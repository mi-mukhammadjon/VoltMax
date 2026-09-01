from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from accounts.models import OTPCode
from ocpp_gateway import commands as ocpp_commands
from sessions_app.models import ChargingSession
from stations.maintenance import open_issue, resolve_open_issues
from stations.models import Station, Connector, MaintenanceIssue, StationAmenity
from management.activity import log_action
from management.models import ActivityLog, SiteSettings
from stations.services import sync_all, sync_connector_from_sessions, sync_station_status
from sessions_app.services import force_stop_session
from dashboard.templatetags.money import format_som
from wallet.models import WalletBalance, Transaction
from .charts import line_chart
from .decorators import staff_required
from .redirects import safe_redirect
from .forms import LoginForm, StationForm, ConnectorForm, StationAmenityForm

PAGE_SIZE = 20


# ─── Auth ─────────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard:home')

    from management import login_guard

    form = LoginForm(request.POST or None)
    error = None
    if request.method == 'POST' and form.is_valid():
        username = form.cleaned_data['username']
        ip = login_guard.client_ip(request)

        # Parol TEKSHIRILISHIDAN oldin blok qaraladi: aks holda bloklangan
        # hisobda ham parolni sinab ko'rish davom etaverardi
        locked, minutes = login_guard.is_locked(username, ip)
        if locked:
            login_guard.record(request, username, successful=False)
            error = (f"Urinishlar chegarasi tugadi. {minutes} daqiqadan keyin "
                     f"qayta urinib ko'ring.")
            return render(request, 'dashboard/login.html',
                          {'form': form, 'error': error})

        user = authenticate(
            request,
            username=username,
            password=form.cleaned_data['password'],
        )
        login_guard.record(request, username, successful=user is not None)

        if user is None:
            # Nechta urinish qolganini aytamiz: haqiqiy operator adashib
            # parol kiritganda bloklanish kutilmagan bo'lmasligi kerak
            limit = SiteSettings.load().panel_max_attempts
            left = limit - login_guard.recent_failures(username, ip) if limit else 0
            error = "Login yoki parol noto'g'ri"
            if limit and 0 < left <= 3:
                error += f'. Yana {left} ta urinish qoldi.'
        else:
            # Ikki bosqichli kirish yoqilgan bo'lsa, parol hali kirish
            # emas: foydalanuvchi HALI TIZIMGA KIRITILMAYDI, faqat
            # "kim ekani" sessiyada belgilanadi va kod so'raladi.
            from management.totp import TwoFactor

            second = TwoFactor.objects.filter(user=user).first()
            if second is not None and second.is_active:
                request.session['pending_2fa_user'] = user.pk
                request.session['pending_2fa_at'] = timezone.now().isoformat()
                return redirect('dashboard:login_2fa')

            _finish_login(request, user)
            return redirect('dashboard:home')
    return render(request, 'dashboard/login.html', {'form': form, 'error': error})


def logout_view(request):
    logout(request)
    return redirect('dashboard:login')


# ─── Bosh sahifa ────────────────────────────────────────────────
WEEKDAY_SHORT = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya']


def _revenue_chart(days=7):
    """Oxirgi `days` kunlik tushum — ustunli grafik uchun.

    Balandlik foizi shu yerda hisoblanadi (shablonda arifmetika qilib bo'lmaydi),
    shuning uchun har element `height` bilan keladi."""
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)

    rows = (
        Transaction.objects
        .filter(type=Transaction.Type.CHARGE_PAYMENT, created_at__date__gte=start)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Sum('amount'))
    )
    by_day = {r['day']: r['total'] or 0 for r in rows}

    points = []
    for i in range(days):
        day = start + timedelta(days=i)
        points.append({
            'day': day,
            'label': WEEKDAY_SHORT[day.weekday()],
            'amount': by_day.get(day, 0),
            'is_today': day == today,
        })

    peak = max((p['amount'] for p in points), default=0)
    for p in points:
        # Nolinchi kun ham ko'rinib turishi uchun minimal balandlik 2%
        p['height'] = round(p['amount'] / peak * 100) if peak else 0
    return points, sum(p['amount'] for p in points)


def _percent(part, whole):
    return round(part / whole * 100) if whole else 0


