"""RFID kartalar bo'limi.

Kartalar ikki yo'l bilan paydo bo'ladi: operator qo'lda qo'shadi yoki charger
noma'lum kartani ko'rganda tizim uni "tasdiqlanmagan" holatda o'zi yozib
qo'yadi. Ikkinchisi ataylab shunday: avval qaysi kartalar ishlatilayotganini
ko'rish kerak, keyingina qat'iy rejimni yoqish mumkin — aks holda ishlab
turgan stansiyada hamma kartalar birdaniga ishlamay qolardi.
"""

import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.models import Company, CompanyInvoice, RfidCard
from management.models import SiteSettings
from sessions_app.models import ChargingSession
from ocpp_gateway import commands as ocpp_commands
from stations.models import Station
from wallet.models import Transaction, WalletBalance

from .decorators import staff_required
from .forms import COMPANY_SECTIONS, CompanyForm, RfidCardForm
from .templatetags.money import format_som
from .widgets import strip_separators
from .views import PAGE_SIZE


# Muddatni uzaytirish tanlovlari: (oylar, yozuvi)
EXTEND_OPTIONS = [
    (1, '1 oy'),
    (3, '3 oy'),
    (6, '6 oy'),
    (12, '1 yil'),
]


def _back(request):
    return redirect(request.POST.get('next') or 'dashboard:rfid_cards')


def _card_filters(request):
    """RFID ro'yxatining filtrlari.

    Korporativ mijozlar sahifasidagi tartib: qidiruv va holat tabi ko'rinib
    turadi, qolgan mezonlar «Filtr» oynasida. Ro'yxat va tugmadagi son bir
    xil qoidaga tayanishi uchun hammasi shu yerda o'qiladi.
    """
    get = request.GET
    return {
        'q': get.get('q', '').strip(),
        'status': get.get('status', '').strip(),
        'company': [v for v in get.getlist('company') if v],
        'owner': get.get('owner', '').strip(),        # with | without
        'expiry': get.get('expiry', '').strip(),      # soon | none | set
        'usage': get.get('usage', '').strip(),        # used | unused
        'added_from': get.get('added_from', '').strip(),
        'added_to': get.get('added_to', '').strip(),
        'sort': get.get('sort', '').strip(),
    }


# «Filtr» tugmasidagi son: qidiruv va holat tabi ko'rinib turadi,
# ularni qayta sanash chalkashtirardi
CARD_ADVANCED = ('company', 'owner', 'expiry', 'usage', 'added_from', 'added_to')

CARD_SORTS = {
    'new': '-created_at',
    'used': '-use_count',
    'expiring': 'expires_at',
    'tag': 'id_tag',
}

# Muddati tugashiga shuncha kun qolganda karta "tez orada tugaydi" hisoblanadi
EXPIRING_SOON_DAYS = 30


