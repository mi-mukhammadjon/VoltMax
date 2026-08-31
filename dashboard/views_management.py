"""Panelning kengaytirilgan bo'limlari.

`views.py` asosiy bo'limlarni (stansiyalar, sessiyalar, foydalanuvchilar,
tranzaksiyalar, OTP) saqlaydi; bu modulda esa hamyonlar, sharhlar, hisobotlar,
stansiya salomatligi, aksiyalar, hamkorlar, xodimlar/rollar, kontent va tizim
sozlamalari bor. Ikkalasi ham `dashboard/urls.py` orqali ulanadi.
"""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.models import Group, User
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils import timezone

from accounts.models import Company
from accounts.models import RfidCard
from management.activity import log_action
from management.holidays import HolidaySyncError, sync_holidays
from management.models import (
    CONTRACT_PLACEHOLDERS, Banner, ContractSection, FaqItem, Holiday, LegalPage,
    ActivityLog, NotificationTemplate, Offer, Partner, PaymentProvider,
    SettingsChange, SiteSettings, UserNotification,
)
from sessions_app.models import ChargingSession
from stations.models import Connector, Review, Station, TariffWindow
from wallet.models import Transaction, WalletBalance

from .decorators import admin_required, staff_required
from .forms import (
    BannerForm,
    FaqItemForm,
    LegalPageForm,
    OfferForm,
    PartnerForm,
    ContractSectionForm,
    NotificationTemplateForm,
    PaymentProviderForm,
    RoleForm,
    SettingsAccessForm,
    SettingsContractForm,
    SettingsGeneralForm,
    SettingsHolidayForm,
    SettingsModeForm,
    SettingsNotificationForm,
    SettingsOrgForm,
    SettingsPriceForm,
    SettingsRfidForm,
    SettingsSessionForm,
    TariffWindowForm,
    SettingsTopupForm,
    StaffUserForm,
)
from .views import PAGE_SIZE, _percent, _revenue_chart


# ═══════════════════════════════════════════════════════════════
#  Hamyonlar
# ═══════════════════════════════════════════════════════════════
@staff_required
def wallets_list(request):
    wallets = WalletBalance.objects.select_related('user').order_by('-amount')
    q = request.GET.get('q', '').strip()
    if q:
        wallets = wallets.filter(user__username__icontains=q)
    page_obj = Paginator(wallets, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'dashboard/wallets.html', {
        'page_obj': page_obj,
        'q': q,
        'total_balance': WalletBalance.objects.aggregate(t=Sum('amount'))['t'] or 0,
        'wallet_count': WalletBalance.objects.count(),
    })


@staff_required
def wallet_detail(request, pk):
    wallet = get_object_or_404(WalletBalance.objects.select_related('user'), pk=pk)
    transactions_page = Paginator(
        Transaction.objects.filter(user=wallet.user).order_by('-created_at'), PAGE_SIZE
    ).get_page(request.GET.get('page'))
    by_type = {
        row['type']: row['t']
        for row in Transaction.objects.filter(user=wallet.user).values('type').annotate(t=Sum('amount'))
    }
    return render(request, 'dashboard/wallet_detail.html', {
        'wallet': wallet,
        'transactions_page': transactions_page,
        'topup_total': by_type.get(Transaction.Type.TOPUP, 0),
        'spent_total': by_type.get(Transaction.Type.CHARGE_PAYMENT, 0),
    })


# ═══════════════════════════════════════════════════════════════
#  Sharhlar
# ═══════════════════════════════════════════════════════════════
@staff_required
def reviews_list(request):
    reviews = Review.objects.select_related('station', 'user').order_by('-created_at')
    rating = request.GET.get('rating', '').strip()
    if rating.isdigit():
        reviews = reviews.filter(rating=int(rating))
    page_obj = Paginator(reviews, PAGE_SIZE).get_page(request.GET.get('page'))

    all_reviews = Review.objects.all()
    total = all_reviews.count()
    avg = all_reviews.aggregate(a=Avg('rating'))['a']
    breakdown = [
        {
            'star': star,
            'count': all_reviews.filter(rating=star).count(),
            'pct': _percent(all_reviews.filter(rating=star).count(), total),
        }
        for star in range(5, 0, -1)
    ]
    return render(request, 'dashboard/reviews.html', {
        'page_obj': page_obj,
        'rating': rating,
        'total': total,
        'average': round(avg, 1) if avg else 0,
        'breakdown': breakdown,
    })


@staff_required
def review_delete(request, pk):
    review = get_object_or_404(Review, pk=pk)
    if request.method == 'POST':
        review.delete()
        messages.success(request, "Sharh o'chirildi")
    return redirect('dashboard:reviews')