@staff_required
def home(request):
    stations = Station.objects.all()
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)

    # Ikki kunlik tushum bitta so'rovda: ular bir xil jadvaldan va
    # yonma-yon ko'rsatiladi
    paid = Transaction.objects.filter(type=Transaction.Type.CHARGE_PAYMENT)
    revenue = paid.filter(created_at__date__in=[today, yesterday]).aggregate(
        today=Sum('amount', filter=Q(created_at__date=today)),
        yesterday=Sum('amount', filter=Q(created_at__date=yesterday)),
    )
    today_revenue = revenue['today'] or 0
    yesterday_revenue = revenue['yesterday'] or 0

    # Holatlar BITTA so'rovda sanaladi. Ilgari har biri uchun alohida
    # `COUNT` ketardi — to'rt so'rov, hammasi bir xil jadvaldan.
    by_status = dict(
        stations.values_list('status').annotate(n=Count('id')).values_list('status', 'n'))
    total_stations = sum(by_status.values())
    available = by_status.get(Station.Status.AVAILABLE, 0)
    busy = by_status.get(Station.Status.BUSY, 0)
    offline = by_status.get(Station.Status.OFFLINE, 0)

    active_sessions = ChargingSession.objects.filter(status=ChargingSession.Status.CHARGING).count()
    today_sessions = ChargingSession.objects.filter(started_at__date=today).count()
    new_users_today = User.objects.filter(date_joined__date=today).count()

    # Ulagichlar kesimi — stansiya emas, ulagich darajasidagi haqiqiy
    # bandlik. Bu ham bitta so'rovda (yuqoridagi kabi to'rttada emas).
    connector_by_status = dict(
        Connector.objects.values_list('status').annotate(n=Count('id'))
        .values_list('status', 'n'))
    connector_stats = {
        'total': sum(connector_by_status.values()),
        'available': connector_by_status.get(Connector.Status.AVAILABLE, 0),
        'charging': connector_by_status.get(Connector.Status.CHARGING, 0),
        'offline': connector_by_status.get(Connector.Status.OFFLINE, 0),
    }

    revenue_points, week_revenue = _revenue_chart()

    stats = {
        'total': total_stations,
        'available': available,
        'busy': busy,
        'offline': offline,
        'users': User.objects.count(),
        'new_users_today': new_users_today,
        'active_sessions': active_sessions,
        'today_sessions': today_sessions,
        'total_balance': WalletBalance.objects.aggregate(total=Sum('amount'))['total'] or 0,
        'today_revenue': today_revenue,
        'yesterday_revenue': yesterday_revenue,
        'revenue_delta': today_revenue - yesterday_revenue,
        'week_revenue': week_revenue,
        'available_pct': _percent(available, total_stations),
    }

    # Donut segmentlari: stroke-dasharray uchun tayyor foizlar
    donut = [
        {'name': "Bo'sh", 'value': available, 'pct': _percent(available, total_stations), 'color': 'var(--success)'},
        {'name': 'Band', 'value': busy, 'pct': _percent(busy, total_stations), 'color': 'var(--warning)'},
        {'name': 'Ishlamayapti', 'value': offline, 'pct': _percent(offline, total_stations), 'color': 'var(--text-muted)'},
    ]
    # SVG donut: har segment stroke-dasharray="<segment> <qolgan>" bilan chiziladi.
    # Django shablonida arifmetika yo'q — qiymatlar shu yerda tayyorlanadi.
    offset = 0
    for seg in donut:
        seg['dash'] = seg['pct']
        seg['gap'] = 100 - seg['pct']
        seg['offset'] = offset
        offset += seg['pct']

    # `annotate` ATAYLAB: shablon har stansiya uchun `connectors.count`
    # so'rardi va bu beshta ortiqcha so'rov edi (N+1). Ro'yxat qisqa
    # bo'lgani uchun sezilmasdi, lekin bu naqsh uzun ro'yxatda
    # qimmatga tushadi.
    recent_stations = (stations.order_by('-created_at')
                       .annotate(connector_total=Count('connectors'))[:5])
    recent_sessions = ChargingSession.objects.select_related('user', 'station').order_by('-started_at')[:5]
    # Tizim holati: muammo BO'LSAGINA ko'rsatiladi. Hamma narsa joyida
    # bo'lganda ham banner chiqarish uni "fon shovqini"ga aylantirardi va
    # haqiqiy muammo paytida ham e'tiborsiz qolinardi.
    from management.health import collect

    # `cached=True` va tarmoqsiz: dashboard har yuklashda o'nlab
    # so'rov qilmasin va begona xizmatning javobini kutmasin.
    # Alohida «Tizim holati» sahifasi har doim yangisini oladi.
    health = collect(cached=True, with_network=False)

    return render(request, 'dashboard/home.html', {
        'health': health if health['overall'] != 'ok' else None,
        'stats': stats,
        'connector_stats': connector_stats,
        'revenue_points': revenue_points,
        'donut': donut,
        'recent_stations': recent_stations,
        'recent_sessions': recent_sessions,
    })


# ─── Stansiyalar ──────────────────────────────────────────────
@staff_required
def stations_list(request):
    from management.models import Partner

    stations = Station.objects.select_related('partner').prefetch_related('connectors').all()

    q = request.GET.get('q', '').strip()
    if q:
        stations = stations.filter(name__icontains=q) | stations.filter(address__icontains=q)

    status = request.GET.get('status', '').strip()
    if status in dict(Station.Status.choices):
        stations = stations.filter(status=status)

    partner_id = request.GET.get('partner', '').strip()
    if partner_id == 'none':
        stations = stations.filter(partner__isnull=True)
    elif partner_id.isdigit():
        stations = stations.filter(partner_id=int(partner_id))

    ocpp = request.GET.get('ocpp', '').strip()
    if ocpp == 'linked':
        stations = stations.exclude(ocpp_id__isnull=True).exclude(ocpp_id='')
    elif ocpp == 'unlinked':
        stations = stations.filter(ocpp_id__isnull=True) | stations.filter(ocpp_id='')

    all_stations = Station.objects.all()
    summary = {
        'total': all_stations.count(),
        'available': all_stations.filter(status=Station.Status.AVAILABLE).count(),
        'busy': all_stations.filter(status=Station.Status.BUSY).count(),
        'offline': all_stations.filter(status=Station.Status.OFFLINE).count(),
        'unassigned': all_stations.filter(partner__isnull=True).count(),
    }

    page_obj = Paginator(stations.order_by('name'), PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'dashboard/stations.html', {
        'page_obj': page_obj,
        'q': q,
        'status': status,
        'partner_id': partner_id,
        'ocpp': ocpp,
        'status_choices': Station.Status.choices,
        'partners': Partner.objects.all(),
        'summary': summary,
        'result_count': stations.count(),
    })


