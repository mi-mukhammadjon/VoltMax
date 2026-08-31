# -*- coding: utf-8 -*-
"""Xavfsizlik sozlamalari HAQIQATAN qo'llanadimi.

Uch sozlama panelda turardi, lekin hech qayerda ishlatilmasdi:
OTP muddati, OTP urinishlar chegarasi va panel sessiyasi muddati.
Panelda bor, lekin ishlamaydigan sozlama eng yomon holat — operator
himoya bor deb o'ylaydi.

Asosiy savollar:
  1. OTP muddati sozlamadan olinadimi?
  2. Noto'g'ri kod urinishlari sanaladimi va chegara tugagach kod
     bloklanadimi?
  3. To'g'ri kod bilan kirish ishlaydimi (himoya haddan tashqari
     qattiq emasmi)?
  4. Panel sessiyasining muddati qo'yiladimi?
  5. Token yangilash manzili ishlaydimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import OTPCode  # noqa: E402
from management.models import SiteSettings  # noqa: E402

failures = 0
PHONE = '998900000777'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    OTPCode.objects.filter(phone=PHONE).delete()
    User.objects.filter(username=PHONE).delete()
    User.objects.filter(username__startswith='__sc').delete()


def verify(code):
    return Client().post('/api/auth/verify-otp/',
                         {'phone': PHONE, 'code': code},
                         content_type='application/json')


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f)
             for f in ('otp_ttl_minutes', 'otp_max_attempts', 'session_timeout_minutes')}
    try:
        settings_obj.otp_ttl_minutes = 5
        settings_obj.otp_max_attempts = 3
        settings_obj.session_timeout_minutes = 30
        settings_obj.save()

        # ── 1. Muddat sozlamadan ────────────────────────────────
        otp = OTPCode.objects.create(phone=PHONE, code='111111')
        check('yangi kod amal qiladi', not otp.is_expired)
        check('muddat sozlamadan olindi', otp.ttl_minutes == 5, otp.ttl_minutes)

        OTPCode.objects.filter(pk=otp.pk).update(
            created_at=timezone.now() - timedelta(minutes=6))
        otp.refresh_from_db()
        check('sozlamadagi muddat o\'tgach eskirdi', otp.is_expired)

        # Muddat oshirilsa o'sha kod yana amal qiladi
        settings_obj.otp_ttl_minutes = 30
        settings_obj.save(update_fields=['otp_ttl_minutes'])
        otp.refresh_from_db()
        check('muddat oshirilgach yana amal qildi', not otp.is_expired)
        settings_obj.otp_ttl_minutes = 5
        settings_obj.save(update_fields=['otp_ttl_minutes'])

        # ── 2. Urinishlar chegarasi ─────────────────────────────
        OTPCode.objects.filter(phone=PHONE).delete()
        OTPCode.objects.create(phone=PHONE, code='222222')

        first = verify('000000')
        check('noto\'g\'ri kod rad etildi', first.status_code == 400, first.status_code)
        check('urinish sanaldi',
              OTPCode.objects.get(phone=PHONE).attempts == 1,
              OTPCode.objects.get(phone=PHONE).attempts)

        verify('000001')
        third = verify('000002')
        check('chegara tugagach bloklandi', third.status_code == 429, third.status_code)
        check('sabab aytildi', 'Urinishlar' in third.json().get('detail', ''),
              third.json())

        # Bloklangandan keyin TO'G'RI kod ham ishlamaydi
        blocked = verify('222222')
        check('bloklangan kod bilan kirib bo\'lmadi',
              blocked.status_code == 429, blocked.status_code)
        check('foydalanuvchi yaratilmadi',
              not User.objects.filter(username=PHONE).exists())

        # ── 3. To'g'ri kod bilan kirish ─────────────────────────
        OTPCode.objects.filter(phone=PHONE).delete()
        OTPCode.objects.create(phone=PHONE, code='333333')
        good = verify('333333')
        check('to\'g\'ri kod bilan kirildi', good.status_code == 200, good.status_code)
        check('token qaytdi', 'access' in good.json() and 'refresh' in good.json())
        check('kod ishlatilgan deb belgilandi',
              OTPCode.objects.get(phone=PHONE).is_used)

        # ── 4. Token yangilash ──────────────────────────────────
        tokens = good.json()
        refreshed = Client().post('/api/auth/token/refresh/',
                                  {'refresh': tokens['refresh']},
                                  content_type='application/json')
        check('token yangilandi',
              refreshed.status_code == 200 and 'access' in refreshed.json(),
              refreshed.status_code)
        bad = Client().post('/api/auth/token/refresh/', {'refresh': 'yolgon'},
                            content_type='application/json')
        check('yaroqsiz token rad etildi', bad.status_code == 401, bad.status_code)

        # ── 5. Panel sessiyasining muddati ──────────────────────
        staff = User.objects.create_user(username='__sc_admin__', password='sinov-parol-1',
                                         is_staff=True)
        panel = Client()
        panel.post('/login/', {'username': '__sc_admin__', 'password': 'sinov-parol-1'})
        age = panel.session.get_expiry_age()
        check('sessiya muddati sozlamadan qo\'yildi',
              1700 < age <= 1800, age)

        settings_obj.session_timeout_minutes = 120
        settings_obj.save(update_fields=['session_timeout_minutes'])
        panel2 = Client()
        panel2.post('/login/', {'username': '__sc_admin__', 'password': 'sinov-parol-1'})
        check('o\'zgartirilgan muddat ham qo\'llandi',
              panel2.session.get_expiry_age() > 7000, panel2.session.get_expiry_age())
        staff.delete()

        # ── 6. Panel darajalari ────────────────────────────────
        # Ilgari `is_staff` bo'lgan har kim sozlamalarni ham, hamkorga
        # to'lovni ham o'zgartira olardi: «Rollar» bo'limi bor edi-yu,
        # hech qayerda tekshirilmasdi
        manager = User.objects.create_user(username='__sc_menejer__',
                                           password='sinov-parol-2', is_staff=True)
        admin = User.objects.create_user(username='__sc_admin2__',
                                         password='sinov-parol-3',
                                         is_staff=True, is_superuser=True)

        as_manager, as_admin = Client(), Client()
        as_manager.force_login(manager)
        as_admin.force_login(admin)

        closed = ['/settings/general/', '/settings/providers/', '/payouts/',
                  '/managers/', '/roles/']
        blocked = [url for url in closed if as_manager.get(url).status_code == 403]
        check('menejerga sozlama va hisob-kitob yopiq',
              len(blocked) == len(closed), set(closed) - set(blocked))

        allowed = [url for url in closed if as_admin.get(url).status_code == 200]
        check('administratorga ochiq', len(allowed) == len(closed),
              set(closed) - set(allowed))

        # Kundalik ish menejerga ochiq qolishi kerak
        daily = ['/stations/', '/sessions/', '/rfid/', '/companies/', '/maintenance/']
        open_pages = [url for url in daily if as_manager.get(url).status_code == 200]
        check("kundalik bo'limlar menejerga ochiq",
              len(open_pages) == len(daily), set(daily) - set(open_pages))

        # Yozish amallari ham yopiq: ko'rinishni yashirish yetarli emas
        write = as_manager.post('/settings/general/',
                                {'section': 'app', 'app_name': 'menejer yozdi'})
        check('menejer sozlamani saqlay olmadi', write.status_code == 403,
              write.status_code)

        menu = as_manager.get('/stations/').content.decode('utf-8')
        check("yopiq bo'limlar menyuda ko'rinmadi",
              '/settings/general/' not in menu and '/payouts/' not in menu)

        manager.delete()
        admin.delete()

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
