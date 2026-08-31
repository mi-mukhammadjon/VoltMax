# -*- coding: utf-8 -*-
"""Tizim holati — «hozir hamma narsa ishlayaptimi?» degan savolga javob.

Nima uchun kerak: tizimning yarmi so'rovdan tashqarida ishlaydi —
davriy vazifalar, push yetkazish, to'lov tizimlarining javobi, OCPP
ulanishlari. Ularning hech biri panelda ko'rinmasdi. Servis serverda
umuman ishga tushmagan bo'lsa ham panel «hammasi joyida» ko'rinishida
turaverardi.

Har tekshiruv uchta holatdan birini qaytaradi:

    ok    — ishlayapti
    warn  — e'tibor bering, lekin hozircha xizmatga ta'sir qilmayapti
    down  — ishlamayapti, foydalanuvchi buni sezadi

Muhim qoida: tekshiruvlarning HECH BIRI xato tashlamaydi. Holat sahifasi
tizim buzilganda ochilishi kerak — aynan o'shanda kerak bo'ladi.
"""
from datetime import timedelta

from django.utils import timezone

# Vazifa oxirgi ishlaganidan keyin necha marta o'z oralig'i o'tsa
# «ishlamayapti» deb hisoblanadi. Bittasi kam: tarmoq sekinlashsa yoki
# server band bo'lsa bitta tsikl kechikishi normal.
LATE_FACTOR = 3

# Push navbatida shuncha xabar yig'ilib qolsa — yetkazish to'xtagan
PUSH_QUEUE_WARN = 20


def _state(*states):
    """Bir nechta holatdan eng yomonini tanlaydi."""
    order = {'ok': 0, 'warn': 1, 'down': 2}
    return max(states, key=lambda s: order.get(s, 0)) if states else 'ok'


def _human_age(seconds):
    if seconds is None:
        return 'hech qachon'
    if seconds < 60:
        return f'{seconds} soniya oldin'
    if seconds < 3600:
        return f'{seconds // 60} daqiqa oldin'
    if seconds < 86400:
        return f'{seconds // 3600} soat oldin'
    return f'{seconds // 86400} kun oldin'


def check_jobs():
    """Davriy vazifalar: har biri o'z oralig'ida ishlayaptimi."""
    from management.jobs import JobStatus
    from management.management.commands.run_workers import JOBS

    rows = {row.name: row for row in JobStatus.objects.all()}
    checks = []

    for name, _func, interval in JOBS:
        row = rows.get(name)
        limit = interval * LATE_FACTOR

        if row is None or row.last_run_at is None:
            checks.append({
                'key': f'job:{name}',
                'title': f'Vazifa «{name}»',
                'state': 'down',
                'value': 'hech qachon ishlamagan',
                'hint': "Ishchi servis ishga tushmagan bo'lishi mumkin "
                        "(Railway: `python manage.py run_workers`)",
            })
            continue

        age = row.seconds_since_run
        late = age > limit

        if row.fail_streak >= 3:
            state, hint = 'down', row.last_error or 'ketma-ket xato bermoqda'
        elif late:
            state, hint = 'down', (f'har {interval} soniyada ishlashi kerak edi')
        elif row.last_error:
            state, hint = 'warn', row.last_error
        else:
            state, hint = 'ok', row.last_summary

        checks.append({
            'key': f'job:{name}',
            'title': f'Vazifa «{name}»',
            'state': state,
            'value': _human_age(age),
            'hint': hint,
        })

    return checks


def check_push():
    """Push yetkazish: qurilmalar bormi, navbat o'sib ketmadimi."""
    from accounts.models import DeviceToken
    from management.models import UserNotification

    devices = DeviceToken.objects.filter(is_active=True).count()
    pending = UserNotification.objects.filter(
        pushed_at__isnull=True, push_attempts__lt=3).count()
    failed = UserNotification.objects.filter(
        pushed_at__isnull=True, push_attempts__gte=3).count()

    if devices == 0:
        # Bu xato emas: hali hech kim ilovadan kirmagan bo'lishi mumkin
        state = 'warn'
        hint = "Ro'yxatda push manzili bor qurilma yo'q — xabar hech qayerga bormaydi"
    elif pending > PUSH_QUEUE_WARN:
        state = 'down'
        hint = 'Navbat o‘sib bormoqda — push vazifasi ishlamayotgan bo‘lishi mumkin'
    elif failed:
        state = 'warn'
        hint = f'{failed} ta xabar uch urinishdan keyin yetkazilmadi'
    else:
        state = 'ok'
        hint = f'{devices} ta qurilma ro‘yxatda'

    return [{
        'key': 'push',
        'title': 'Push xabarlar',
        'state': state,
        'value': f'navbatda {pending}',
        'hint': hint,
    }]