def device_state(station):
    """Stansiyaning qurilma holati — formada ko'rsatish uchun.

    Holat maydoni formadan olib tashlangani sababli operator "hozir nima
    bo'lyapti" degan savolga javob ko'rishi kerak. Bu yerda faqat O'QILADI —
    hech narsa o'zgartirilmaydi.
    """
    if station is None:
        return {'health': 'new', 'label': 'Hali ulanmagan',
                'note': "Stansiya saqlangach OCPP ID kiritsangiz, holat shu yerda ko'rinadi"}
    if not station.ocpp_id:
        return {'health': 'none', 'label': 'Charger ulanmagan',
                'note': "Holat ulagichlardan hisoblanadi. Jismoniy qurilma uchun OCPP ID kiriting"}
    if not station.is_online:
        seen = station.ocpp_last_seen_at
        return {'health': 'down', 'label': "Aloqa yo'q",
                'note': (f'Oxirgi signal: {seen:%d.%m.%Y %H:%M}' if seen
                         else 'Charger hali birorta ham xabar yubormagan')}

    faulted = [c for c in station.connectors.all() if c.status == Connector.Status.OFFLINE]
    if faulted:
        labels = ', '.join(c.label for c in faulted)
        return {'health': 'warn', 'label': 'Onlayn, nosozlik bilan',
                'note': f'Ishlamayotgan ulagichlar: {labels}'}

    return {'health': 'ok', 'label': 'Onlayn',
            'note': f'Joriy holat: {station.get_status_display()}'}


@staff_required
def station_form_view(request, pk=None):
    instance = get_object_or_404(Station, pk=pk) if pk else None
    form = StationForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        station = form.save()
        messages.success(request, 'Saqlandi')
        return redirect('dashboard:station_detail', pk=station.pk)
    return render(request, 'dashboard/station_form.html', {
        'form': form,
        'instance': instance,
        # Holat formada tanlanmaydi — qurilmadan o'qiladi va shu blokda ko'rinadi
        'device': device_state(instance),
    })


@staff_required
def station_delete(request, pk):
    station = get_object_or_404(Station, pk=pk)
    if request.method == 'POST':
        station.delete()
        messages.success(request, "O'chirildi")
    return redirect('dashboard:stations')