@staff_required
def rfid_cards(request):
    filters = _card_filters(request)
    cards = RfidCard.objects.select_related('user', 'company', 'first_seen_station')

    now = timezone.now()
    not_expired = Q(expires_at__isnull=True) | Q(expires_at__gt=now)

    status = filters['status']
    if status == 'expired':
        # Muddati tugagan karta bazada "faol" bo'lib turadi, lekin ishlamaydi
        cards = cards.filter(expires_at__lte=now).exclude(status=RfidCard.Status.BLOCKED)
    elif status == RfidCard.Status.ACTIVE:
        cards = cards.filter(Q(status=status) & not_expired)
    elif status in dict(RfidCard.Status.choices):
        cards = cards.filter(status=status)

    if filters['q']:
        # Karta raqami, nomi, egasi yoki korporativ mijoz bo'yicha
        cards = cards.filter(
            Q(id_tag__icontains=filters['q'])
            | Q(label__icontains=filters['q'])
            | Q(user__username__icontains=filters['q'])
            | Q(user__first_name__icontains=filters['q'])
            | Q(company__name__icontains=filters['q'])
        )

    # Korporativ mijoz — bir nechtasini birga tanlash mumkin.
    # `none` alohida qiymat: korporativ mijozga biriktirilmagan kartalar.
    selected_companies = filters['company']
    if selected_companies:
        ids = [int(v) for v in selected_companies if v.isdigit()]
        condition = Q(pk__in=[])          # bo'sh shart, quyida to'ldiriladi
        if ids:
            condition |= Q(company_id__in=ids)
        if 'none' in selected_companies:
            condition |= Q(company__isnull=True)
        cards = cards.filter(condition)

    if filters['owner'] == 'with':
        cards = cards.filter(user__isnull=False)
    elif filters['owner'] == 'without':
        # Egasiz karta — xizmat kartasi (usta, texnik xizmat)
        cards = cards.filter(user__isnull=True)

    if filters['expiry'] == 'soon':
        cards = cards.filter(expires_at__gt=now,
                             expires_at__lte=now + timedelta(days=EXPIRING_SOON_DAYS))
    elif filters['expiry'] == 'none':
        cards = cards.filter(expires_at__isnull=True)
    elif filters['expiry'] == 'set':
        cards = cards.filter(expires_at__isnull=False)

    if filters['usage'] == 'used':
        cards = cards.filter(use_count__gt=0)
    elif filters['usage'] == 'unused':
        # Hech qachon ishlatilmagan karta: berilgan-u, haydovchida qolib ketgan
        cards = cards.filter(use_count=0)

    start = parse_date(filters['added_from'])
    end = parse_date(filters['added_to'])
    if start:
        cards = cards.filter(created_at__date__gte=start)
    if end:
        cards = cards.filter(created_at__date__lte=end)

    cards = cards.order_by(CARD_SORTS.get(filters['sort'], '-created_at'))

    # Hisoblar HAQIQIY holat bo'yicha: muddati tugagan karta "faol" emas
    counts = RfidCard.objects.aggregate(
        active=Count('id', filter=Q(status=RfidCard.Status.ACTIVE) & not_expired),
        pending=Count('id', filter=Q(status=RfidCard.Status.PENDING) & not_expired),
        blocked=Count('id', filter=Q(status=RfidCard.Status.BLOCKED)),
        expired=Count('id', filter=Q(expires_at__lte=now)
                      & ~Q(status=RfidCard.Status.BLOCKED)),
    )

    companies_list = list(Company.objects.order_by('name').values('id', 'name'))

    ocpp_stations = list(
        Station.objects.exclude(ocpp_id__isnull=True).exclude(ocpp_id='').order_by('name')
    )

    return render(request, 'dashboard/rfid_cards.html', {
        'page_obj': Paginator(cards, PAGE_SIZE).get_page(request.GET.get('page')),
        # Qatorli formada holat so'ralmaydi — karta har doim
        # "tasdiqlanmagan" bo'lib qo'shiladi va qo'lda tasdiqlanadi.
        'form': RfidCardForm(compact=True),
        'counts': counts,
        'status': status,
        'q': filters['q'],
        'filters': filters,
        'found': cards.count(),
        'advanced_count': sum(1 for key in CARD_ADVANCED if filters[key]),
        'strict': SiteSettings.load().require_known_rfid,
        'companies': companies_list,
        # Shablonda solishtirish uchun matn ko'rinishida saqlanadi
        'selected_companies': selected_companies,
        # Muddatni uzaytirish tanlovlari — bir joyda turgani ma'qul
        'extend_options': EXTEND_OPTIONS,
        # Ro'yxatni qurilmaga yuklash uchun — faqat OCPP'ga ulanganlar.
        # Bitta ham bo'lmasa tugma ko'rsatilmaydi: bosilganda baribir
        # "yuboradigan qurilma yo'q" degan xato chiqardi.
        'ocpp_stations': ocpp_stations,
        'online_stations': sum(1 for st in ocpp_stations if st.is_online),
    })


@staff_required
def rfid_card_create(request):
    if request.method != 'POST':
        return _back(request)

    # `compact=True` — holat so'ralmaydi, karta model standarti bo'yicha
    # "tasdiqlanmagan" bo'lib yaratiladi va operator uni qo'lda tasdiqlaydi.
    form = RfidCardForm(request.POST, compact=True)
    if form.is_valid():
        card = form.save()
        messages.success(
            request,
            f"{card.id_tag} qo'shildi — tasdiqlanmagan holatda. "
            f'Ishlashi uchun "Tasdiqlash" tugmasini bosing.',
        )
    else:
        for field, errors in form.errors.items():
            label = form.fields[field].label if field in form.fields else ''
            for error in errors:
                messages.error(request, f'{label}: {error}' if label else error)
    return _back(request)


