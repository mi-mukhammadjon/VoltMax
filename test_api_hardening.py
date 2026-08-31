# -*- coding: utf-8 -*-
"""API ning umumiy himoyasi: ruxsat, so'rov chegarasi, parol qoidalari.

Eng xavfli narsa aniq bir xato emas, XATOGA MOYIL STANDART edi: DRF ning
standart ruxsati `AllowAny` turardi. Ya'ni yangi endpoint yozilганda
`permission_classes` ni yozish unutilsa, u jimgina hammaga ochiq bo'lib
qolardi. Bunday xato ko'zga tashlanmaydi — endpoint ishlayveradi, faqat
begona odam ham ko'ra oladi.

Endi standart — YOPIQ, ochiq bo'lishi kerak bo'lganlar buni o'zida aniq
yozadi. Bu sinov o'sha qoidani ushlab turadi: kelajakda kimdir yangi
endpoint qo'shsa va ruxsatni unutsa, shu yerda ko'rinadi.

Asosiy savollar:
  1. Kirmagan odam yopiq manzillarga kira oladimi?
  2. Ochiq bo'lishi kerak bo'lganlar ochiqmi (himoya haddan oshmaganmi)?
  3. Promo-kodni tanlash mumkinmi (so'rov chegarasi bormi)?
  4. Zaif parol qabul qilinadimi?
  5. Ishlab chiqarishda standart SECRET_KEY bilan server ishga tushadimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.core.exceptions import ValidationError  # noqa: E402
from django.contrib.auth.password_validation import validate_password  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from stations.models import Station  # noqa: E402

failures = 0

# Kirish talab qiladigan manzillar. Yangi endpoint qo'shilsa shu yerga
# ham qo'shish kerak — ro'yxat qoidaning yozma ifodasi.
PRIVATE = [
    '/api/auth/profile/',
    '/api/auth/vehicles/',
    '/api/auth/rfid-cards/',
    '/api/wallet/balance/',
    '/api/wallet/transactions/',
    '/api/wallet/providers/',
    '/api/sessions/',
    '/api/sessions/active/',
    '/api/sessions/insights/',
    '/api/bookings/',
    '/api/notifications/',
]

# Ataylab ochiq: odam avval stansiyalarni ko'radi, keyin ro'yxatdan o'tadi
PUBLIC = [
    '/api/stations/',
]


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    Station.objects.filter(name__startswith='__hard').delete()
    User.objects.filter(username__startswith='__hard').delete()
    cache.clear()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    try:
        anon = Client()

        # ── 1. Yopiq manzillar ──────────────────────────────────
        opened = [url for url in PRIVATE if anon.get(url).status_code not in (401, 403)]
        check('kirmagan odamga hamma yopiq manzil yopiq',
              not opened, opened)

        # ── 2. Ochiq manzillar ochiq qoldi ──────────────────────
        closed = [url for url in PUBLIC if anon.get(url).status_code != 200]
        check('ochiq manzillar ochiq qoldi', not closed, closed)

        # OTP ham ochiq bo'lishi shart: foydalanuvchi hali kirmagan
        sent = anon.post('/api/auth/send-otp/', {'phone': '998900000123'},
                         content_type='application/json')
        check('OTP so\'rash ochiq qoldi', sent.status_code != 401, sent.status_code)

        # ── 3. Kirgan foydalanuvchi ishlayveradi ────────────────
        driver = User.objects.create(username='__hard_driver__')
        me = Client()
        me.defaults['HTTP_AUTHORIZATION'] = (
            f'Bearer {RefreshToken.for_user(driver).access_token}')
        broken = [url for url in PRIVATE if me.get(url).status_code >= 400]
        check('kirgan foydalanuvchiga hammasi ochiq', not broken, broken)

        # ── 4. Promo-kodni tanlab bo'lmaydi ─────────────────────
        # Kod qisqa; urinishlar cheklanmagan bo'lsa uni topib olish
        # shunchaki vaqt masalasi edi
        cache.clear()
        station = Station.objects.create(
            name='__hard Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='DC', power_kw=60)

        codes = [me.post('/api/stations/promo/check/',
                         {'stationId': station.id, 'code': f'KOD{i}'},
                         content_type='application/json').status_code
                 for i in range(14)]
        check('promo-kod urinishlari cheklandi', 429 in codes,
              f'{codes.count(400)} ta rad, {codes.count(429)} ta to\'sildi')
        cache.clear()

        # ── 5. Parol qoidalari ──────────────────────────────────
        # Panel butun tarmoqni boshqaradi. Mobil foydalanuvchi parol
        # ishlatmaydi (OTP bilan kiradi), ya'ni qattiq talab hech kimga
        # noqulaylik tug'dirmaydi.
        weak = ['voltmax2026', '123456', 'parol', '12345678901', 'admin']
        accepted = []
        for password in weak:
            try:
                validate_password(password)
                accepted.append(password)
            except ValidationError:
                pass
        check('zaif parollar rad etildi', not accepted, accepted)

        try:
            validate_password('QuyoshliKun-92-Tashkent')
            strong_ok = True
        except ValidationError as error:
            strong_ok, = (False,)
            print('   ', error.messages)
        check('kuchli parol qabul qilindi', strong_ok)

        # ── 6. SECRET_KEY qorovuli ──────────────────────────────
        # Standart kalit kodda ochiq turibdi: server undan foydalansa,
        # istalgan odam o'zini xohlagan foydalanuvchi qilib ko'rsata oladi
        check('standart kalit hali ishlatilyapti (ishlab chiqishda normal)',
              settings.SECRET_KEY == settings.DEV_SECRET_KEY
              or len(settings.SECRET_KEY) > 20,
              'sozlangan' if settings.SECRET_KEY != settings.DEV_SECRET_KEY else 'dev')

        source = open('voltmax/settings.py', encoding='utf-8').read()
        check('ishlab chiqarishda kalitsiz ishga tushmaydi',
              'if not DEBUG and SECRET_KEY == DEV_SECRET_KEY' in source
              and 'raise RuntimeError' in source)

        # ── 7. Django admini ────────────────────────────────────
        check('admin sozlama bilan boshqariladi',
              hasattr(settings, 'ENABLE_DJANGO_ADMIN'))
        source = open('voltmax/urls.py', encoding='utf-8').read()
        check('admin manzili shartli ulangan',
              'ENABLE_DJANGO_ADMIN' in source)

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