@staff_required
def station_detail(request, pk):
    station = get_object_or_404(Station, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_connector':
            connector_form = ConnectorForm(request.POST, station=station)
            if connector_form.is_valid():
                connector = connector_form.save(commit=False)
                connector.station = station
                connector.save()
                messages.success(request, f"{connector.label} ulagichi qo'shildi")
            else:
                # Forma qatorli (inline) bo'lgani uchun xatolar maydon ostida
                # ko'rinmaydi — ularni toast'ga chiqaramiz, aks holda operator
                # "saqlanmadi" degan umumiy gapdan sababni topa olmasdi.
                for field, errors in connector_form.errors.items():
                    name = connector_form.fields[field].label if field in connector_form.fields else ''
                    for error in errors:
                        messages.error(request, f'{name}: {error}' if name else error)
            return redirect('dashboard:station_detail', pk=pk)
        elif action == 'add_amenity':
            amenity_form = StationAmenityForm(request.POST)
            if amenity_form.is_valid():
                amenity = amenity_form.save(commit=False)
                amenity.station = station
                amenity.save()
                messages.success(request, "Qulaylik qo'shildi")
            else:
                messages.error(request, "Qulaylikni saqlab bo'lmadi — maydonlarni tekshiring")
            return redirect('dashboard:station_detail', pk=pk)

    from django.db.models import Avg
    from management.models import Partner

    # Faol sessiyalar ulagich bo'yicha indekslanadi — har ulagich qatorida
    # kim zaryadlanayotgani va necha foizda ekani ko'rsatiladi.
    active_sessions = list(
        ChargingSession.objects
        .filter(station=station, status=ChargingSession.Status.CHARGING)
        .select_related('user', 'connector')
    )
    sessions_by_connector = {s.connector_id: s for s in active_sessions}

    connectors = []
    for connector in station.connectors.all():
        connectors.append({
            'obj': connector,
            'session': sessions_by_connector.get(connector.id),
            'parking': connector.parking_mode,
            'parking_minutes': connector.parking_minutes,
        })

    finished = ChargingSession.objects.filter(station=station).exclude(
        status=ChargingSession.Status.CHARGING
    )
    stats = {
        'sessions_total': ChargingSession.objects.filter(station=station).count(),
        'revenue': finished.aggregate(t=Sum('final_cost'))['t'] or 0,
        'kwh': round(sum(s.kwh_charged for s in finished), 1),
        'rating': station.average_rating,
        'reviews': station.review_count,
    }

    return render(request, 'dashboard/station_detail.html', {
        'station': station,
        'connector_form': ConnectorForm(station=station),
        'amenity_form': StationAmenityForm(),
        'partners': Partner.objects.filter(is_active=True),
        'active_sessions': active_sessions,
        'connectors': connectors,
        'stats': stats,
        'recent_sessions': ChargingSession.objects.filter(station=station)
            .select_related('user').order_by('-started_at')[:8],
        'reviews': station.reviews.select_related('user').order_by('-created_at')[:5],
        # Qurilma haqidagi ma'lumot — BootNotification/GetConfiguration'dan
        'info': getattr(station, 'info', None),
        'configuration': station.configuration.all(),
        'logs': station.logs.all()[:15],
    })


@staff_required
def connector_delete(request, pk, connector_pk):
    connector = get_object_or_404(Connector, pk=connector_pk, station_id=pk)
    if request.method == 'POST':
        connector.delete()
        messages.success(request, "Ulagich o'chirildi")
    return redirect('dashboard:station_detail', pk=pk)


@staff_required
def amenity_delete(request, pk, amenity_pk):
    amenity = get_object_or_404(StationAmenity, pk=amenity_pk, station_id=pk)
    if request.method == 'POST':
        amenity.delete()
        messages.success(request, "Qulaylik o'chirildi")
    return redirect('dashboard:station_detail', pk=pk)


@staff_required
def connector_remote_start(request, pk, connector_pk):
    connector = get_object_or_404(Connector, pk=connector_pk, station_id=pk)
    if request.method == 'POST':
        from stations.rules import is_working_now

        working, closed_reason = is_working_now()
        if not connector.station.ocpp_id or not connector.ocpp_connector_id:
            messages.error(request, "Bu ulagich hali OCPP charger'ga bog'lanmagan")
        elif not working:
            # Operator ish vaqtidan tashqarida ham boshlashi mumkin, lekin
            # buni bilib turishi kerak — cheklov o'zi qo'ygan sozlamada
            messages.error(
                request,
                f"{closed_reason} Sozlamalar > Sessiya bo'limida "
                "ish vaqtini o'zgartiring.")
        else:
            ocpp_commands.remote_start_transaction(
                connector.station.ocpp_id, connector.ocpp_connector_id, id_tag=f'DASH-{request.user.username}'
            )
            log_action(request, ActivityLog.Action.DEVICE,
                       f'Masofadan boshlash — {connector.station.name} / {connector.label}',
                       url=f'/stations/{connector.station_id}/')
            messages.success(request, "Masofadan boshlash buyrug'i yuborildi")
    return safe_redirect(request, redirect('dashboard:station_detail', pk=pk).url)


@staff_required
def connector_remote_stop(request, pk, connector_pk):
    """Ulagichdagi zaryadlashni majburan uzadi.

    Faol sessiya bo'lsa — chargerga buyruq + DB'da yakunlash.
    Sessiya topilmasa, lekin ulagich "zaryadlanmoqda" bo'lib qolgan bo'lsa —
    bu nomuvofiqlik, ulagich shunchaki bo'shatiladi (sinxronlash)."""
    connector = get_object_or_404(Connector, pk=connector_pk, station_id=pk)
    if request.method == 'POST':
        session = ChargingSession.objects.filter(
            connector=connector, status=ChargingSession.Status.CHARGING
        ).order_by('-started_at').first()

        if session is not None:
            result = force_stop_session(session, actor=request.user.username)
            log_action(request, ActivityLog.Action.SESSION,
                       f"Sessiya majburan to'xtatildi — {connector.station.name}",
                       detail=f'{connector.label} ulagichi, sessiya #{session.pk}',
                       url=f'/sessions/{session.pk}/')
            if result.charger_notified:
                messages.success(request, "Zaryadlash uzildi va chargerga buyruq yuborildi")
            else:
                messages.success(request, 'Zaryadlash uzildi')
            if result.warning:
                messages.error(request, result.warning)
        elif sync_connector_from_sessions(connector):
            messages.success(request, "Faol sessiya topilmadi — ulagich holati sinxronlandi")
        else:
            messages.error(request, "Bu ulagichda zaryadlash yo'q")
    return safe_redirect(request, redirect('dashboard:station_detail', pk=pk).url)


# ─── Foydalanuvchilar ───────────────────────────────────────────
@staff_required
def users_list(request):
    # `profile` ham olinadi: avatar har qator uchun ko'rsatiladi va
    # usiz har qatorga alohida so'rov ketardi (N+1)
    users = (
        User.objects.select_related('wallet', 'profile')
        .annotate(session_count=Count('charging_sessions', distinct=True))
        .order_by('-date_joined')
    )
    q = request.GET.get('q', '').strip()
    if q:
        users = users.filter(username__icontains=q)

    page_obj = Paginator(users, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'dashboard/users.html', {'page_obj': page_obj, 'q': q})


@staff_required
def user_detail(request, pk):
    user = get_object_or_404(
        User.objects.select_related('profile')
        .annotate(session_count=Count('charging_sessions', distinct=True)), pk=pk
    )
    wallet = getattr(user, 'wallet', None)
    # Ikki jadval — ikki sahifa kaliti (`page` sessiyalar, `tpage` tranzaksiyalar)
    sessions_page = Paginator(
        user.charging_sessions.select_related('station').order_by('-started_at'), 10
    ).get_page(request.GET.get('page'))
    transactions_page = Paginator(
        user.transactions.order_by('-created_at'), 10
    ).get_page(request.GET.get('tpage'))
    return render(request, 'dashboard/user_detail.html', {
        'phone_user': user,
        'wallet': wallet,
        'sessions_page': sessions_page,
        'transactions_page': transactions_page,
        # Mijozning RFID kartalari — sessiya kim hisobidan yechilishini
        # aynan shu bog'lanish hal qiladi.
        'rfid_cards': user.rfid_cards.order_by('-created_at'),
    })


@staff_required
def user_toggle_active(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        log_action(request, ActivityLog.Action.OTHER,
                   f"{user.username}: "
                   f"{'faollashtirildi' if user.is_active else 'bloklandi'}",
                   url=f'/users/{user.pk}/')
        messages.success(request, 'Faollashtirildi' if user.is_active else 'Bloklandi')
    return redirect('dashboard:user_detail', pk=pk)


# ─── OTP kodlar ─────────────────────────────────────────────────
@staff_required
def otp_list(request):
    codes = OTPCode.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        codes = codes.filter(phone__icontains=q)

    page_obj = Paginator(codes, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'dashboard/otp_list.html', {'page_obj': page_obj, 'q': q})


# ─── Zaryadlash sessiyalari ─────────────────────────────────────
@staff_required
def sessions_list(request):
    sessions = ChargingSession.objects.select_related('user', 'station')
    status = request.GET.get('status', '').strip()
    if status in ChargingSession.Status.values:
        sessions = sessions.filter(status=status)
    q = request.GET.get('q', '').strip()
    if q:
        sessions = sessions.filter(user__username__icontains=q) | sessions.filter(station__name__icontains=q)
    sessions = sessions.order_by('-started_at')

    page_obj = Paginator(sessions, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'dashboard/sessions.html', {
        'page_obj': page_obj, 'q': q, 'status': status,
        'status_choices': ChargingSession.Status.choices,
    })


# OCPP StopTransaction.reason -> odam o'qiydigan izoh. Bu qiymat nosozlik
# tahlilida eng kerakli ma'lumotlardan biri: zaryadlash o'z-o'zidan tugadimi,
# kabel uzildimi yoki tok o'chdimi.
STOP_REASONS = {
    'EmergencyStop': 'Avariya tugmasi bosildi',
    'EVDisconnected': 'Kabel avtomobildan uzildi',
    'HardReset': 'Qurilma majburan qayta yuklandi',
    'Local': "Chargerning o'zida to'xtatildi",
    'Other': 'Boshqa sabab',
    'PowerLoss': "Elektr ta'minoti uzildi",
    'Reboot': 'Qurilma qayta yuklandi',
    'Remote': "Masofadan to'xtatildi",
    'SoftReset': 'Qurilma dasturiy qayta yuklandi',
    'UnlockCommand': 'Ulagich qulfi ochildi',
    'DeAuthorized': 'Ruxsat bekor qilindi',
}


@staff_required
def session_detail(request, pk):
    session = get_object_or_404(
        ChargingSession.objects.select_related('user', 'station', 'connector', 'vehicle'), pk=pk
    )
    readings = list(session.readings.all())

    return render(request, 'dashboard/session_detail.html', {
        'session': session,
        'readings_count': len(readings),
        # Kuchlanish dinamikasi — asosiy grafik. Tok va quvvat yonida
        # kichik ko'rsatkich sifatida beriladi (charger yuborgan bo'lsa).
        'voltage_chart': line_chart(readings, value_getter=lambda r: r.voltage_v, unit='V'),
        'current_chart': line_chart(readings, value_getter=lambda r: r.current_a, unit='A', decimals=1),
        'soc_chart': line_chart(readings, value_getter=lambda r: r.soc_percent, unit='%'),
        'temp_chart': line_chart(readings, value_getter=lambda r: r.temperature_c, unit='°C', decimals=1),
        'last_reading': readings[-1] if readings else None,
        'stop_reason': STOP_REASONS.get(session.stop_reason, session.stop_reason),
    })


@staff_required
def session_force_stop(request, pk):
    """Majburan to'xtatish: haqiqiy chargerga RemoteStopTransaction yuboriladi
    va shu bilan birga sessiya DB'da yakunlanadi (hisob + hamyon + ulagich)."""
    session = get_object_or_404(ChargingSession, pk=pk)
    if request.method == 'POST':
        result = force_stop_session(session, actor=request.user.username)
        if not result.stopped:
            messages.error(request, result.warning or "Sessiyani to'xtatib bo'lmadi")
        else:
            if result.charger_notified:
                messages.success(
                    request,
                    f"Sessiya to'xtatildi va chargerga uzish buyrug'i yuborildi. "
                    f"Yakuniy summa: {format_som(result.final_cost)} so'm",
                )
            else:
                messages.success(
                    request, f"Sessiya to'xtatildi. Yakuniy summa: {format_som(result.final_cost)} so'm"
                )
            if result.warning:
                messages.error(request, result.warning)
    # `next` — tugma qaysi sahifadan bosilgan bo'lsa, o'sha yerga qaytaramiz
    return safe_redirect(request, redirect('dashboard:session_detail', pk=pk).url)


# ─── Tranzaksiyalar ─────────────────────────────────────────────
@staff_required
def transactions_list(request):
    transactions = Transaction.objects.select_related('user')
    tx_type = request.GET.get('type', '').strip()
    if tx_type in Transaction.Type.values:
        transactions = transactions.filter(type=tx_type)
    q = request.GET.get('q', '').strip()
    if q:
        transactions = transactions.filter(user__username__icontains=q) | transactions.filter(description__icontains=q)
    transactions = transactions.order_by('-created_at')

    page_obj = Paginator(transactions, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'dashboard/transactions.html', {
        'page_obj': page_obj, 'q': q, 'tx_type': tx_type,
        'type_choices': Transaction.Type.choices,
    })


@staff_required
def sync_status(request):
    """Butun tarmoqning holatini qayta hisoblaydi: sessiyasiz "zaryadlanmoqda"
    ulagichlarni bo'shatadi, stansiya holatini ulagichlaridan chiqaradi."""
    if request.method == 'POST':
        result = sync_all()
        asked = sum(1 for st in Station.objects.exclude(ocpp_id__isnull=True).exclude(ocpp_id='')
                    if _request_device_status(st))
        if asked:
            messages.success(request, f"{asked} ta chargerdan joriy holat so'raldi")
        if result['connectors'] or result['stations']:
            messages.success(
                request,
                f"Sinxronlandi: {result['connectors']} ta ulagich, {result['stations']} ta stansiya to'g'rilandi",
            )
        else:
            messages.success(request, 'Hammasi mos — tuzatish talab qilinmadi')
    return safe_redirect(request, 'dashboard:stations_health')


@staff_required
def station_sync(request, pk):
    """Bitta stansiyaning ulagich/holatini sessiyalarga qarab to'g'rilaydi."""
    station = get_object_or_404(Station, pk=pk)
    if request.method == 'POST':
        fixed = 0
        for connector in station.connectors.all():
            if sync_connector_from_sessions(connector):
                fixed += 1
        station.refresh_from_db()
        station_changed = sync_station_status(station)

        # Bazani moslash — bu faqat yarim ish. Qurilmadan ham haqiqiy holatni
        # so'raymiz; javob kelganda consumers.py uni o'zi yozib qo'yadi.
        asked = _request_device_status(station)

        if fixed or station_changed:
            messages.success(request, f"Sinxronlandi: {fixed} ta ulagich to'g'rilandi")
        else:
            messages.success(request, 'Baza holati mos')
        if asked:
            messages.success(request, "Qurilmadan joriy holat so'raldi — javob kelishi bilan yangilanadi")
        elif station.ocpp_id:
            messages.error(request, "Charger oflayn — qurilmadan holat so'rab bo'lmadi")
    return redirect('dashboard:station_detail', pk=pk)


def _push_availability(request, connector, operative: bool) -> bool:
    """Ulagich holatini chargerga uzatadi. Yetkazilgan bo'lsa True."""
    station = connector.station
    if not station.ocpp_id or not connector.ocpp_connector_id:
        return False
    if not station.is_online:
        messages.error(
            request,
            "Charger oflayn — holat faqat bazada o'zgardi. Qurilma buyruqni olmadi, "
            "shuning uchun u hali ham mahalliy zaryadlashni qabul qilishi mumkin.",
        )
        return False
    try:
        ocpp_commands.change_availability(station.ocpp_id, connector.ocpp_connector_id, operative)
        return True
    except Exception as exc:
        messages.error(request, f"Chargerga buyruq yuborilmadi: {exc}")
        return False


def _request_device_status(station) -> bool:
    """Chargerdan haqiqiy holatini qayta yuborishni so'raydi (TriggerMessage).
    Javob StatusNotification sifatida keladi va consumers.py uni bazaga yozadi."""
    if not station.ocpp_id or not station.is_online:
        return False
    try:
        ocpp_commands.trigger_status_notification(station.ocpp_id)
        return True
    except Exception:
        return False


# ─── Ulagichni tahrirlash ───────────────────────────────────────
def connector_state(connector):
    """Ulagichning joriy holati — formada ko'rsatish uchun (faqat o'qiydi).

    Stansiyadagi `device_state` bilan bir xil shaklda qaytaradi, shunda
    ikkala sahifada bitta uslub ishlaydi.
    """
    station = connector.station

    if connector.status == Connector.Status.OFFLINE:
        return {'health': 'down', 'label': 'Ishlamayapti',
                'note': connector.offline_reason or 'Sabab ko\'rsatilmagan'}
    if connector.status == Connector.Status.CHARGING:
        note = 'Zaryadlash ketmoqda'
        if connector.parking_mode:
            note = f'Pullik parkovka — {connector.parking_minutes} daqiqa'
        return {'health': 'warn', 'label': 'Band', 'note': note}

    if station.ocpp_id and not station.is_online:
        return {'health': 'down', 'label': "Charger bilan aloqa yo'q",
                'note': "Ulagich bo'sh ko'rinadi, lekin qurilma javob bermayapti"}
    if not station.ocpp_id or not connector.ocpp_connector_id:
        return {'health': 'none', 'label': "Bo'sh (qurilmasiz)",
                'note': "OCPP bog'lanmagan — holat faqat qo'lda boshqariladi"}

    return {'health': 'ok', 'label': "Bo'sh", 'note': 'Qurilma bilan aloqa bor'}


@staff_required
def connector_edit(request, pk, connector_pk):
    """Ulagichning xossalarini tahrirlash: yorliq, turi, quvvat, OCPP raqami.

    Holat bu yerda o'zgartirilmaydi — u qurilmadan keladi yoki Profilaktika
    bo'limida qo'yiladi. Sahifada u faqat KO'RSATILADI, tezkor amallar esa
    o'sha bo'limga olib boradi.
    """
    connector = get_object_or_404(Connector, pk=connector_pk, station_id=pk)
    active = ChargingSession.objects.filter(
        connector=connector, status=ChargingSession.Status.CHARGING
    ).first()

    # OCPP raqami sessiya davomida o'zgarsa, chargerdan keladigan xabarlar
    # boshqa yozuvga tusha boshlaydi va ketayotgan zaryadlash "yo'qoladi".
    old_ocpp_id = connector.ocpp_connector_id

    form = ConnectorForm(request.POST or None, instance=connector)
    if request.method == 'POST' and form.is_valid():
        if active and form.cleaned_data.get('ocpp_connector_id') != old_ocpp_id:
            messages.error(
                request,
                "Bu ulagichda zaryadlash ketmoqda — OCPP raqamini hozir "
                "o'zgartirib bo'lmaydi, avval sessiyani to'xtating.",
            )
        else:
            connector = form.save()
            messages.success(request, 'Ulagich saqlandi')
            return redirect('dashboard:station_detail', pk=pk)

    return render(request, 'dashboard/connector_form.html', {
        'form': form,
        'connector': connector,
        'station': connector.station,
        'active_session': active,
        'state': connector_state(connector),
        'open_issue': connector.issues.filter(
            status=MaintenanceIssue.Status.OPEN
        ).first(),
    })


@staff_required
def connector_toggle_service(request, pk, connector_pk):
    """Tezkor amal: ulagichni xizmatdan chiqarish / xizmatga qaytarish.

    Operator ko'pincha shuni xohlaydi — to'liq formani ochmasdan ulagichni
    ta'mirga qo'yish yoki qaytarish."""
    connector = get_object_or_404(Connector, pk=connector_pk, station_id=pk)
    if request.method == 'POST':
        active = ChargingSession.objects.filter(
            connector=connector, status=ChargingSession.Status.CHARGING
        ).exists()
        if active:
            messages.error(request, "Faol sessiya bor — avval zaryadlashni to'xtating")
        else:
            operative = connector.status == Connector.Status.OFFLINE
            if operative:
                connector.status = Connector.Status.AVAILABLE
                connector.offline_reason = ''
            else:
                connector.status = Connector.Status.OFFLINE
                connector.offline_reason = (request.POST.get('reason') or '').strip()[:200]                     or "Ta'mirlash ishlari olib borilmoqda"
            connector.save(update_fields=['status', 'offline_reason'])

            # Profilaktika yozuvi — qo'lda qilingan amal ham tarixda qolsin,
            # aks holda bo'lim faqat qurilma xabarlarini ko'rsatardi.
            if operative:
                resolve_open_issues(
                    station=connector.station, connector=connector,
                    user=request.user, note='Panel orqali xizmatga qaytarildi',
                )
            else:
                open_issue(
                    station=connector.station, connector=connector,
                    reason=connector.offline_reason,
                    source=MaintenanceIssue.Source.MANUAL,
                )

            # Qurilmaning o'zida ham yoqib/o'chirib qo'yamiz — aks holda charger
            # bu haqda bilmay, RFID karta bilan mahalliy zaryadlashni qabul qilaveradi.
            delivered = _push_availability(request, connector, operative)
            action = 'xizmatga qaytarildi' if operative else 'xizmatdan chiqarildi'
            suffix = ' va qurilmaga buyruq yuborildi' if delivered else ''
            messages.success(request, f'{connector.label} ulagichi {action}{suffix}')

        connector.station.refresh_from_db()
        sync_station_status(connector.station)

    return safe_redirect(request, redirect('dashboard:station_detail', pk=pk).url)


# ─── Ikki bosqichli kirish ──────────────────────────────────────
# Parolgacha bo'lgan yarim holat shu qadar yashaydi: kod so'ralgan
# sahifada cheksiz turib qolgan sessiya ochiq qoldirilmasin.
PENDING_2FA_MINUTES = 5


def _finish_login(request, user):
    """Sessiyani ochadi va muddatini sozlamadan oladi.

    Ikki joydan chaqiriladi (oddiy kirish va kod tasdiqlangach), shuning
    uchun alohida funksiya: sessiya muddati bir joyda unutilib qolmasin.
    """
    login(request, user)
    minutes = SiteSettings.load().session_timeout_minutes
    if minutes:
        request.session.set_expiry(minutes * 60)


def login_2fa_view(request):
    """Parol to'g'ri bo'lgach — telefondagi kod.

    Foydalanuvchi bu bosqichda hali TIZIMGA KIRMAGAN: `login()` faqat kod
    tasdiqlangach chaqiriladi. Shuning uchun parolni bilgan, lekin
    telefoni yo'q odam hech qanday sahifani ocha olmaydi.
    """
    from datetime import datetime

    from management import login_guard
    from management.totp import TwoFactor

    user_id = request.session.get('pending_2fa_user')
    started = request.session.get('pending_2fa_at')
    if not user_id or not started:
        return redirect('dashboard:login')

    # Yarim holat uzoq yashamasin: kompyuter qarovsiz qolsa, kod
    # sahifasi ochiq turib, keyin kimdir kod kiritishi mumkin edi
    try:
        age = (timezone.now() - datetime.fromisoformat(started)).total_seconds()
    except (TypeError, ValueError):
        age = PENDING_2FA_MINUTES * 60 + 1
    if age > PENDING_2FA_MINUTES * 60:
        request.session.pop('pending_2fa_user', None)
        request.session.pop('pending_2fa_at', None)
        return redirect('dashboard:login')

    user = User.objects.filter(pk=user_id).first()
    second = TwoFactor.objects.filter(user=user).first() if user else None
    if user is None or second is None or not second.is_active:
        return redirect('dashboard:login')

    error = None
    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip()

        # Kod ham parol kabi tanlanishi mumkin — o'sha chegara qo'llanadi
        ip = login_guard.client_ip(request)
        locked, minutes = login_guard.is_locked(user.username, ip)
        if locked:
            error = (f"Urinishlar chegarasi tugadi. {minutes} daqiqadan keyin "
                     f"qayta urinib ko'ring.")
        elif second.verify_code(code):
            login_guard.record(request, user.username, successful=True)
            request.session.pop('pending_2fa_user', None)
            request.session.pop('pending_2fa_at', None)
            _finish_login(request, user)
            if second.backup_left <= 2:
                messages.warning(
                    request,
                    f'Zaxira kodlaringizdan {second.backup_left} tasi qoldi — '
                    f'Profil sahifasida yangilang')
            return redirect('dashboard:home')
        else:
            login_guard.record(request, user.username, successful=False)
            error = "Kod noto'g'ri yoki muddati o'tgan"

    return render(request, 'dashboard/login_2fa.html', {
        'error': error,
        'username': user.username,
        'backup_left': second.backup_left,
    })


# ─── Parolni tiklash ────────────────────────────────────────────
# Ilgari parolni faqat SERVERDAN tiklash mumkin edi
# (`manage.py changepassword`). Ya'ni operator parolini unutsa,
# dasturchini kutib o'tirardi.
#
# Havola Django ning o'z token generatori bilan imzolanadi: u
# foydalanuvchining parol hash'i va oxirgi kirish vaqtiga bog'langan,
# shuning uchun parol o'zgargach yoki bir marta ishlatilgach eskiradi.
PASSWORD_RESET_HOURS = 2


def password_reset_request(request):
    """Pochta so'raydi va tiklash havolasini yuboradi."""
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    from management import login_guard
    from management.mail import is_configured, try_send

    sent = False
    error = None

    if request.method == 'POST':
        email = (request.POST.get('email') or '').strip()

        if not is_configured():
            error = ('Pochta sozlanmagan — administratorga murojaat qiling '
                     'yoki serverda `manage.py changepassword` ni bajaring')
        else:
            # Javob HAR DOIM bir xil: "yuborildi". Aks holda bu sahifa
            # qaysi pochta ro'yxatda borligini aniqlash vositasiga
            # aylanardi.
            sent = True
            hours = int(settings.PASSWORD_RESET_TIMEOUT / 3600) or 1

            # Django'da pochta NOYOB EMAS: bir manzil bir necha
            # hisobga yozilgan bo'lishi mumkin. Ilgari `.first()`
            # olinardi va qaysi hisob tanlanishi tasodifga bog'liq
            # edi — odam kutgan hisobi o'rniga boshqasining
            # havolasini olardi.
            #
            # Endi har biriga alohida havola ketadi va xatda qaysi
            # login ekani aytiladi. Xat baribir o'sha pochta
            # egasiga boradi, ya'ni qo'shimcha xavf tug'dirmaydi.
            accounts = list(User.objects.filter(
                email__iexact=email, is_staff=True, is_active=True))

            for user in accounts:
                token = default_token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                link = request.build_absolute_uri(
                    reverse('dashboard:password_reset_confirm',
                            args=[uid, token]))
                whose = (f'«{user.username}» hisobi uchun '
                         if len(accounts) > 1 else '')
                try_send(
                    email,
                    'VoltMax paneli — parolni tiklash',
                    f'Assalomu alaykum!\n\n'
                    f'{whose}Parolni tiklash uchun quyidagi havolaga '
                    f'o\'ting:\n\n'
                    f'{link}\n\n'
                    f'Havola {hours} soat amal qiladi va bir marta '
                    f'ishlatiladi.\n\n'
                    f'Agar bu so\'rovni siz yubormagan bo\'lsangiz, '
                    f'xatni e\'tiborsiz qoldiring — parol o\'zgarmaydi.',
                )
                login_guard.record(request, user.username, successful=False)

    # Muddat sozlamadan olinadi — sahifadagi matn va haqiqiy muddat
    # ajralib qolmasin
    return render(request, 'dashboard/password_reset.html', {
        'sent': sent,
        'error': error,
        'reset_hours': int(settings.PASSWORD_RESET_TIMEOUT / 3600) or 1,
    })


def password_reset_confirm(request, uidb64, token):
    """Havoladagi token to'g'ri bo'lsa yangi parol qo'yishga ruxsat beradi."""
    from django.contrib.auth.password_validation import validate_password
    from django.contrib.auth.tokens import default_token_generator
    from django.core.exceptions import ValidationError
    from django.utils.encoding import force_str
    from django.utils.http import urlsafe_base64_decode

    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        return render(request, 'dashboard/password_reset.html',
                      {'invalid': True})

    error = None
    if request.method == 'POST':
        password = request.POST.get('new_password', '')
        if password != request.POST.get('confirm_password', ''):
            error = 'Parollar mos kelmadi'
        else:
            try:
                validate_password(password, user=user)
            except ValidationError as problem:
                error = ' '.join(problem.messages)
            else:
                user.set_password(password)
                user.save()
                messages.success(request, 'Parol yangilandi — endi kiring')
                return redirect('dashboard:login')

    return render(request, 'dashboard/password_reset.html',
                  {'confirm': True, 'error': error})