@staff_required
def rfid_card_status(request, pk):
    """Kartani tasdiqlash / bloklash."""
    if request.method != 'POST':
        return _back(request)

    card = get_object_or_404(RfidCard, pk=pk)
    new_status = request.POST.get('status')
    if new_status not in dict(RfidCard.Status.choices):
        messages.error(request, "Noma'lum holat")
        return _back(request)

    card.status = new_status
    card.save(update_fields=['status'])
    messages.success(request, f'{card.id_tag}: {card.get_status_display().lower()}')
    return _back(request)


def _extend_until(card, months):
    """Yangi tugash sanasi.

    Sanoq HOZIRDAN emas, kartaning joriy muddatidan boshlanadi — agar muddat
    hali tugamagan bo'lsa, uzaytirish uni qisqartirib yubormasligi kerak.
    Muddati o'tib ketgan bo'lsa esa hozirdan hisoblanadi.
    """
    from dateutil.relativedelta import relativedelta

    now = timezone.now()
    start = card.expires_at if (card.expires_at and card.expires_at > now) else now
    return start + relativedelta(months=months)


@staff_required
def rfid_card_extend(request, pk):
    """Karta muddatini uzaytiradi yoki butunlay olib tashlaydi."""
    if request.method != 'POST':
        return _back(request)

    card = get_object_or_404(RfidCard, pk=pk)
    raw = request.POST.get('months', '')

    if raw == 'clear':
        card.expires_at = None
        card.save(update_fields=['expires_at'])
        messages.success(request, f'{card.id_tag}: muddat olib tashlandi')
        return _back(request)

    try:
        months = int(raw)
    except ValueError:
        messages.error(request, "Muddat noto'g'ri")
        return _back(request)
    if months not in dict(EXTEND_OPTIONS):
        messages.error(request, "Bunday muddat tanlovi yo'q")
        return _back(request)

    card.expires_at = _extend_until(card, months)
    card.save(update_fields=['expires_at'])
    messages.success(
        request,
        f"{card.id_tag}: muddat {card.expires_at:%d.%m.%Y} gacha uzaytirildi",
    )
    return _back(request)


@staff_required
def rfid_card_delete(request, pk):
    card = get_object_or_404(RfidCard, pk=pk)
    if request.method == 'POST':
        tag = card.id_tag
        card.delete()
        messages.success(request, f"{tag} kartasi o'chirildi")
    return _back(request)


@staff_required
def rfid_push(request):
    """Kartalar ro'yxatini chargerlarga yuklaydi (SendLocalList).

    Nima uchun kerak: internet uzilganda charger serverga Authorize yubora
    olmaydi va o'zidagi ro'yxatga tayanadi. Ro'yxat bo'lmasa yo hech kim
    zaryadlay olmaydi, yo hamma zaryadlay oladi.
    """
    if request.method != 'POST':
        return _back(request)

    cards = [
        {'idTag': c.id_tag, 'status': 'Blocked' if c.status == RfidCard.Status.BLOCKED
         else ('Expired' if c.is_expired else 'Accepted')}
        for c in RfidCard.objects.exclude(status=RfidCard.Status.PENDING)
    ]
    # Versiya — ro'yxat o'zgarganini charger shu son orqali biladi.
    # Vaqt belgisidan olamiz: har yuborishda albatta o'sadi.
    version = int(timezone.now().timestamp())

    station_id = request.POST.get('station', '').strip()
    targets = Station.objects.exclude(ocpp_id__isnull=True).exclude(ocpp_id='')
    if station_id.isdigit():
        targets = targets.filter(id=int(station_id))

    # Sabab aniq aytilishi kerak: "topilmadi" degan quruq xabar operatorni
    # nima qilish kerakligidan bexabar qoldiradi.
    if not targets.exists():
        if Station.objects.exists():
            messages.error(
                request,
                "Hech bir stansiyaga OCPP Charge Point ID berilmagan — ro'yxat "
                "yuboriladigan qurilma yo'q. Stansiyani tahrirlash sahifasida "
                "chargerning ID sini kiriting.",
            )
        else:
            messages.error(request, "Hali stansiya qo'shilmagan")
        return _back(request)

    sent = skipped = 0
    for station in targets:
        if not station.is_online:
            skipped += 1
            continue
        try:
            ocpp_commands.send_local_list(station.ocpp_id, version, cards)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f'{station.name}: {exc}')

    if sent:
        messages.success(request, f"{len(cards)} ta karta {sent} ta chargerga yuborildi")
    if skipped:
        messages.error(
            request,
            f"{skipped} ta charger oflayn — ularga yetkazilmadi. "
            f"Ular tarmoqqa qaytganda qayta yuboring.",
        )
    return _back(request)