# ═══════════════════════════════════════════════════════════════
#  Hisobotlar
# ═══════════════════════════════════════════════════════════════
def _clamp_days(request):
    try:
        days = int(request.GET.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    return max(7, min(days, 90))


@staff_required
def report_export(request, kind):
    """Hisobotni CSV faylida beradi.

    Panel raqamlarni ekranda ko'rsatadi, buxgalteriya esa ular bilan
    ishlaydi — o'z jadvalida guruhlaydi, boshqa manbalar bilan
    solishtiradi. Ekrandan ko'chirib olish xatoga olib keladi.
    """
    from .exports import REPORTS, csv_response

    report = REPORTS.get(kind)
    if report is None:
        messages.error(request, "Bunday hisobot yo'q")
        return redirect('dashboard:reports_revenue')

    days = _clamp_days(request)
    rows = report['rows'](days)
    log_action(request, ActivityLog.Action.OTHER,
               f"Hisobot yuklab olindi — {report['filename']} ({days} kun)",
               detail=f'{len(rows)} ta qator')
    return csv_response(f"{report['filename']}-{days}kun", report['header'], rows)


@staff_required
def reports_revenue(request):
    days = _clamp_days(request)
    points, total = _revenue_chart(days)

    per_station = (
        ChargingSession.objects
        .exclude(status=ChargingSession.Status.CHARGING)
        .values('station__name')
        .annotate(revenue=Sum('final_cost'), count=Count('id'))
        .order_by('-revenue')[:10]
    )
    peak = max((r['revenue'] or 0) for r in per_station) if per_station else 0
    station_rows = [
        {
            'name': r['station__name'],
            'revenue': r['revenue'] or 0,
            'count': r['count'],
            'width': _percent(r['revenue'] or 0, peak),
        }
        for r in per_station
    ]

    topups = Transaction.objects.filter(type=Transaction.Type.TOPUP).aggregate(t=Sum('amount'))['t'] or 0
    return render(request, 'dashboard/reports_revenue.html', {
        'points': points,
        'total': total,
        'days': days,
        'station_rows': station_rows,
        'topups_total': topups,
        'avg_per_day': round(total / days) if days else 0,
    })


@staff_required
def reports_usage(request):
    days = _clamp_days(request)
    start = timezone.localdate() - timedelta(days=days - 1)

    sessions = ChargingSession.objects.filter(started_at__date__gte=start)
    finished = sessions.exclude(status=ChargingSession.Status.CHARGING)

    by_day = {
        r['day']: r['c']
        for r in sessions.annotate(day=TruncDate('started_at')).values('day').annotate(c=Count('id'))
    }
    points = []
    for i in range(days):
        day = start + timedelta(days=i)
        points.append({'label': day.strftime('%d.%m'), 'value': by_day.get(day, 0)})
    peak = max((p['value'] for p in points), default=0)
    for p in points:
        p['height'] = _percent(p['value'], peak)

    # Soatlar bo'yicha yuklama — tarmoqning eng band vaqtini ko'rsatadi
    hour_counts = [0] * 24
    for started in sessions.values_list('started_at', flat=True):
        hour_counts[timezone.localtime(started).hour] += 1
    hour_peak = max(hour_counts) if hour_counts else 0
    hours = [
        {'hour': h, 'value': c, 'height': _percent(c, hour_peak)}
        for h, c in enumerate(hour_counts)
    ]

    finished_count = finished.count()
    total_kwh = sum(s.kwh_charged for s in finished)
    return render(request, 'dashboard/reports_usage.html', {
        'points': points,
        'hours': hours,
        'days': days,
        'total_sessions': sessions.count(),
        'finished_sessions': finished_count,
        'total_kwh': round(total_kwh, 1),
        'avg_kwh': round(total_kwh / finished_count, 1) if finished_count else 0,
        'top_stations': sessions.values('station__name').annotate(c=Count('id')).order_by('-c')[:10],
    })


# ═══════════════════════════════════════════════════════════════
#  Stansiyalar salomatligi (OCPP holati)
# ═══════════════════════════════════════════════════════════════
@staff_required
def stations_health(request):
    """Qurilmalar sahifasi ikki qatlamli: yuqorida stansiyalar (OCPP aloqasi),
    pastda har bir ULAGICH alohida qator sifatida — panelda nosozlikni ulagich
    darajasida ko'rish uchun."""
    health_filter = request.GET.get('health', '').strip()

    rows = []
    connector_rows = []
    for station in Station.objects.select_related('partner').prefetch_related('connectors').order_by('name'):
        connectors = list(station.connectors.all())
        faulted = [c for c in connectors if c.status == Connector.Status.OFFLINE]

        if not station.ocpp_id:
            health, label = 'none', 'Charger ulanmagan'
        elif not station.is_online:
            health, label = 'down', "Aloqa yo'q"
        elif faulted:
            health, label = 'warn', f'{len(faulted)} ta ulagich nosoz'
        else:
            health, label = 'ok', 'Onlayn'

        rows.append({
            'station': station,
            'health': health,
            'label': label,
            'connectors': connectors,
            'faulted': faulted,
        })

        for connector in connectors:
            connector_rows.append({
                'station': station,
                'connector': connector,
                'station_online': bool(station.ocpp_id) and station.is_online,
                'parking': connector.parking_mode,
                'parking_minutes': connector.parking_minutes,
            })

    if health_filter in {'ok', 'warn', 'down', 'none'}:
        rows = [r for r in rows if r['health'] == health_filter]

    summary = {
        'online': sum(1 for r in rows if r['health'] == 'ok'),
        'warn': sum(1 for r in rows if r['health'] == 'warn'),
        'down': sum(1 for r in rows if r['health'] == 'down'),
        'none': sum(1 for r in rows if r['health'] == 'none'),
    }
    connector_summary = {
        'total': len(connector_rows),
        'available': sum(1 for c in connector_rows if c['connector'].status == Connector.Status.AVAILABLE),
        'charging': sum(1 for c in connector_rows if c['connector'].status == Connector.Status.CHARGING and not c['parking']),
        'parking': sum(1 for c in connector_rows if c['parking']),
        'offline': sum(1 for c in connector_rows if c['connector'].status == Connector.Status.OFFLINE),
    }
    # Ikki jadval — ikki alohida sahifa kaliti, aks holda biri ikkinchisini surib yuboradi
    return render(request, 'dashboard/stations_health.html', {
        'rows': Paginator(rows, PAGE_SIZE).get_page(request.GET.get('page')),
        'connector_rows': Paginator(connector_rows, PAGE_SIZE).get_page(request.GET.get('cpage')),
        'summary': summary,
        'connector_summary': connector_summary,
        'health_filter': health_filter,
    })


# ═══════════════════════════════════════════════════════════════
#  Aksiyalar
# ═══════════════════════════════════════════════════════════════
@staff_required
def offers_list(request):
    offers = Offer.objects.prefetch_related('stations').all()
    status = request.GET.get('status', '').strip()
    if status == 'running':
        offers = [o for o in offers if o.is_running]
    elif status == 'inactive':
        offers = [o for o in offers if not o.is_running]
    # `is_running` — Python xossasi, shuning uchun ro'yxat filtrlangandan keyin
    # sahifalanadi (QuerySet emas, list — Paginator ikkalasini ham qabul qiladi).
    page_obj = Paginator(offers, PAGE_SIZE).get_page(request.GET.get('page'))

    # Har bir aksiya necha marta ishlatilgani va qancha chegirma bergani.
    # Faqat SHU SAHIFADAGI aksiyalar hisoblanadi — butun jadval bo'ylab
    # yig'ish ro'yxatni sekinlashtirardi.
    for offer in page_obj:
        sessions = ChargingSession.objects.filter(offer=offer)
        offer.used_count = sessions.count()
        offer.saved_total = sum(session.saved_amount for session in sessions[:500])

    return render(request, 'dashboard/offers.html', {
        'page_obj': page_obj, 'status': status,
        # Izohda «belgilangan summa» nimani bildirishini faqat kerak
        # bo'lganda tushuntiramiz
        'fixed_note': any(o.discount_type == Offer.DiscountType.FIXED for o in page_obj),
    })


@staff_required
def offer_form_view(request, pk=None):
    instance = get_object_or_404(Offer, pk=pk) if pk else None
    form = OfferForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        offer = form.save()
        messages.success(request, 'Saqlandi')
        return redirect('dashboard:offer_detail', pk=offer.pk)
    return render(request, 'dashboard/offer_form.html', {'form': form, 'instance': instance})


@staff_required
def offer_detail(request, pk):
    offer = get_object_or_404(Offer.objects.prefetch_related('stations'), pk=pk)
    return render(request, 'dashboard/offer_detail.html', {'offer': offer})


@staff_required
def offer_delete(request, pk):
    offer = get_object_or_404(Offer, pk=pk)
    if request.method == 'POST':
        offer.delete()
        messages.success(request, "O'chirildi")
    return redirect('dashboard:offers')


# ═══════════════════════════════════════════════════════════════
#  Hamkorlar
# ═══════════════════════════════════════════════════════════════
@staff_required
def partners_list(request):
    partners = Partner.objects.prefetch_related('stations').all()
    q = request.GET.get('q', '').strip()
    if q:
        partners = partners.filter(name__icontains=q)
    page_obj = Paginator(partners, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'dashboard/partners.html', {'page_obj': page_obj, 'q': q})


@staff_required
def partner_form_view(request, pk=None):
    instance = get_object_or_404(Partner, pk=pk) if pk else None
    form = PartnerForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        partner = form.save()
        messages.success(request, 'Saqlandi')
        return redirect('dashboard:partner_detail', pk=partner.pk)
    return render(request, 'dashboard/partner_form.html', {'form': form, 'instance': instance})


@staff_required
def partner_detail(request, pk):
    partner = get_object_or_404(Partner, pk=pk)
    stations_page = Paginator(partner.stations.order_by('name'), PAGE_SIZE).get_page(
        request.GET.get('page')
    )
    revenue = (
        ChargingSession.objects
        .filter(station__partner=partner)
        .exclude(status=ChargingSession.Status.CHARGING)
        .aggregate(t=Sum('final_cost'))['t'] or 0
    )
    return render(request, 'dashboard/partner_detail.html', {
        'partner': partner,
        'stations_page': stations_page,
        'revenue': revenue,
        'commission': round(revenue * partner.commission_percent / 100),
        # Biriktirish oynasi uchun — hali egasi yo'q stansiyalar
        'free_stations': Station.objects.filter(partner__isnull=True).order_by('name'),
    })


@staff_required
def partner_delete(request, pk):
    partner = get_object_or_404(Partner, pk=pk)
    if request.method == 'POST':
        partner.delete()
        messages.success(request, "O'chirildi")
    return redirect('dashboard:partners')


# ═══════════════════════════════════════════════════════════════
#  Xodimlar: menejerlar va administratorlar
# ═══════════════════════════════════════════════════════════════
def _staff_queryset(is_admin: bool):
    """Administrator = superuser, menejer = oddiy staff."""
    return User.objects.filter(is_staff=True, is_superuser=is_admin).order_by('username')


@admin_required
def managers_list(request):
    return render(request, 'dashboard/staff_list.html', {
        'page_obj': Paginator(_staff_queryset(is_admin=False), PAGE_SIZE).get_page(request.GET.get('page')),
        'is_admin_section': False,
        'title': 'Menejerlar',
        'subtitle': "Panelga kirish huquqiga ega xodimlar",
        'create_url': 'dashboard:manager_create',
        'detail_url': 'dashboard:manager_detail',
    })


@admin_required
def admins_list(request):
    return render(request, 'dashboard/staff_list.html', {
        'page_obj': Paginator(_staff_queryset(is_admin=True), PAGE_SIZE).get_page(request.GET.get('page')),
        'is_admin_section': True,
        'title': 'Administratorlar',
        'subtitle': 'Tizimning barcha huquqlariga ega foydalanuvchilar',
        'create_url': 'dashboard:admin_create',
        'detail_url': 'dashboard:admin_detail',
    })


def _staff_form_view(request, pk, is_admin):
    instance = get_object_or_404(User, pk=pk, is_staff=True) if pk else None
    form = StaffUserForm(request.POST or None, instance=instance, is_admin=is_admin)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        messages.success(request, 'Saqlandi')
        target = 'dashboard:admin_detail' if is_admin else 'dashboard:manager_detail'
        return redirect(target, pk=user.pk)
    return render(request, 'dashboard/staff_form.html', {
        'form': form,
        'instance': instance,
        'is_admin_section': is_admin,
        'title': 'Administrator' if is_admin else 'Menejer',
    })


@admin_required
def manager_form_view(request, pk=None):
    return _staff_form_view(request, pk, is_admin=False)


@admin_required
def admin_form_view(request, pk=None):
    return _staff_form_view(request, pk, is_admin=True)


@admin_required
def staff_detail(request, pk):
    member = get_object_or_404(User.objects.prefetch_related('groups'), pk=pk, is_staff=True)
    return render(request, 'dashboard/staff_detail.html', {
        'member': member,
        'is_admin_section': member.is_superuser,
        'edit_url': 'dashboard:admin_edit' if member.is_superuser else 'dashboard:manager_edit',
    })


@staff_required
def staff_delete(request, pk):
    member = get_object_or_404(User, pk=pk, is_staff=True)
    is_admin = member.is_superuser
    if request.method == 'POST':
        if member == request.user:
            messages.error(request, "O'zingizni o'chira olmaysiz")
        else:
            member.delete()
            messages.success(request, "O'chirildi")
    return redirect('dashboard:admins' if is_admin else 'dashboard:managers')


# ═══════════════════════════════════════════════════════════════
#  Rollar va huquqlar
# ═══════════════════════════════════════════════════════════════
@admin_required
def roles_list(request):
    roles = Group.objects.prefetch_related('permissions', 'user_set').order_by('name')
    return render(request, 'dashboard/roles.html', {
        'page_obj': Paginator(roles, PAGE_SIZE).get_page(request.GET.get('page')),
    })


@admin_required
def role_form_view(request, pk=None):
    instance = get_object_or_404(Group, pk=pk) if pk else None
    form = RoleForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Saqlandi')
        return redirect('dashboard:roles')
    return render(request, 'dashboard/role_form.html', {'form': form, 'instance': instance})


@admin_required
def role_delete(request, pk):
    role = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        role.delete()
        messages.success(request, "O'chirildi")
    return redirect('dashboard:roles')


# ═══════════════════════════════════════════════════════════════
#  Kontent: bannerlar, FAQ, huquqiy sahifalar
# ═══════════════════════════════════════════════════════════════
@staff_required
def content_banners(request):
    return render(request, 'dashboard/content_banners.html', {
        'page_obj': Paginator(Banner.objects.all(), PAGE_SIZE).get_page(request.GET.get('page')),
    })


@staff_required
def banner_form_view(request, pk=None):
    instance = get_object_or_404(Banner, pk=pk) if pk else None
    form = BannerForm(request.POST or None, request.FILES or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Saqlandi')
        return redirect('dashboard:content_banners')
    return render(request, 'dashboard/banner_form.html', {'form': form, 'instance': instance})


@staff_required
def banner_delete(request, pk):
    banner = get_object_or_404(Banner, pk=pk)
    if request.method == 'POST':
        banner.delete()
        messages.success(request, "O'chirildi")
    return redirect('dashboard:content_banners')


@staff_required
def content_faq(request):
    category = request.GET.get('category', '').strip()
    items = FaqItem.objects.all()
    if category:
        items = items.filter(category=category)
    return render(request, 'dashboard/content_faq.html', {
        'page_obj': Paginator(items, PAGE_SIZE).get_page(request.GET.get('page')),
        'category': category,
        'categories': FaqItem.Category.choices,
    })


@staff_required
def faq_form_view(request, pk=None):
    instance = get_object_or_404(FaqItem, pk=pk) if pk else None
    form = FaqItemForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Saqlandi')
        return redirect('dashboard:content_faq')
    return render(request, 'dashboard/faq_form.html', {'form': form, 'instance': instance})


@staff_required
def faq_delete(request, pk):
    item = get_object_or_404(FaqItem, pk=pk)
    if request.method == 'POST':
        item.delete()
        messages.success(request, "O'chirildi")
    return redirect('dashboard:content_faq')


@staff_required
def content_pages(request):
    # Har sahifa mavjud bo'lishi kerak — yo'q bo'lsa bo'sh holda yaratiladi
    for slug, title in LegalPage.Slug.choices:
        LegalPage.objects.get_or_create(slug=slug, defaults={'title': title})
    return render(request, 'dashboard/content_pages.html', {'pages': LegalPage.objects.all()})


@staff_required
def page_form_view(request, slug):
    page = get_object_or_404(LegalPage, slug=slug)
    form = LegalPageForm(request.POST or None, instance=page)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Saqlandi')
        return redirect('dashboard:content_pages')
    return render(request, 'dashboard/page_form.html', {'form': form, 'page': page})


# ═══════════════════════════════════════════════════════════════
#  Hamkorlar bilan hisob-kitob
# ═══════════════════════════════════════════════════════════════
@admin_required
def payouts(request):
    """Oylik hisob-kitob: qaysi hamkorga qancha o'tkazish kerak.

    Stansiya hamkorga tegishli, tushum esa bizga keladi — oy oxirida
    uning ulushini o'tkazish kerak. Ilgari bu hisob umuman yo'q edi:
    komissiya foizi saqlanardi, lekin u bilan hech narsa qilinmasdi.
    """
    from dashboard.payouts import build_period, month_range

    today = timezone.localdate()
    try:
        year = int(request.GET.get('year') or today.year)
        month = int(request.GET.get('month') or today.month)
    except ValueError:
        year, month = today.year, today.month
    if not 1 <= month <= 12:
        year, month = today.year, today.month

    rows = build_period(year, month)
    start, end = month_range(year, month)

    return render(request, 'dashboard/payouts.html', {
        'rows': rows,
        'year': year,
        'month': month,
        'period': f'{start:%d.%m.%Y} — {end:%d.%m.%Y}',
        'months': _recent_periods(),
        'totals': {
            'gross': sum(r['gross'] for r in rows),
            'commission': sum(r['commission'] for r in rows),
            'amount': sum(r['amount'] for r in rows),
            'unpaid': sum(r['amount'] for r in rows
                          if r['payout'] is None or not r['payout'].is_paid),
        },
    })


def _recent_periods(count=6):
    """Oxirgi oylar — buxgalteriya odatda o'tgan oyni so'raydi."""
    from dashboard.acts import month_label

    today = timezone.localdate()
    year, month = today.year, today.month
    rows = []
    for _ in range(count):
        rows.append({'year': year, 'month': month, 'label': month_label(year, month)})
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return rows


@admin_required
def payout_freeze(request, pk, year, month):
    """Hisobni muzlatadi — shundan keyin foiz o'zgarsa ham davr o'zgarmaydi."""
    from dashboard.payouts import freeze

    partner = get_object_or_404(Partner, pk=pk)
    if request.method != 'POST':
        return redirect('dashboard:payouts')

    record, created = freeze(partner, year, month, user=request.user)
    if created:
        log_action(request, ActivityLog.Action.OTHER,
                   f'{partner.name} — {year}.{month:02d} hisobi tayyorlandi',
                   detail=f"hamkorga {record.amount} so'm")
        messages.success(request, f'{partner.name}: hisob tayyorlandi')
    else:
        messages.error(request, 'Bu davr uchun hisob allaqachon bor')
    return redirect(f'{reverse("dashboard:payouts")}?year={year}&month={month}')


@admin_required
def payout_paid(request, pk):
    """To'lov qilinganini qayd etadi."""
    from management.models import PartnerPayout

    record = get_object_or_404(PartnerPayout.objects.select_related('partner'), pk=pk)
    if request.method != 'POST':
        return redirect('dashboard:payouts')

    if record.is_paid:
        messages.error(request, 'Bu hisob allaqachon to‘langan')
    else:
        record.status = PartnerPayout.Status.PAID
        record.paid_at = timezone.now()
        record.payment_ref = (request.POST.get('payment_ref') or '').strip()[:50]
        record.save(update_fields=['status', 'paid_at', 'payment_ref'])

        log_action(request, ActivityLog.Action.WALLET,
                   f"{record.partner.name} — {record.amount} so'm to'landi",
                   detail=f"t/t №{record.payment_ref or '—'}")
        messages.success(request, f"{record.partner.name}: to'langan deb belgilandi")

    return redirect(f'{reverse("dashboard:payouts")}'
                    f'?year={record.year}&month={record.month}')


@admin_required
def payouts_export(request):
    """Davr hisobini CSV faylida beradi — buxgalteriya u bilan ishlaydi."""
    from dashboard.exports import csv_response
    from dashboard.payouts import build_period

    today = timezone.localdate()
    year = int(request.GET.get('year') or today.year)
    month = int(request.GET.get('month') or today.month)

    rows = [
        [r['partner'].name, r['sessions'], r['kwh'], r['gross'],
         r['commission_percent'], r['commission'], r['amount'],
         'to‘langan' if r['payout'] and r['payout'].is_paid else 'to‘lanmagan']
        for r in build_period(year, month)
    ]
    return csv_response(
        f'hamkorlar-{year}-{month:02d}',
        ['Hamkor', 'Sessiyalar', 'Energiya (kVt·s)', "Umumiy tushum (so'm)",
         'Komissiya (%)', "Bizning ulush (so'm)", "Hamkorga (so'm)", 'Holat'],
        rows,
    )


# ═══════════════════════════════════════════════════════════════
#  Amallar jurnali
# ═══════════════════════════════════════════════════════════════
@staff_required
def activity_log(request):
    """Panelda bajarilgan amallar.

    Tizimda pul harakati ko'p — onlayn to'lov, qaytarish, korporativ
    hisoblar. Nizo chiqqanda «kim va qachon qildi?» degan savolga javob
    bo'lishi kerak.

    Sozlama o'zgarishlari bu yerda emas: ular maydon darajasida
    «eski → yangi» bilan saqlanadi va o'z sahifasida ko'rinadi
    (Sozlamalar > tab ostidagi jadval).
    """
    rows = ActivityLog.objects.select_related('actor')

    action = request.GET.get('action', '').strip()
    if action in dict(ActivityLog.Action.choices):
        rows = rows.filter(action=action)

    query = request.GET.get('q', '').strip()
    if query:
        rows = rows.filter(
            Q(title__icontains=query)
            | Q(detail__icontains=query)
            | Q(actor__username__icontains=query))

    actor = request.GET.get('actor', '').strip()
    if actor.isdigit():
        rows = rows.filter(actor_id=int(actor))

    start = parse_date(request.GET.get('from', ''))
    end = parse_date(request.GET.get('to', ''))
    if start:
        rows = rows.filter(created_at__date__gte=start)
    if end:
        rows = rows.filter(created_at__date__lte=end)

    advanced = sum(1 for key in ('actor', 'from', 'to') if request.GET.get(key))

    return render(request, 'dashboard/activity.html', {
        'page_obj': Paginator(rows, PAGE_SIZE).get_page(request.GET.get('page')),
        'actions': ActivityLog.Action.choices,
        'action': action,
        'q': query,
        'filters': {'actor': actor, 'from': request.GET.get('from', ''),
                    'to': request.GET.get('to', '')},
        'found': rows.count(),
        'advanced_count': advanced,
        # Faqat amal qilgan xodimlar — ro'yxat qisqa bo'lsin
        'staff': User.objects.filter(is_staff=True).order_by('username'),
        'today_count': ActivityLog.objects.filter(
            created_at__date=timezone.localdate()).count(),
    })


# ═══════════════════════════════════════════════════════════════
#  Tizim sozlamalari
#
#  Har tab BO'LIMlardan iborat, har bo'lim alohida saqlanadi. Ilgari
#  bitta katta forma edi: tasodifiy o'zgargan maydon ham birga yozilib
#  ketardi va nima o'zgargani bilinmasdi.
#
#  Har o'zgarish jurnalga tushadi (`SettingsChange`) — narx yoki qat'iy
#  rejim butun tizimga ta'sir qiladi, muammo chiqqanda «kim o'zgartirdi?»
#  degan savolga javob bo'lishi kerak.
# ═══════════════════════════════════════════════════════════════
SETTINGS_TABS = [
    ('general', 'Umumiy', [
        ('app', 'Ilova', SettingsGeneralForm),
        ('mode', 'Rejim', SettingsModeForm),
    ]),
    ('org', 'Tashkilot', [
        ('org', 'Rekvizitlar', SettingsOrgForm),
    ]),
    ('payment', "To'lov", [
        ('price', 'Tariflar', SettingsPriceForm),
        ('topup', "To'ldirish", SettingsTopupForm),
    ]),
    ('providers', "To'lov tizimlari", []),
    ('session', 'Sessiya', [
        ('session', 'Sessiya va ish vaqti', SettingsSessionForm),
    ]),
    ('notification', 'Bildirishnoma', [
        ('notification', 'Bildirishnomalar', SettingsNotificationForm),
    ]),
    ('security', 'Xavfsizlik', [
        ('rfid', 'RFID kartalar', SettingsRfidForm),
        ('access', 'Kirish', SettingsAccessForm),
    ]),
    ('contract', 'Shartnoma', [
        ('contract', 'Shablon', SettingsContractForm),
    ]),
    ('holiday', 'Bayramlar', [
        ('holiday', 'Kalendar', SettingsHolidayForm),
    ]),
]

TAB_SECTIONS = {tab: dict((name, form) for name, _, form in sections)
                for tab, _, sections in SETTINGS_TABS}

# Butun tizimga ta'sir qiladigan sozlamalar: yoqishdan oldin nima
# o'zgarishini ko'rsatib, tasdiq so'raladi
DANGEROUS = {'maintenance_mode', 'require_known_rfid', 'require_ocpp_auth',
             'require_2fa_for_admins'}


def _display(form, field, value):
    """Jurnal uchun qiymatning o'qiladigan ko'rinishi."""
    if isinstance(value, bool):
        return 'yoqilgan' if value else "o'chirilgan"
    if value in (None, ''):
        return '—'
    getter = getattr(form.instance, f'get_{field}_display', None)
    return str(getter() if getter else value)[:255]


def _log_changes(form, section, user):
    """O'zgargan maydonlarni jurnalga yozadi va sonini qaytaradi."""
    written = 0
    for field in form.changed_data:
        if field not in form.fields:
            continue
        SettingsChange.objects.create(
            section=section,
            field=field,
            label=str(form.fields[field].label or field),
            old_value=_display(form, field, form.initial.get(field)),
            new_value=_display(form, field, form.cleaned_data.get(field)),
            changed_by=user if user and user.is_authenticated else None,
        )
        written += 1
    return written


def _settings_context(request, tab, forms_map=None):
    settings_obj = SiteSettings.load()
    forms_map = forms_map or {}

    section_forms = []
    for tab_slug, _label, section_list in SETTINGS_TABS:
        if tab_slug != tab:
            continue
        for name, label, form_class in section_list:
            section_forms.append({
                'name': name,
                'label': label,
                'form': forms_map.get(name) or form_class(instance=settings_obj),
            })

    context = {
        'tabs': [(slug, label) for slug, label, _ in SETTINGS_TABS],
        'active_tab': tab,
        'settings_obj': settings_obj,
        'section_forms': section_forms,
        'dangerous': DANGEROUS,
        # Oxirgi o'zgarishlar — har tabda ko'rinadi, chunki savol doim
        # bitta: "buni kim o'zgartirdi?"
        'changes': SettingsChange.objects.select_related('changed_by')[:10],
    }

    if tab == 'contract':
        # Bo'limlar bo'sh bo'lsa standart matn yaratiladi — operator toza
        # sahifa emas, tayyor shablonni ko'radi va uni tahrirlaydi
        ContractSection.ensure_defaults()
        context['sections'] = _numbered_sections()
        context['placeholders'] = CONTRACT_PLACEHOLDERS
        context['companies_count'] = Company.objects.count()

    if tab == 'holiday':
        context['holidays'] = Holiday.objects.filter(
            date__gte=timezone.localdate().replace(month=1, day=1))
        context['holiday_count'] = Holiday.objects.count()

    if tab == 'providers':
        from wallet.models import PaymentOrder

        context['providers'] = PaymentProvider.objects.all()
        context['provider_form'] = PaymentProviderForm()
        # Oxirgi to'lovlar: integratsiya ishlayaptimi yoki yo'qmi degan
        # savolga eng tez javob shu jadvalda
        context['orders'] = (PaymentOrder.objects
                             .select_related('provider', 'user')[:15])
        context['paid_total'] = sum(
            o.amount for o in PaymentOrder.objects.filter(
                state=PaymentOrder.State.PAID))
        context['open_orders'] = PaymentOrder.objects.filter(
            state__in=[PaymentOrder.State.CREATED, PaymentOrder.State.WAITING]).count()

    if tab == 'notification':
        from accounts.models import DeviceToken

        # Yetkazish holati: xabar bazada bo'lishi uni foydalanuvchi KO'RDI
        # degani emas. Ro'yxatdan o'tgan qurilma yo'q bo'lsa push umuman
        # ketmaydi — buni operator bilishi kerak.
        context['push_devices'] = DeviceToken.objects.filter(is_active=True).count()
        context['push_pending'] = UserNotification.objects.filter(
            pushed_at__isnull=True, push_attempts__lt=3).count()
        context['push_failed'] = UserNotification.objects.filter(
            pushed_at__isnull=True, push_attempts__gte=3).count()
        context['push_sent'] = UserNotification.objects.filter(
            pushed_at__isnull=False).count()
        # Shablonlar bo'sh bo'lsa standart matn yaratiladi — operator toza
        # sahifa emas, tayyor matnni ko'radi va uni tahrirlaydi
        NotificationTemplate.ensure_defaults()
        context['templates'] = NotificationTemplate.objects.all()
        context['unread_total'] = UserNotification.objects.filter(
            read_at__isnull=True).count()

    if tab == 'payment':
        # Narx nechta stansiyaga ta'sir qilishini ko'rsatamiz — operator
        # o'zgartirishdan oldin ko'lamini bilib tursin
        context['stations_on_standard'] = Station.objects.filter(
            discount_price_per_kwh__isnull=True
        ).count()
        context['stations_with_own_price'] = Station.objects.filter(
            discount_price_per_kwh__isnull=False
        ).count()

        # Vaqtga bog'liq tariflar shu tabda — narx bilan bog'liq hamma
        # narsa bir joyda turgani operator uchun qulay
        context['tariffs'] = TariffWindow.objects.select_related('station')
        context['tariff_form'] = TariffWindowForm()
        # Modal ichidagi stansiya ro'yxati uchun — forma maydonidan emas,
        # to'g'ridan-to'g'ri, chunki oyna oddiy inputlardan yig'ilgan
        context['all_stations'] = Station.objects.only('id', 'name')
        context['tariff_now'] = _tariff_now()

    if tab == 'security':
        # Qat'iy rejim yoqilsa nechta karta ishlamay qolishini ko'rsatamiz
        context['unknown_cards'] = RfidCard.objects.exclude(
            status=RfidCard.Status.ACTIVE).count()

        # Kirish urinishlari. Ilgari hujumni payqashning iloji yo'q edi:
        # muvaffaqiyatsiz urinish hech qayerga yozilmasdi.
        from management.login_guard import LoginAttempt, uses_default_password

        day_ago = timezone.now() - timedelta(hours=24)
        context['login_attempts'] = (LoginAttempt.objects.all()[:20])
        context['failed_today'] = LoginAttempt.objects.filter(
            successful=False, created_at__gte=day_ago).count()
        context['default_password_users'] = uses_default_password()

        # SMS balansi: mablag' tugasa xabar jimgina ketmay qo'yadi va
        # buni faqat foydalanuvchi kira olmaganda bilib qolardik.
        # Xizmat javob bermasa `None` — sahifa baribir ochiladi.
        from management import sms

        context['sms_balance'] = (sms.balance()
                                  if sms.is_configured(settings_obj) else None)

    if tab == 'general':
        context['app_users'] = User.objects.filter(is_staff=False).count()

    return context


def _settings_view(request, tab):
    if request.method != 'POST':
        return render(request, 'dashboard/settings.html',
                      _settings_context(request, tab))

    section = request.POST.get('section', '')
    form_class = TAB_SECTIONS.get(tab, {}).get(section)
    if form_class is None:
        return redirect(f'dashboard:settings_{tab}')

    settings_obj = SiteSettings.load()
    form = form_class(request.POST, instance=settings_obj)
    if not form.is_valid():
        # Xato bo'lgan bo'lim formasi qiymatlari bilan qaytariladi,
        # qolgan bo'limlarga tegilmaydi
        return render(request, 'dashboard/settings.html',
                      _settings_context(request, tab, {section: form}))

    changed = _log_changes(form, section, request.user)
    form.save()
    messages.success(
        request,
        f'Saqlandi — {changed} ta o\'zgarish' if changed else "O'zgarish yo'q")
    return redirect(f'dashboard:settings_{tab}')


@admin_required
def settings_general(request):
    return _settings_view(request, 'general')


@admin_required
def settings_org(request):
    return _settings_view(request, 'org')


@admin_required
def settings_session(request):
    return _settings_view(request, 'session')


@admin_required
def settings_providers(request):
    return _settings_view(request, 'providers')


@admin_required
def settings_payment(request):
    return _settings_view(request, 'payment')


@admin_required
def settings_notification(request):
    return _settings_view(request, 'notification')


@admin_required
def settings_security(request):
    return _settings_view(request, 'security')


@admin_required
def settings_contract(request):
    return _settings_view(request, 'contract')


# ── Shartnoma bo'limlari (shartlar) ─────────────────────────────
def _contract_back():
    return redirect('dashboard:settings_contract')


def _numbered_sections():
    """Bo'limlar ro'yxati, har biriga hujjatdagi raqami qo'shilgan.

    Raqam faqat FAOL bo'limlar orasida hisoblanadi — o'chirilgan bo'lim
    hujjatga tushmaydi, demak raqam ham egallamaydi.
    """
    sections = list(ContractSection.objects.all())
    number = 0
    for section in sections:
        if section.is_active:
            number += 1
            section.active_number = number
    return sections


@admin_required
def contract_section_form_view(request, pk=None):
    """Bo'lim qo'shish yoki tahrirlash (sozlamalar sahifasidagi modal orqali)."""
    section = get_object_or_404(ContractSection, pk=pk) if pk else None
    if request.method != 'POST':
        return _contract_back()

    form = ContractSectionForm(request.POST, instance=section)
    if not form.is_valid():
        # Modal sahifaning bir qismi — xatoni forma ostida emas, xabar
        # satrida ko'rsatamiz, shunda operator uni darrov ko'radi
        for errors in form.errors.values():
            messages.error(request, errors[0])
        return _contract_back()

    obj = form.save(commit=False)
    if section is None:
        # Yangi bo'lim oxiriga qo'shiladi
        last = ContractSection.objects.order_by('-order').first()
        obj.order = (last.order if last else 0) + 1
    obj.save()
    messages.success(request, "Bo'lim saqlandi")
    return _contract_back()


@admin_required
def contract_section_delete(request, pk):
    section = get_object_or_404(ContractSection, pk=pk)
    if request.method == 'POST':
        section.delete()
        messages.success(request, "Bo'lim o'chirildi")
    return _contract_back()


@admin_required
def contract_section_move(request, pk):
    """Bo'limni bir pog'ona yuqoriga yoki pastga suradi.

    Raqamlash tartibdan hisoblangani uchun o'rin almashtirish shartnomadagi
    bo'lim raqamlarini ham darhol o'zgartiradi.
    """
    section = get_object_or_404(ContractSection, pk=pk)
    if request.method != 'POST':
        return _contract_back()

    up = request.POST.get('direction') == 'up'
    neighbours = ContractSection.objects.exclude(pk=section.pk)
    neighbour = (
        neighbours.filter(order__lte=section.order).order_by('-order', '-id').first() if up
        else neighbours.filter(order__gte=section.order).order_by('order', 'id').first()
    )
    if neighbour is not None:
        # Tartib raqamlari teng bo'lib qolishi mumkin (import yoki qo'lda
        # tahrirlashdan keyin) — shuning uchun shunchaki almashtirmaymiz
        section.order, neighbour.order = neighbour.order, section.order
        if section.order == neighbour.order:
            section.order += -1 if up else 1
        section.save(update_fields=['order'])
        neighbour.save(update_fields=['order'])
    return _contract_back()


# ── Bildirishnoma shablonlari ───────────────────────────────────
@admin_required
def notification_template_edit(request, pk):
    """Bildirishnoma matnini saqlaydi.

    Hodisa o'zgartirilmaydi — u kodga bog'langan; faqat sarlavha, matn va
    yuborilishi tahrirlanadi.
    """
    template = get_object_or_404(NotificationTemplate, pk=pk)
    if request.method != 'POST':
        return redirect('dashboard:settings_notification')

    form = NotificationTemplateForm(request.POST, instance=template)
    if not form.is_valid():
        for field, errors in form.errors.items():
            label = form.fields[field].label if field in form.fields else ''
            messages.error(request, f'{label}: {errors[0]}' if label else errors[0])
        return redirect('dashboard:settings_notification')

    changed = _log_changes(form, f'notification:{template.event}', request.user)
    form.save()
    messages.success(
        request,
        f'{template.get_event_display()} — saqlandi' if changed else "O'zgarish yo'q")
    return redirect('dashboard:settings_notification')


@admin_required
def notification_templates_reset(request):
    """Barcha matnlarni standart holatiga qaytaradi."""
    if request.method == 'POST':
        NotificationTemplate.objects.all().delete()
        NotificationTemplate.ensure_defaults()
        messages.success(request, 'Standart matnlar tiklandi')
    return redirect('dashboard:settings_notification')


# ── To'lov tizimlari ────────────────────────────────────────────
@admin_required
def provider_form_view(request, pk=None):
    """To'lov tashkilotini qo'shish yoki tahrirlash.

    Ro'yxat bazada: yangi to'lov tizimi qo'shilganda kodni o'zgartirish va
    deploy qilish kerak bo'lmasin.
    """
    provider = get_object_or_404(PaymentProvider, pk=pk) if pk else None
    if request.method != 'POST':
        return redirect('dashboard:settings_providers')

    form = PaymentProviderForm(request.POST, instance=provider)
    if not form.is_valid():
        for field, errors in form.errors.items():
            label = form.fields[field].label if field in form.fields else ''
            messages.error(request, f'{label}: {errors[0]}' if label else errors[0])
        return redirect('dashboard:settings_providers')

    obj = form.save(commit=False)
    if provider is None:
        last = PaymentProvider.objects.order_by('-order').first()
        obj.order = (last.order if last else 0) + 1
    obj.save()

    SettingsChange.objects.create(
        section='providers', field=obj.code,
        label=f"To'lov tizimi — {obj.name}",
        old_value='—' if provider is None else 'tahrirlandi',
        new_value="qo'shildi" if provider is None else 'saqlandi',
        changed_by=request.user,
    )
    messages.success(request, f'{obj.name} saqlandi')
    return redirect('dashboard:settings_providers')


@admin_required
def provider_toggle(request, pk):
    """Tashkilotni yoqadi/o'chiradi. O'chirilgani mobil ilovada ko'rinmaydi."""
    provider = get_object_or_404(PaymentProvider, pk=pk)
    if request.method == 'POST':
        provider.is_active = not provider.is_active
        provider.save(update_fields=['is_active'])
        SettingsChange.objects.create(
            section='providers', field=provider.code,
            label=f"To'lov tizimi — {provider.name}",
            old_value="o'chirilgan" if provider.is_active else 'yoqilgan',
            new_value='yoqilgan' if provider.is_active else "o'chirilgan",
            changed_by=request.user,
        )
        messages.success(
            request,
            f"{provider.name} "
            f"{'yoqildi' if provider.is_active else 'o‘chirildi'}")
    return redirect('dashboard:settings_providers')


@admin_required
def provider_delete(request, pk):
    provider = get_object_or_404(PaymentProvider, pk=pk)
    if request.method == 'POST':
        name = provider.name
        provider.delete()
        SettingsChange.objects.create(
            section='providers', field='-', label=f"To'lov tizimi — {name}",
            old_value='mavjud', new_value="o'chirildi", changed_by=request.user,
        )
        messages.success(request, f"{name} o'chirildi")
    return redirect('dashboard:settings_providers')


# ── Sozlamalar bo'yicha qidiruv ─────────────────────────────────
@admin_required
def settings_search(request):
    """Sozlama nomi bo'yicha qidiradi va qaysi tabda ekanini ko'rsatadi.

    Sozlamalar soni oshgani sari kerakligini topish qiyinlashadi: operator
    to'qqizta tabni birma-bir ochib chiqishga majbur bo'lardi.
    """
    query = request.GET.get('q', '').strip().lower()
    results = []
    if query:
        settings_obj = SiteSettings.load()
        for tab, tab_label, sections in SETTINGS_TABS:
            for name, section_label, form_class in sections:
                form = form_class(instance=settings_obj)
                for field_name, field in form.fields.items():
                    haystack = ' '.join([
                        str(field.label or ''), str(field.help_text or ''), field_name,
                    ]).lower()
                    if query in haystack:
                        results.append({
                            'label': field.label or field_name,
                            'help': field.help_text,
                            'tab': tab,
                            'tab_label': tab_label,
                            'section': section_label,
                        })

    return render(request, 'dashboard/_settings_search.html', {
        'q': request.GET.get('q', '').strip(),
        'results': results[:20],
        'total': len(results),
    })


# ── Bayram kunlari ──────────────────────────────────────────────
def _holiday_back():
    return redirect('dashboard:settings_holiday')


@admin_required
def settings_holiday(request):
    return _settings_view(request, 'holiday')


@admin_required
def holidays_sync(request):
    """Bayramlarni Google Calendar'dan yangilaydi.

    Tarmoq xatosi kutilgan hol — internet yoki Google javob bermasligi
    mumkin. Bunda sahifa buzilmaydi, operator xabarni ko'radi va keyinroq
    qayta uradi yoki kunlarni qo'lda kiritadi.
    """
    if request.method != 'POST':
        return _holiday_back()

    try:
        added, updated, total = sync_holidays()
    except HolidaySyncError as error:
        messages.error(request, str(error))
        return _holiday_back()

    messages.success(
        request,
        f'Kalendar yangilandi: {added} ta yangi, {updated} ta o\'zgargan '
        f'({total} ta kun tekshirildi)',
    )
    return _holiday_back()


@admin_required
def holiday_add(request):
    """Bayram kunini qo'lda qo'shadi (yoki mavjudini yangilaydi)."""
    if request.method != 'POST':
        return _holiday_back()

    day = parse_date(request.POST.get('date') or '')
    name = (request.POST.get('name') or '').strip()[:150]
    if not day or not name:
        messages.error(request, 'Sana va nomni kiriting')
        return _holiday_back()

    Holiday.objects.update_or_create(
        date=day,
        defaults={'name': name, 'source': Holiday.Source.MANUAL, 'synced_at': None},
    )
    messages.success(request, f'{day:%d.%m.%Y} — {name} qo\'shildi')
    return _holiday_back()


@admin_required
def holiday_delete(request, pk):
    holiday = get_object_or_404(Holiday, pk=pk)
    if request.method == 'POST':
        holiday.delete()
        messages.success(request, "Kun ro'yxatdan olib tashlandi")
    return _holiday_back()


@staff_required
def holidays_json(request):
    """Kalendar uchun bayram kunlari: {"2026-01-01": "Yangi yil", ...}.

    Panelning sana tanlagichi shu manzilni bir marta o'qiydi va natijani
    seans davomida eslab qoladi — har bir maydon uchun qayta so'ramaydi.
    """
    rows = Holiday.objects.all()

    # Kalendar odatda bitta yilni ko'rsatadi — keraksiz ma'lumot yubormaymiz
    start = parse_date(request.GET.get('from') or '')
    end = parse_date(request.GET.get('to') or '')
    if start:
        rows = rows.filter(date__gte=start)
    if end:
        rows = rows.filter(date__lte=end)

    return JsonResponse({
        'days': {row.date.isoformat(): row.name for row in rows},
    })


@admin_required
def contract_preview(request):
    """Shablonni namuna ma'lumotlar bilan yuklab beradi.

    Operator matnni o'zgartirgach natijani ko'rish uchun haqiqiy mijoz
    kartochkasiga o'tishi shart emas. Mijoz bo'lmasa namunaviy nom bilan
    yig'iladi — shablonni tizim bo'sh turganda ham tayyorlash mumkin.
    """
    try:
        from .contracts import ContractBuilder, build_company_contract
    except ModuleNotFoundError:
        messages.error(
            request,
            "Word hujjatlari uchun `python-docx` o'rnatilmagan — "
            "`pip install -r requirements.txt` ni bajaring",
        )
        return _contract_back()

    ContractSection.ensure_defaults()
    company = Company.objects.order_by('id').first()
    if company is not None:
        document = build_company_contract(company)
    else:
        sample = Company(
            name='Namuna mijoz', legal_name='«Namuna» MChJ',
            director='Familiya I.O.', legal_address='Toshkent sh.',
        )
        document = ContractBuilder(
            sample, SiteSettings.load(), [],
            ContractSection.objects.filter(is_active=True),
        ).build()

    response = HttpResponse(
        document.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    response['Content-Disposition'] = 'attachment; filename="shartnoma-namuna.docx"'
    return response


@admin_required
def contract_sections_reset(request):
    """Barcha bo'limlarni standart matnga qaytaradi."""
    if request.method == 'POST':
        ContractSection.objects.all().delete()
        ContractSection.ensure_defaults()
        messages.success(request, 'Standart shartnoma matni tiklandi')
    return _contract_back()


# ═══════════════════════════════════════════════════════════════
#  Profil (panelga kirgan xodimning o'zi)
# ═══════════════════════════════════════════════════════════════
@staff_required
def profile(request):
    user = request.user
    if request.method == 'POST':
        user.first_name = request.POST.get('first_name', '').strip()[:150]
        user.last_name = request.POST.get('last_name', '').strip()[:150]
        user.email = request.POST.get('email', '').strip()[:254]
        user.save(update_fields=['first_name', 'last_name', 'email'])

        new_password = request.POST.get('new_password', '')
        if new_password:
            if new_password != request.POST.get('confirm_password', ''):
                messages.error(request, 'Parollar mos kelmadi')
                return redirect('dashboard:profile')
            # Parol qoidalari SHU YERDA ham tekshiriladi. Ilgari
            # tekshirilmasdi: sozlamalarda qoidalar turardi, panelda esa
            # istalgan parol qabul qilinardi — ya'ni qoida faqat qog'ozda
            # bor edi.
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError

            try:
                validate_password(new_password, user=user)
            except ValidationError as error:
                for message in error.messages:
                    messages.error(request, message)
                return redirect('dashboard:profile')

            user.set_password(new_password)
            user.save()
            messages.success(request, "Parol yangilandi — qaytadan kiring")
            return redirect('dashboard:login')

        messages.success(request, 'Profil saqlandi')
        return redirect('dashboard:profile')

    from management.totp import TwoFactor, required_for

    second = TwoFactor.objects.filter(user=user).first()
    return render(request, 'dashboard/profile.html', {
        'member': user,
        'session_count': ChargingSession.objects.count(),
        'two_factor': second,
        'two_factor_required': required_for(user),
    })


# ═══════════════════════════════════════════════════════════════
#  Stansiyani hamkorga biriktirish
# ═══════════════════════════════════════════════════════════════
@staff_required
def station_assign_partner(request, pk):
    """Stansiya detalidagi tezkor biriktirish. Bo'sh qiymat — bog'lanishni uzadi."""
    station = get_object_or_404(Station, pk=pk)
    if request.method == 'POST':
        raw = (request.POST.get('partner') or '').strip()
        if raw:
            station.partner = get_object_or_404(Partner, pk=int(raw))
            messages.success(request, f'{station.name} → {station.partner.name}')
        else:
            station.partner = None
            messages.success(request, "Hamkor bog'lanishi uzildi")
        station.save(update_fields=['partner'])
    return redirect('dashboard:station_detail', pk=pk)


@staff_required
def partner_attach_stations(request, pk):
    """Hamkor sahifasidan bir nechta stansiyani birdaniga biriktirish."""
    partner = get_object_or_404(Partner, pk=pk)
    if request.method == 'POST':
        ids = request.POST.getlist('stations')
        if ids:
            count = Station.objects.filter(id__in=ids).update(partner=partner)
            messages.success(request, f'{count} ta stansiya biriktirildi')
    return redirect('dashboard:partner_detail', pk=pk)


@staff_required
def partner_detach_station(request, pk, station_pk):
    partner = get_object_or_404(Partner, pk=pk)
    if request.method == 'POST':
        Station.objects.filter(pk=station_pk, partner=partner).update(partner=None)
        messages.success(request, 'Stansiya ajratildi')
    return redirect('dashboard:partner_detail', pk=pk)


# ═══════════════════════════════════════════════════════════════
#  Manzilni koordinataga aylantirish (geokodlash)
# ═══════════════════════════════════════════════════════════════
@staff_required
def geocode(request):
    """Manzil matnini koordinataga aylantiradi (OpenStreetMap Nominatim).

    Nega server orqali: Nominatim foydalanish siyosati har bir so'rovda
    o'zini tanishtiruvchi `User-Agent` talab qiladi, brauzer esa bu
    sarlavhani o'rnata olmaydi — shuning uchun to'g'ridan-to'g'ri
    chaqiruvlar rad etilishi mumkin. Bu yerda uni o'zimiz qo'yamiz.
    """
    import json
    import urllib.error
    import urllib.parse
    import urllib.request

    from django.http import JsonResponse

    query = (request.GET.get('q') or '').strip()
    if len(query) < 3:
        return JsonResponse({'error': "Manzil juda qisqa"}, status=400)

    # Mamlakatni cheklaymiz — "Chilonzor 5" kabi qisqa so'rovlar boshqa
    # davlatdagi o'xshash nomga tushib ketmasin.
    params = urllib.parse.urlencode({
        'q': query,
        'format': 'json',
        'limit': 1,
        'countrycodes': 'uz',
        'accept-language': 'uz',
    })
    url = f'https://nominatim.openstreetmap.org/search?{params}'
    headers = {'User-Agent': 'VoltMax-Panel/1.0 (admin panel geocoding)'}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            results = json.loads(response.read().decode('utf-8'))
    except urllib.error.URLError as exc:
        return JsonResponse(
            {'error': f"Qidiruv xizmatiga ulanib bo'lmadi: {exc.reason}"}, status=502
        )
    except (ValueError, TimeoutError):
        return JsonResponse({'error': "Qidiruv xizmati javob bermadi"}, status=502)

    if not results:
        return JsonResponse({'error': 'Manzil topilmadi'}, status=404)

    place = results[0]
    return JsonResponse({
        'lat': float(place['lat']),
        'lng': float(place['lon']),
        'label': place.get('display_name', query),
    })


# ── Vaqtga bog'liq tariflar ─────────────────────────────────────
def _tariff_now():
    """Hozir qaysi stansiyada qaysi tarif amal qilayotgani.

    Operator "tungi tarif yoqilganmi" degan savolga jadvalga qarab javob
    olishi kerak: sozlama saqlangani uning ISHLAYOTGANINI bildirmaydi.
    """
    from stations import pricing

    rows = []
    for station in Station.objects.all()[:200]:
        window = pricing.active_tariff(station)
        if window is not None:
            rows.append((station, window))
    return rows


def _tariff_back():
    return redirect('dashboard:settings_payment')


@admin_required
def tariff_form_view(request, pk=None):
    """Tarif oynasini qo'shish yoki tahrirlash."""
    window = get_object_or_404(TariffWindow, pk=pk) if pk else None
    if request.method != 'POST':
        return _tariff_back()

    form = TariffWindowForm(request.POST, instance=window)
    if not form.is_valid():
        for field, errors in form.errors.items():
            label = form.fields[field].label if field in form.fields else ''
            messages.error(request, f'{label}: {errors[0]}' if label else errors[0])
        return _tariff_back()

    obj = form.save()
    SettingsChange.objects.create(
        section='payment', field=f'tariff:{obj.pk}',
        label=f'Tarif — {obj.name}',
        old_value='—' if window is None else 'tahrirlandi',
        new_value=f"{obj.start_time:%H:%M}–{obj.end_time:%H:%M} · {obj.price_per_kwh}",
        changed_by=request.user,
    )
    # Amallar jurnaliga alohida yozilmaydi: sozlama o'zgarishlari
    # `SettingsChange` da yuritiladi va sozlamalar sahifasida ko'rinadi
    messages.success(request, f'{obj.name} saqlandi')
    return _tariff_back()


@admin_required
def tariff_toggle(request, pk):
    window = get_object_or_404(TariffWindow, pk=pk)
    if request.method == 'POST':
        window.is_active = not window.is_active
        window.save(update_fields=['is_active'])
        SettingsChange.objects.create(
            section='payment', field=f'tariff:{window.pk}',
            label=f'Tarif — {window.name}',
            old_value="o'chirilgan" if window.is_active else 'yoqilgan',
            new_value='yoqilgan' if window.is_active else "o'chirilgan",
            changed_by=request.user,
        )
        messages.success(
            request,
            f"{window.name} {'yoqildi' if window.is_active else 'toxtatildi'}")
    return _tariff_back()


@admin_required
def tariff_delete(request, pk):
    window = get_object_or_404(TariffWindow, pk=pk)
    if request.method == 'POST':
        name = window.name
        window.delete()
        SettingsChange.objects.create(
            section='payment', field='tariff', label=f'Tarif — {name}',
            old_value='mavjud', new_value="o'chirildi", changed_by=request.user,
        )
        messages.success(request, f"{name} o'chirildi")
    return _tariff_back()


# ── Tizim holati ────────────────────────────────────────────────
@staff_required
def system_health(request):
    """Tizimning ko'rinmas yarmi ishlayaptimi.

    Davriy vazifalar, push yetkazish, to'lov tizimlari va OCPP ulanishlari
    so'rovdan tashqarida ishlaydi — panelga qarab ularning holatini bilib
    bo'lmasdi. Servis serverda umuman ishga tushmagan bo'lsa ham panel
    "hammasi joyida" ko'rinishida turaverardi.

    Sahifa menejerga ham ochiq: charger oflayn bo'lgani yoki push
    ketmayotgani kundalik ishga tegishli. Maxfiy kalitlar ko'rsatilmaydi —
    faqat "sozlangan / sozlanmagan".
    """
    from management.health import collect

    return render(request, 'dashboard/system_health.html', collect())


@admin_required
def otp_gateway_test(request):
    """OTP shlyuziga sinov kodi yuboradi.

    Nima uchun kerak: token noto'g'ri yoki hisobda mablag' qolmagan
    bo'lsa, buni FAQAT haqiqiy foydalanuvchi kirmoqchi bo'lganda bilib
    qolinardi — ya'ni eng noqulay paytda. Bu tugma javobni darhol beradi.

    Kod haqiqiy OTP emas: hech qanday hisobga bog'lanmaydi va u bilan
    tizimga kirib bo'lmaydi.
    """
    if request.method != 'POST':
        return redirect('dashboard:settings_security')

    from accounts.telegram_gateway import TelegramGatewayError, send_verification_code
    from dashboard.phones import normalize_phone

    phone = normalize_phone(request.POST.get('phone', ''))
    if len(phone) < 12:
        messages.error(request, "Telefon raqamini to'liq kiriting")
        return redirect('dashboard:settings_security')

    try:
        send_verification_code('+' + phone, '000000')
    except TelegramGatewayError as error:
        messages.error(request, f'Shlyuz javobi: {error}')
    else:
        messages.success(
            request, f'Sinov kodi {phone} raqamiga yuborildi — telefonni tekshiring')
    return redirect('dashboard:settings_security')


# ── Ikki bosqichli kirish ───────────────────────────────────────
@staff_required
def two_factor_setup(request):
    """Ikki bosqichli kirishni yoqish.

    Ikki qadam: kalit yaratiladi va QR ko'rsatiladi, keyin foydalanuvchi
    ilova bergan kodni kiritadi. Tasdiqlanmaguncha talab qilinmaydi —
    aks holda kalit yaratilib, ilovaga qo'shilmagan bo'lsa operator o'z
    panelidan chiqib qolardi.
    """
    from management.totp import TwoFactor, new_secret, provisioning_uri, qr_svg

    second, _ = TwoFactor.objects.get_or_create(
        user=request.user, defaults={'secret': new_secret()})

    if second.is_active:
        messages.info(request, 'Ikki bosqichli kirish allaqachon yoqilgan')
        return redirect('dashboard:profile')

    if request.method == 'POST':
        if second.verify_code(request.POST.get('code', '')):
            second.confirmed_at = timezone.now()
            codes = second.set_backup_codes()
            second.save(update_fields=['confirmed_at', 'backup_hashes'])

            SettingsChange.objects.create(
                section='security', field='2fa',
                label=f'Ikki bosqichli kirish — {request.user.username}',
                old_value="o'chirilgan", new_value='yoqilgan',
                changed_by=request.user,
            )
            # Zaxira kodlari FAQAT SHU PAYT ko'rsatiladi: bazada ularning
            # yig'indisi turadi, ochiq ko'rinishini tiklab bo'lmaydi
            return render(request, 'dashboard/two_factor_done.html',
                          {'codes': codes})

        messages.error(request, "Kod noto'g'ri — ilovadagi joriy kodni kiriting")

    # Kalit har ochilganda YANGILANMAYDI: foydalanuvchi QR ni skanerlab,
    # sahifani yangilagan bo'lsa, eski kalit ilovada qolib ketardi
    uri = provisioning_uri(second.secret, request.user.username)
    return render(request, 'dashboard/two_factor_setup.html', {
        'secret': second.secret,
        'uri': uri,
        'qr': qr_svg(uri),
    })


@staff_required
def two_factor_disable(request):
    """O'chirish — faqat joriy kod bilan.

    Kodsiz o'chirilsa, o'g'irlangan sessiya ikkinchi to'siqni shunchaki
    olib tashlab qo'ya olardi.
    """
    from management.totp import TwoFactor, required_for

    second = TwoFactor.objects.filter(user=request.user).first()
    if request.method != 'POST' or second is None:
        return redirect('dashboard:profile')

    if required_for(request.user):
        messages.error(
            request,
            "Administratorlar uchun ikki bosqichli kirish majburiy "
            "(Sozlamalar > Xavfsizlik)")
        return redirect('dashboard:profile')

    if not second.verify_code(request.POST.get('code', '')):
        messages.error(request, "Kod noto'g'ri — o'chirilmadi")
        return redirect('dashboard:profile')

    second.delete()
    SettingsChange.objects.create(
        section='security', field='2fa',
        label=f'Ikki bosqichli kirish — {request.user.username}',
        old_value='yoqilgan', new_value="o'chirildi",
        changed_by=request.user,
    )
    messages.success(request, "Ikki bosqichli kirish o'chirildi")
    return redirect('dashboard:profile')


@staff_required
def two_factor_backup_codes(request):
    """Zaxira kodlarini yangilaydi. Eskilari darhol yaroqsiz bo'ladi."""
    from management.totp import TwoFactor

    second = TwoFactor.objects.filter(user=request.user).first()
    if request.method != 'POST' or second is None or not second.is_active:
        return redirect('dashboard:profile')

    if not second.verify_code(request.POST.get('code', '')):
        messages.error(request, "Kod noto'g'ri")
        return redirect('dashboard:profile')

    codes = second.set_backup_codes()
    second.save(update_fields=['backup_hashes'])
    return render(request, 'dashboard/two_factor_done.html',
                  {'codes': codes, 'renewed': True})


@admin_required
def sms_test(request):
    """SMS shlyuziga sinov xabari yuboradi.

    Haqiqiy SMS ketadi va hisobdan pul yechiladi — shuning uchun matn
    ham haqiqiy ko'rinishda bo'ladi: sozlama ishlayotganini shu bilan
    ishonch hosil qilinadi.
    """
    if request.method != 'POST':
        return redirect('dashboard:settings_security')

    from dashboard.phones import normalize_phone
    from management import sms

    phone = normalize_phone(request.POST.get('phone', ''))
    if len(phone) < 12:
        messages.error(request, "Telefon raqamini to'liq kiriting")
        return redirect('dashboard:settings_security')

    try:
        sms.send(phone, 'VoltMax: SMS shlyuzi sinovi')
    except sms.SmsError as error:
        messages.error(request, f'SMS xizmati javobi: {error}')
    else:
        messages.success(request, f'Sinov SMS {phone} raqamiga yuborildi')
    return redirect('dashboard:settings_security')