def check_payments():
    """To'lov tizimlari: sozlanganmi va oxirgi to'lov qachon o'tgan."""
    from management.models import PaymentProvider
    from wallet.models import PaymentOrder

    active = [p for p in PaymentProvider.objects.filter(is_active=True)]
    configured = [p for p in active if p.is_configured]

    last_paid = PaymentOrder.objects.filter(
        state=PaymentOrder.State.PAID).order_by('-id').first()
    # Uzoq "kutilmoqda" holatida qotgan buyurtma — to'lov tizimi bizning
    # serverga yeta olmayotganining eng aniq belgisi
    stuck = PaymentOrder.objects.filter(
        state__in=[PaymentOrder.State.CREATED, PaymentOrder.State.WAITING],
        created_at__lt=timezone.now() - timedelta(hours=2),
    ).count()

    if not active:
        state, hint = 'down', 'Yoqilgan to‘lov tizimi yo‘q — hamyon to‘ldirilmaydi'
    elif not configured:
        state, hint = 'down', 'Yoqilgan, lekin identifikatorlari to‘ldirilmagan'
    elif stuck:
        state, hint = 'warn', f'{stuck} ta to‘lov 2 soatdan beri yakunlanmagan'
    else:
        state, hint = 'ok', ', '.join(p.name for p in configured)

    value = ('to‘lov bo‘lmagan' if last_paid is None
             else f'oxirgisi {_human_age(int((timezone.now() - last_paid.created_at).total_seconds()))}')

    return [{
        'key': 'payments',
        'title': "To'lov tizimlari",
        'state': state,
        'value': value,
        'hint': hint,
    }]


def check_chargers():
    """OCPP: bog'langan chargerlarning nechtasi onlayn."""
    from stations.models import Station

    linked = [s for s in Station.objects.exclude(ocpp_id='').exclude(ocpp_id=None)]
    if not linked:
        return [{
            'key': 'ocpp',
            'title': 'Chargerlar (OCPP)',
            'state': 'warn',
            'value': 'bog‘lanmagan',
            'hint': 'Birorta stansiyaga OCPP ID berilmagan — hammasi qo‘lda boshqariladi',
        }]

    online = [s for s in linked if s.is_online]
    if not online:
        state = 'down'
        hint = 'Birorta charger ulanmagan — masofadan boshlash ishlamaydi'
    elif len(online) < len(linked):
        state = 'warn'
        hint = ', '.join(s.name for s in linked if not s.is_online)[:200] + ' — oflayn'
    else:
        state = 'ok'
        hint = 'Hammasi ulangan'

    return [{
        'key': 'ocpp',
        'title': 'Chargerlar (OCPP)',
        'state': state,
        'value': f'{len(online)} / {len(linked)} onlayn',
        'hint': hint,
    }]


def check_settings():
    """Sozlamadagi eng xavfli bo'shliqlar."""
    from management.models import SiteSettings

    settings_obj = SiteSettings.load()
    checks = []

    if not settings_obj.default_price_per_kwh:
        checks.append({
            'key': 'price',
            'title': 'Standart narx',
            'state': 'down',
            'value': 'belgilanmagan',
            'hint': 'Narxsiz sessiyalar bepul hisoblanadi',
        })

    return checks


def collect():
    """Barcha tekshiruvlar va umumiy holat.

    Har tekshiruv alohida himoyalangan: bittasi yiqilsa ham sahifa
    ochilishi kerak — u aynan tizim buzilganda kerak bo'ladi.
    """
    checks = []
    for func in (check_jobs, check_push, check_payments, check_chargers,
                 check_settings):
        try:
            checks.extend(func())
        except Exception as error:      # noqa: BLE001
            checks.append({
                'key': func.__name__,
                'title': func.__name__,
                'state': 'warn',
                'value': 'tekshirib bo‘lmadi',
                'hint': f'{type(error).__name__}: {error}'[:200],
            })

    overall = _state(*[c['state'] for c in checks]) if checks else 'ok'
    return {
        'checks': checks,
        'overall': overall,
        'down': [c for c in checks if c['state'] == 'down'],
        'warn': [c for c in checks if c['state'] == 'warn'],
        'checked_at': timezone.now(),
    }