def card_usage(sessions):
    """Karta bo'yicha sarf statistikasi: qaysi stansiyada qancha.

    Ikki manbadan yig'iladi:
      * TUGAGAN sessiyalar — bazada `final_kwh_charged` / `final_cost`
        muzlatilgan, shuning uchun SQL darajasida yig'iladi (tez va aniq);
      * KETAYOTGAN sessiyalar — yakuniy qiymati hali yo'q, ular Python'da
        qo'shiladi. Ular bir vaqtda sanoqli bo'lgani uchun bu arzon.

    Butun ro'yxatni Python'da aylantirish ham mumkin edi, lekin ko'p
    sessiyali kartada bu sahifani sekinlashtirardi.
    """
    finished = sessions.exclude(final_cost__isnull=True)

    rows = {}
    for item in finished.values('station_id', 'station__name').annotate(
        count=Count('id'),
        kwh=Sum('final_kwh_charged'),
        cost=Sum('final_cost'),
    ):
        rows[item['station_id']] = {
            'name': item['station__name'],
            'count': item['count'],
            'kwh': item['kwh'] or 0,
            'cost': item['cost'] or 0,
        }

    active = sessions.filter(final_cost__isnull=True)
    for session in active:
        row = rows.setdefault(session.station_id, {
            'name': session.station.name, 'count': 0, 'kwh': 0, 'cost': 0,
        })
        row['count'] += 1
        row['kwh'] += session.kwh_charged
        row['cost'] += session.cost_so_far

    stations = sorted(rows.values(), key=lambda r: r['cost'], reverse=True)

    total_kwh = sum(r['kwh'] for r in stations)
    total_cost = sum(r['cost'] for r in stations)
    total_count = sum(r['count'] for r in stations)

    # Ustun uzunligi eng ko'p sarflangan stansiyaga nisbatan
    top_cost = stations[0]['cost'] if stations else 0
    for row in stations:
        row['pct'] = round(row['cost'] / top_cost * 100) if top_cost else 0
        row['share'] = round(row['cost'] / total_cost * 100) if total_cost else 0

    return {
        'stations': stations,
        'count': total_count,
        'kwh': total_kwh,
        'cost': total_cost,
        'avg_cost': round(total_cost / total_count) if total_count else 0,
        'top': stations[0] if stations else None,
    }


@staff_required
def rfid_card_detail(request, pk):
    """Karta sahifasi: tahrirlash va u bilan bo'lgan sessiyalar tarixi.

    Tahrirlash aynan shu yerda kerak bo'ladi: qurilma noma'lum kartani
    ro'yxatga EGASIZ qo'shadi, keyin operator uni kimgadir biriktirishi
    shart. Ilgari buning imkoni yo'q edi.
    """
    card = get_object_or_404(RfidCard.objects.select_related('user', 'company'), pk=pk)
    form = RfidCardForm(request.POST or None, instance=card)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Karta saqlandi')
        return redirect('dashboard:rfid_card_detail', pk=card.pk)

    # Karta bilan bo'lgan sessiyalar — nizoli holatlarda shu ro'yxat kerak
    sessions = ChargingSession.objects.filter(
        id_tag=card.id_tag
    ).select_related('station', 'user').order_by('-started_at')

    return render(request, 'dashboard/rfid_card_detail.html', {
        'card': card,
        'form': form,
        'sessions_page': Paginator(sessions, 10).get_page(request.GET.get('page')),
        'usage': card_usage(sessions),
        'extend_options': EXTEND_OPTIONS,
    })


