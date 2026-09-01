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


def check_mail():
    """Pochta: sozlanganmi va ogohlantirish kimga ketadi."""
    from management.mail import is_configured
    from management.models import SiteSettings

    settings_obj = SiteSettings.load()

    if not is_configured(settings_obj):
        return [{
            'key': 'mail',
            'title': 'Elektron pochta',
            'state': 'warn',
            'value': 'sozlanmagan',
            'hint': 'Hujjatlar qo‘lda yuboriladi, parolni tiklash ishlamaydi '
                    'va muammo haqida xabar kelmaydi',
        }]

    recipients = settings_obj.alert_recipients
    return [{
        'key': 'mail',
        'title': 'Elektron pochta',
        # Sozlangan-u, ogohlantirish manzili yo'q bo'lsa — tizim
        # muammosi haqida hech kim bilmaydi
        'state': 'warn' if not recipients else 'ok',
        'value': settings_obj.mail_host,
        'hint': (f"Ogohlantirish: {', '.join(recipients)}" if recipients
                 else 'Ogohlantirish manzili kiritilmagan — muammo haqida '
                      'xabar hech kimga bormaydi'),
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

    # Imzodan o'tmagan so'rovlar: kalitsiz hech narsa qilib bo'lmaydi,
    # lekin urinishning o'zi ko'rinib turishi kerak — kimdir kalit
    # tanlayotgan bo'lishi mumkin
    from management.login_guard import LoginAttempt

    rejected = LoginAttempt.objects.filter(
        username__startswith='webhook:',
        created_at__gte=timezone.now() - timedelta(hours=24)).count()

    if not active:
        state, hint = 'down', 'Yoqilgan to‘lov tizimi yo‘q — hamyon to‘ldirilmaydi'
    elif not configured:
        state, hint = 'down', 'Yoqilgan, lekin identifikatorlari to‘ldirilmagan'
    elif stuck:
        state, hint = 'warn', f'{stuck} ta to‘lov 2 soatdan beri yakunlanmagan'
    elif rejected > 20:
        # Ko'p rad etilgan so'rov ikki narsani bildirishi mumkin:
        # panelda kalit xato kiritilgan yoki kimdir uni tanlayapti
        state = 'warn'
        hint = (f'Sutkada {rejected} ta so‘rov imzodan o‘tmadi — kalit '
                f'xato kiritilgan yoki kimdir tanlayapti')
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

    # Parolsiz manzil — ochiq eshik: `ocpp_id` maxfiy emas (qurilma ustida
    # yozilgan, panelda ko'rinadi, odatda ketma-ket), ya'ni uni bilgan har
    # kim soxta charger bo'lib ulanib, begona odamning hamyonidan pul
    # yechishi mumkin
    from management.models import SiteSettings

    unprotected = [s for s in linked if not s.ocpp_password]
    if unprotected:
        names = ', '.join(s.name for s in unprotected)[:120]
        required = SiteSettings.load().require_ocpp_auth
        # Ikki xil holat, ikki xil oqibat:
        #   parol majburiy   → charger ULANA OLMAYDI (ish to'xtaydi)
        #   majburiy emas    → manzil OCHIQ turadi (pul yo'qotish xavfi)
        checks_extra = [{
            'key': 'ocpp-auth',
            'title': 'OCPP paroli',
            'state': 'warn' if required else 'down',
            'value': f'{len(unprotected)} ta stansiyada yo‘q',
            'hint': (f'{names} — parol qo‘yilmaguncha charger ulana olmaydi'
                     if required else
                     f'{names} — manzilni bilgan har kim ulana oladi va '
                     f'begona hamyondan pul yechishi mumkin'),
        }]
    else:
        checks_extra = [{
            'key': 'ocpp-auth',
            'title': 'OCPP paroli',
            'state': 'ok',
            'value': 'hammasida bor',
            'hint': 'Charger o‘zini parol bilan tanishtiradi',
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

    return checks_extra + [{
        'key': 'ocpp',
        'title': 'Chargerlar (OCPP)',
        'state': state,
        'value': f'{len(online)} / {len(linked)} onlayn',
        'hint': hint,
    }]


def check_otp(with_network=True):
    """OTP shlyuzi: kalit bormi.

    Kalit yo'q yoki noto'g'ri bo'lsa HECH KIM ilovaga kira olmaydi.
    Bu eng jim buziladigan joy: xato faqat haqiqiy foydalanuvchi
    kirmoqchi bo'lganda chiqadi.
    """
    from management.models import SiteSettings

    source = SiteSettings.load().otp_token_source
    if source == 'yo‘q':
        state = 'down'
        hint = ('Kirish kodlari yuborilmaydi — ilovaga kirib bo‘lmaydi. '
                'Sozlamalar > Xavfsizlik')
    else:
        state = 'ok'
        hint = ('Panelda saqlangan' if source == 'panel'
                else 'Server sozlamasida (TELEGRAM_GATEWAY_TOKEN)')

    checks = [{
        'key': 'otp',
        'title': 'OTP shlyuzi',
        'state': state,
        'value': 'sozlangan' if state == 'ok' else 'sozlanmagan',
        'hint': hint,
    }]

    # Zaxira kanal. Telegramning o'zi ishlab tursa ham, u BITTA nuqta:
    # hisobda mablag' tugasa hech kim kira olmaydi. SMS shu holatni
    # yopadi, shuning uchun uning yo'qligi ogohlantirish.
    from management import sms

    settings_obj = SiteSettings.load()
    if not sms.is_configured(settings_obj):
        checks.append({
            'key': 'sms',
            'title': 'SMS (zaxira kanal)',
            'state': 'warn',
            'value': "o'chirilgan",
            'hint': 'Telegram ishlamay qolsa kirish to‘xtaydi. Telegrami '
                    'yo‘q odam esa umuman kira olmaydi',
        })
    else:
        # Balans TARMOQ so'rovi: sahifa uni kutmasligi kerak
        left = sms.balance() if with_network else None
        # Balans past bo'lsa SMS jimgina ketmay qo'yadi
        low = left is not None and left < 50
        checks.append({
            'key': 'sms',
            'title': 'SMS (zaxira kanal)',
            'state': 'warn' if low else 'ok',
            'value': ('balans noma‘lum' if left is None else f'balans: {left}'),
            'hint': ('Hisobni to‘ldiring — SMS tugash arafasida' if low
                     else f'{settings_obj.sms_login} orqali'),
        })

    return checks


def check_security():
    """Xavfsizlik: standart parol va parol tanlash urinishlari."""
    from django.conf import settings as django_settings

    from management.login_guard import LoginAttempt, uses_default_password
    from management.models import SiteSettings

    checks = []

    risky = uses_default_password()
    checks.append({
        'key': 'default-password',
        'title': 'Standart parol',
        'state': 'down' if risky else 'ok',
        'value': ', '.join(risky) if risky else 'almashtirilgan',
        'hint': ('Bu parol hujjatlarda ochiq yozilgan — parol emas, taklifnoma'
                 if risky else 'Standart parolli hisob yo‘q'),
    })

    settings_obj = SiteSettings.load()
    if not settings_obj.panel_max_attempts:
        checks.append({
            'key': 'login-guard',
            'title': 'Panel login himoyasi',
            'state': 'down',
            'value': "o'chirilgan",
            'hint': 'Parolni cheksiz sinab ko‘rish mumkin',
        })
    else:
        failed = LoginAttempt.objects.filter(
            successful=False,
            created_at__gte=timezone.now() - timedelta(hours=24)).count()
        checks.append({
            'key': 'login-guard',
            'title': 'Panel login himoyasi',
            'state': 'warn' if failed > 20 else 'ok',
            'value': f'sutkada {failed} ta rad etilgan urinish',
            'hint': ('Odatdagidan ko‘p — kimdir parol tanlayotgan bo‘lishi mumkin'
                     if failed > 20
                     else f'{settings_obj.panel_max_attempts} ta urinishdan keyin bloklanadi'),
        })

    # Administrator hisoblari ikkinchi to'siqsiz qolmasin: parol oshkor
    # bo'lsa (fishing, qayta ishlatilgan parol) boshqa hech narsa yo'q
    from django.contrib.auth.models import User

    from management.totp import TwoFactor

    admins = list(User.objects.filter(is_staff=True, is_superuser=True, is_active=True))
    protected = set(TwoFactor.objects.filter(
        user__in=admins, confirmed_at__isnull=False).values_list('user_id', flat=True))
    exposed = [a.username for a in admins if a.pk not in protected]

    if admins:
        checks.append({
            'key': 'two-factor',
            'title': 'Ikki bosqichli kirish',
            'state': 'warn' if exposed else 'ok',
            'value': (f'{len(admins) - len(exposed)} / {len(admins)} administratorda'),
            'hint': (', '.join(exposed)[:150] + ' — faqat parol bilan kiradi'
                     if exposed else 'Barcha administratorlarda yoqilgan'),
        })

    # Django admini ochiq qolgan bo'lsa — qo'shimcha hujum yuzasi:
    # uning kirish formasi bizning urinishlar chegarasidan o'tmaydi
    if getattr(django_settings, 'ENABLE_DJANGO_ADMIN', False) and not django_settings.DEBUG:
        checks.append({
            'key': 'django-admin',
            'title': 'Django admini',
            'state': 'warn',
            'value': 'ochiq',
            'hint': 'Panel hamma ishni qamrab oladi. Kerak bo‘lmasa '
                    'ENABLE_DJANGO_ADMIN=False qo‘ying',
        })

    # DEBUG productionda yoqiq qolsa, xato sahifalari butun kodni va
    # sozlamalarni ko'rsatib turadi.
    #
    # Ishlab chiqish mashinasida DEBUG yoqiq bo'lishi NORMAL, shuning
    # uchun u yerda «muammo» deb baqirmaydi: har doim qizil turadigan
    # tekshiruvga hech kim e'tibor bermay qo'yadi. Farq `ALLOWED_HOSTS`
    # dan bilinadi — unda tashqi domen bo'lsa, bu haqiqiy server.
    if django_settings.DEBUG:
        local = {'localhost', '127.0.0.1', '10.0.2.2', ''}
        public = [h for h in django_settings.ALLOWED_HOSTS
                  if h not in local and not h.startswith('192.168.')]
        checks.append({
            'key': 'debug',
            'title': 'DEBUG rejimi',
            'state': 'down' if public else 'warn',
            'value': 'yoqilgan',
            'hint': ('Xato sahifalari kod va sozlamalarni ko‘rsatadi — '
                     'serverda DEBUG=False bo‘lishi SHART' if public
                     else 'Ishlab chiqish mashinasida bu normal'),
        })

    return checks


def check_backup():
    """Zaxira nusxa: oxirgi marta qachon olingan va qayerda yotibdi."""
    from django.conf import settings as django_settings

    from management.jobs import JobStatus

    row = JobStatus.objects.filter(name='backup').first()
    if row is None or row.last_ok_at is None:
        return [{
            'key': 'backup',
            'title': 'Zaxira nusxa',
            'state': 'down',
            'value': 'olinmagan',
            'hint': 'Bazada pul harakati bor — nusxasiz ishlash xavfli',
        }]

    age = int((timezone.now() - row.last_ok_at).total_seconds())
    # Kundalik vazifa; ikki kun o'tsa nimadir buzilgan
    if age > 2 * 24 * 3600:
        state, hint = 'down', 'Ikki kundan beri nusxa olinmagan'
    elif not getattr(django_settings, 'USE_R2', False):
        state = 'warn'
        hint = ('Nusxa faqat shu serverning diskida — Railway‘da disk har '
                'deploy‘da tozalanadi. R2 sozlansa nusxa saqlanib qoladi')
    else:
        state, hint = 'ok', row.last_summary

    return [{
        'key': 'backup',
        'title': 'Zaxira nusxa',
        'state': state,
        'value': _human_age(age),
        'hint': hint,
    }]


def check_media():
    """Yuklangan fayllar qayerda saqlanadi."""
    from django.conf import settings as django_settings

    if getattr(django_settings, 'USE_R2', False):
        return [{
            'key': 'media',
            'title': 'Rasm va fayllar',
            'state': 'ok',
            'value': 'R2',
            'hint': 'Fayllar tashqi saqlashda — deploy ularga tegmaydi',
        }]

    return [{
        'key': 'media',
        'title': 'Rasm va fayllar',
        'state': 'warn',
        'value': 'serverning diski',
        'hint': 'Railway‘da disk har deploy‘da tozalanadi — yuklangan '
                'stansiya rasmlari yo‘qoladi. R2_BUCKET sozlang',
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


# Qisqa kesh: bosh sahifadagi ogohlantirish HAR YUKLASHDA to'liq
# tekshiruv o'tkazardi — o'nlab so'rov va hatto SMS xizmatiga tarmoq
# so'rovi. Dashboard shu sababli sekinlashardi.
#
# Ogohlantirish uchun yarim daqiqalik eskilik mutlaqo yetarli:
# muammo bir necha soniya kechroq ko'rinsa hech narsa o'zgarmaydi.
_CACHE_TTL = 30
_cached = {'at': 0.0, 'value': None}


def collect(cached=False, with_network=True):
    """Barcha tekshiruvlar va umumiy holat.

    `cached` — tez-tez chaqiriladigan joylar uchun (bosh sahifadagi
    ogohlantirish). Alohida holat sahifasi va `manage.py health` har
    doim yangisini oladi: u yerga odam AYNAN tekshirish uchun keladi.

    `with_network` — tashqi xizmatga so'rov yuborilsinmi (SMS balansi).
    Sahifa yuklanishi begona xizmatning javobini kutmasligi kerak.

    Har tekshiruv alohida himoyalangan: bittasi yiqilsa ham sahifa
    ochilishi kerak — u aynan tizim buzilganda kerak bo'ladi.
    """
    import time

    if cached and _cached['value'] is not None:
        if time.monotonic() - _cached['at'] <= _CACHE_TTL:
            return _cached['value']

    checks = []
    for func in (check_jobs, check_push, check_payments, check_chargers,
                 check_otp, check_mail, check_security, check_backup,
                 check_media, check_settings):
        try:
            checks.extend(func(with_network=with_network)
                          if func is check_otp else func())
        except Exception as error:      # noqa: BLE001
            checks.append({
                'key': func.__name__,
                'title': func.__name__,
                'state': 'warn',
                'value': 'tekshirib bo‘lmadi',
                'hint': f'{type(error).__name__}: {error}'[:200],
            })

    overall = _state(*[c['state'] for c in checks]) if checks else 'ok'
    report = {
        'checks': checks,
        'overall': overall,
        'down': [c for c in checks if c['state'] == 'down'],
        'warn': [c for c in checks if c['state'] == 'warn'],
        'checked_at': timezone.now(),
    }

    if cached:
        _cached['at'] = time.monotonic()
        _cached['value'] = report
    return report