@staff_required
def rfid_bulk(request):
    """Belgilangan kartalar ustida ommaviy amal.

    20 ta kartani birma-bir bosish o'rniga belgilab, bir marta.
    """
    if request.method != 'POST':
        return _back(request)

    ids = request.POST.getlist('ids')
    action = request.POST.get('bulk_action')
    if not ids:
        messages.error(request, 'Hech qanday karta belgilanmagan')
        return _back(request)

    cards = RfidCard.objects.filter(id__in=ids)
    if action == 'extend':
        try:
            months = int(request.POST.get('months', 0))
        except ValueError:
            months = 0
        if months not in dict(EXTEND_OPTIONS):
            messages.error(request, 'Uzaytirish muddati tanlanmagan')
            return _back(request)
        for card in cards:
            card.expires_at = _extend_until(card, months)
            card.save(update_fields=['expires_at'])
        messages.success(request, f'{cards.count()} ta kartaning muddati uzaytirildi')
    elif action == 'delete':
        count = cards.count()
        cards.delete()
        messages.success(request, f"{count} ta karta o'chirildi")
    elif action in dict(RfidCard.Status.choices):
        # Operator bloklaganda "egasi bloklagan" belgisi tozalanadi —
        # aks holda foydalanuvchi uni o'zi ochib yuborardi.
        count = cards.update(status=action, blocked_by_owner=False)
        label = dict(RfidCard.Status.choices)[action].lower()
        messages.success(request, f'{count} ta karta: {label}')
    else:
        messages.error(request, "Noma'lum amal")
    return _back(request)


# ═══════════════════════════════════════════════════════════════
#  Korporativ mijozlar
# ═══════════════════════════════════════════════════════════════
def _company_filters(request):
    """Manzildagi filtrlarni o'qiydi.

    Qidiruv va holat tabi doim ko'rinib turadi, qolganlari («Filtr» oynasi)
    kamdan-kam kerak bo'ladi — ular ham shu yerda, bitta joyda o'qiladi,
    shunda ro'yxat ham, tugmadagi son ham bir xil qoidaga tayanadi.
    """
    get = request.GET
    return {
        'q': get.get('q', '').strip(),
        'status': get.get('status', '').strip(),
        'inn': get.get('inn', '').strip(),
        'account': get.get('account', '').strip(),
        'mfo': get.get('mfo', '').strip(),
        'min_balance': strip_separators(get.get('min_balance', '')).strip(),
        'max_balance': strip_separators(get.get('max_balance', '')).strip(),
        'cards': get.get('cards', '').strip(),          # with | without
        'bank': get.get('bank', '').strip(),            # full | missing
        'sort': get.get('sort', '').strip(),
    }


# «Filtr» tugmasidagi son SHU maydonlar bo'yicha hisoblanadi: qidiruv va
# holat tabi ko'rinib turadi, ularni qayta sanash chalkashtirardi
ADVANCED_FILTERS = ('inn', 'account', 'mfo', 'min_balance', 'max_balance', 'cards', 'bank')

COMPANY_SORTS = {
    'name': 'name',
    'balance': '-billing_user__wallet__amount',
    'cards': '-card_count',
    'new': '-id',
}


def _as_int(value):
    """Balans maydonidagi qiymatni butun songa aylantiradi.

    Maydon pul formatida ishlaydi va fokusdan chiqqanda "1 000 000.00"
    ko'rinishiga keladi — kasr qismi bilan. Faqat raqamni kutgan tekshiruv
    bunday qiymatni rad etib, filtrni jimgina e'tiborsiz qoldirardi.
    """
    value = (value or '').strip()
    if not value:
        return None
    try:
        return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


@staff_required
def companies(request):
    filters = _company_filters(request)
    rows = Company.objects.select_related('billing_user__wallet').annotate(
        card_count=Count('cards', distinct=True),
    )

    if filters['q']:
        # Qidiruv rekvizitlarni ham qamraydi: buxgalteriya odatda STIR yoki
        # hisob raqami bilan qidiradi, nomni esa har xil yozishi mumkin
        rows = rows.filter(
            Q(name__icontains=filters['q'])
            | Q(legal_name__icontains=filters['q'])
            | Q(contact_name__icontains=filters['q'])
            | Q(contact_phone__icontains=filters['q'])
            | Q(inn__icontains=filters['q'])
            | Q(bank_account__icontains=filters['q'])
        )

    if filters['status'] == 'active':
        rows = rows.filter(is_active=True)
    elif filters['status'] == 'inactive':
        rows = rows.filter(is_active=False)
    elif filters['status'] == 'debtor':
        # Balansi bo'sh mijoz: kartalari ishlamaydi — birinchi navbatda
        # ko'riladigan ro'yxat
        rows = rows.filter(
            Q(billing_user__wallet__amount__lte=0) | Q(billing_user__wallet__isnull=True))

    if filters['inn']:
        rows = rows.filter(inn__icontains=filters['inn'])
    if filters['account']:
        rows = rows.filter(bank_account__icontains=filters['account'])
    if filters['mfo']:
        rows = rows.filter(bank_mfo__icontains=filters['mfo'])

    low = _as_int(filters['min_balance'])
    high = _as_int(filters['max_balance'])
    if low is not None:
        rows = rows.filter(billing_user__wallet__amount__gte=low)
    if high is not None:
        # Hamyon yozuvi hali yaratilmagan mijozning balansi — nol. Oddiy
        # solishtiruv uni ro'yxatdan butunlay tushirib qoldirardi.
        rows = rows.filter(
            Q(billing_user__wallet__amount__lte=high)
            | Q(billing_user__wallet__isnull=True))

    if filters['cards'] == 'with':
        rows = rows.filter(card_count__gt=0)
    elif filters['cards'] == 'without':
        rows = rows.filter(card_count=0)

    if filters['bank'] == 'full':
        rows = rows.exclude(Q(inn='') | Q(bank_account='') | Q(bank_mfo=''))
    elif filters['bank'] == 'missing':
        rows = rows.filter(Q(inn='') | Q(bank_account='') | Q(bank_mfo=''))

    rows = rows.order_by(COMPANY_SORTS.get(filters['sort'], 'name'))

    # Umumiy ko'rsatkichlar — filtrdan qat'i nazar butun baza bo'yicha
    everything = Company.objects.select_related('billing_user__wallet')
    totals = {
        'count': everything.count(),
        'active': everything.filter(is_active=True).count(),
        'cards': RfidCard.objects.filter(company__isnull=False).count(),
        'balance': sum(c.balance for c in everything),
        # Yozilgan, lekin hali kelmagan bank o'tkazmalari
        'pending': (CompanyInvoice.objects
                    .filter(status=CompanyInvoice.Status.PENDING)
                    .aggregate(total=Sum('amount'))['total'] or 0),
        'pending_count': CompanyInvoice.objects.filter(
            status=CompanyInvoice.Status.PENDING).count(),
    }

    return render(request, 'dashboard/companies.html', {
        'page_obj': Paginator(rows, PAGE_SIZE).get_page(request.GET.get('page')),
        'totals': totals,
        'filters': filters,
        'q': filters['q'],
        'status': filters['status'],
        'found': rows.count(),
        'advanced_count': sum(1 for key in ADVANCED_FILTERS if filters[key]),
    })


@staff_required
def company_form_view(request, pk=None):
    """Yangi mijoz. Mavjudini tahrirlash batafsil sahifada, bo'limlar bo'yicha."""
    instance = get_object_or_404(Company, pk=pk) if pk else None
    if instance is not None:
        return redirect('dashboard:company_detail', pk=instance.pk)

    form = CompanyForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        company = form.save()
        messages.success(request, f"{company.name} qo'shildi")
        return redirect('dashboard:company_detail', pk=company.pk)

    return render(request, 'dashboard/company_form.html', {'form': form, 'instance': None})


@staff_required
def company_section_edit(request, pk, section):
    """Batafsil sahifadagi bitta bo'limni saqlaydi.

    Har bo'lim o'z formasi bilan tekshiriladi: rekvizitlarni tahrirlashda
    mijoz nomi ham yuborilishi shart emas, ya'ni bir bo'limdagi xato
    boshqasini saqlashga xalaqit qilmaydi.
    """
    company = get_object_or_404(Company, pk=pk)
    form_class = COMPANY_SECTIONS.get(section)
    if form_class is None or request.method != 'POST':
        return redirect('dashboard:company_detail', pk=pk)

    form = form_class(request.POST, instance=company)
    if form.is_valid():
        form.save()
        messages.success(request, 'Saqlandi')
    else:
        # Oyna sahifaning bir qismi — xatoni maydon ostida emas, xabar
        # satrida ko'rsatamiz, shunda operator uni darrov ko'radi
        for field, errors in form.errors.items():
            label = form.fields[field].label if field in form.fields else ''
            messages.error(request, f'{label}: {errors[0]}' if label else errors[0])

    return redirect('dashboard:company_detail', pk=pk)


@staff_required
def company_detail(request, pk):
    company = get_object_or_404(
        Company.objects.select_related('billing_user__wallet'), pk=pk)

    # Kompaniya sessiyalari — hisob foydalanuvchisi bo'yicha
    sessions = ChargingSession.objects.filter(
        user=company.billing_user
    ).select_related('station').order_by('-started_at')

    return render(request, 'dashboard/company_detail.html', {
        'company': company,
        'cards': company.cards.select_related('user').order_by('-created_at'),
        'sessions_page': Paginator(sessions, 10).get_page(request.GET.get('page')),
        'session_count': sessions.count(),
        'transactions': company.billing_user.transactions.order_by('-created_at')[:10],
        'invoices': company.invoices.all()[:20],
        # Kutilayotgan summa — «qancha pul yo'lda» degan savolga javob
        'pending_total': sum(
            invoice.amount for invoice in company.invoices.all()
            if invoice.is_pending
        ),
        'next_invoice_number': CompanyInvoice.next_number(),
        # Bo'limlar sahifaning O'ZIDA tahrirlanadi: alohida sahifaga o'tib,
        # keyin qaytish uchun ikki qadam ketardi va kontekst yo'qolardi
        'section_forms': {name: form(instance=company)
                          for name, form in COMPANY_SECTIONS.items()},
    })


@staff_required
def company_topup(request, pk):
    """Korporativ hamyonni to'ldirish.

    Korporativ mijoz odatda bank o'tkazmasi bilan to'laydi — pul kelgach
    operator uni qo'lda kiritadi. Tranzaksiya izohida to'lov asosi
    (to'lov topshiriqnomasi raqami) saqlanadi, aks holda buxgalteriya
    keyin qaysi pul qayerdan kelganini topa olmasdi.
    """
    company = get_object_or_404(Company.objects.select_related('billing_user'), pk=pk)
    if request.method != 'POST':
        return redirect('dashboard:company_detail', pk=pk)

    raw = strip_separators(request.POST.get('amount') or '')
    try:
        amount = int(Decimal(raw).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        messages.error(request, "Summani to'g'ri kiriting")
        return redirect('dashboard:company_detail', pk=pk)

    if amount <= 0:
        messages.error(request, "Summa noldan katta bo'lishi kerak")
        return redirect('dashboard:company_detail', pk=pk)

    reference = (request.POST.get('reference') or '').strip()[:150]

    with transaction.atomic():
        wallet, _ = WalletBalance.objects.select_for_update().get_or_create(
            user=company.billing_user)
        wallet.amount += amount
        wallet.save(update_fields=['amount'])

        description = f'Korporativ to\'ldirish — {company.name}'
        if reference:
            description += f' ({reference})'
        Transaction.objects.create(
            user=company.billing_user, type=Transaction.Type.TOPUP,
            amount=amount, description=description[:255],
        )

    messages.success(
        request,
        f"{format_som(amount)} so'm qo'shildi. Yangi balans: {format_som(wallet.amount)} so'm",
    )
    return redirect('dashboard:company_detail', pk=pk)


@staff_required
def company_contract(request, pk):
    """Korporativ mijoz bilan shartnoma shablonini Word faylida beradi.

    Fayl har safar qaytadan yig'iladi — mijoz rekvizitlari, tariflar va
    kartalar ro'yxati o'zgarib turadi. Saqlab qo'yilgan fayl eskirgan
    ma'lumot bilan chiqib ketardi.
    """
    company = get_object_or_404(Company, pk=pk)

    # Import shu yerda: `python-docx` — ixtiyoriy kutubxona. U o'rnatilmagan
    # serverda butun panel qulab tushmasligi kerak, faqat shu tugma ishlamaydi.
    try:
        from .contracts import build_company_contract
    except ModuleNotFoundError:
        messages.error(
            request,
            "Word hujjatlari uchun `python-docx` o'rnatilmagan — "
            "`pip install -r requirements.txt` ni bajaring",
        )
        return redirect('dashboard:company_detail', pk=company.pk)

    document = build_company_contract(company)

    # Fayl nomida faqat xavfsiz belgilar qoldiramiz — kirill yoki maxsus
    # belgilar ba'zi brauzerlarda yuklab olishni buzadi
    slug = re.sub(r'[^A-Za-z0-9]+', '-', company.name).strip('-').lower() or 'mijoz'
    filename = f'shartnoma-{slug}-{timezone.now():%Y%m%d}.docx'

    return _docx_response(document, filename)


def _docx_response(document, filename):
    """Word faylini yuklab olish uchun javob."""
    response = HttpResponse(
        document.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ═══════════════════════════════════════════════════════════════
#  To'lov hisoblari (bank o'tkazmasi bilan to'ldirish)
# ═══════════════════════════════════════════════════════════════
def _invoice_amount(request):
    """Formadan summani o'qiydi. Xato bo'lsa (None, xabar) qaytaradi."""
    raw = strip_separators(request.POST.get('amount') or '')
    try:
        amount = int(Decimal(raw).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None, "Summani to'g'ri kiriting"
    if amount <= 0:
        return None, "Summa noldan katta bo'lishi kerak"
    return amount, None


@staff_required
def company_invoice_create(request, pk):
    """Mijozga to'lov hisobi yozadi (hamyon hali to'ldirilmaydi).

    Pul bank orqali keladi va bu bir necha kun oladi. Hisob shu oraliqni
    ko'rsatib turadi: mijoz nima uchun, qancha to'lashi kerak.
    """
    company = get_object_or_404(Company, pk=pk)
    if request.method != 'POST':
        return redirect('dashboard:company_detail', pk=pk)

    amount, error = _invoice_amount(request)
    if error:
        messages.error(request, error)
        return redirect('dashboard:company_detail', pk=pk)

    purpose = (request.POST.get('purpose') or '').strip()[:255]
    invoice = CompanyInvoice.objects.create(
        company=company,
        number=CompanyInvoice.next_number(),
        amount=amount,
        purpose=purpose or CompanyInvoice._meta.get_field('purpose').default,
        note=(request.POST.get('note') or '').strip()[:255],
        created_by=request.user,
    )
    messages.success(
        request,
        f"Hisob №{invoice.number} yozildi — {format_som(amount)} so'm. "
        f"Word faylini yuklab mijozga yuboring.",
    )
    return redirect('dashboard:company_detail', pk=pk)


@staff_required
def company_invoice_paid(request, pk):
    """Bank o'tkazmasi kelganini qayd etadi va hamyonni to'ldiradi."""
    invoice = get_object_or_404(CompanyInvoice.objects.select_related('company'), pk=pk)
    if request.method != 'POST':
        return redirect('dashboard:company_detail', pk=invoice.company_id)

    payment_date = parse_date(request.POST.get('payment_date') or '')
    done = invoice.mark_paid(
        payment_ref=(request.POST.get('payment_ref') or '').strip(),
        payment_date=payment_date,
        user=request.user,
    )
    if done:
        messages.success(
            request,
            f"Hisob №{invoice.number} to'langan deb belgilandi — "
            f"{format_som(invoice.amount)} so'm hamyonga qo'shildi",
        )
    else:
        # Ikki operator bir vaqtda bosgan bo'lishi mumkin
        messages.error(request, f"Hisob №{invoice.number} allaqachon yopilgan")
    return redirect('dashboard:company_detail', pk=invoice.company_id)


@staff_required
def company_invoice_cancel(request, pk):
    """To'lanmagan hisobni bekor qiladi. To'langanini bekor qilib bo'lmaydi."""
    invoice = get_object_or_404(CompanyInvoice, pk=pk)
    if request.method == 'POST':
        if invoice.is_pending:
            invoice.status = CompanyInvoice.Status.CANCELLED
            invoice.save(update_fields=['status'])
            messages.success(request, f"Hisob №{invoice.number} bekor qilindi")
        else:
            # To'langan hisob buxgalteriya hujjati — u o'chirilmaydi
            messages.error(
                request,
                f"Hisob №{invoice.number} to'langan, uni bekor qilib bo'lmaydi",
            )
    return redirect('dashboard:company_detail', pk=invoice.company_id)


@staff_required
def company_invoice_document(request, pk):
    """Hisobni Word faylida beradi — mijoz uni banki orqali to'laydi."""
    invoice = get_object_or_404(CompanyInvoice.objects.select_related('company'), pk=pk)
    try:
        from .invoices import build_invoice_document
    except ModuleNotFoundError:
        messages.error(
            request,
            "Word hujjatlari uchun `python-docx` o'rnatilmagan — "
            "`pip install -r requirements.txt` ni bajaring",
        )
        return redirect('dashboard:company_detail', pk=invoice.company_id)

    document = build_invoice_document(invoice)
    return _docx_response(document, f'hisob-{invoice.number}.docx')
