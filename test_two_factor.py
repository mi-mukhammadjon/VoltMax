# -*- coding: utf-8 -*-
"""Ikki bosqichli kirish (TOTP).

Parol qanchalik kuchli bo'lmasin, u BITTA to'siq: oshkor bo'lsa
(fishing, qayta ishlatilgan parol, zararli dastur) boshqa hech narsa
qolmaydi. Panel esa butun tarmoqni, hamma hamyonni va to'lov kalitlarini
boshqaradi.

Bu sinovning eng muhim savoli oddiy: parolni bilgan, lekin telefoni
yo'q odam BIRORTA sahifani ocha oladimi? Agar ocha olsa, ikkinchi to'siq
bezak bo'lib qoladi.

Asosiy savollar:
  1. Algoritm to'g'rimi (RFC 6238) va soat farqiga yon beradimi?
  2. Kod so'ralganda foydalanuvchi HALI kirmagan bo'ladimi?
  3. Noto'g'ri kod urinishlari chegaraga tushadimi?
  4. Zaxira kodi bir marta ishlaydimi va bazada ochiq saqlanmaydimi?
  5. Tasdiqlanmagan sozlama kirishni to'sib qo'ymaydimi?
  6. Majburiy qilingan hisob uni o'chira oladimi (o'chira olmasligi kerak)?
"""
import os
import time

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from management import totp  # noqa: E402
from management.login_guard import LoginAttempt  # noqa: E402
from management.models import SiteSettings  # noqa: E402
from management.totp import TwoFactor  # noqa: E402

failures = 0

LOGIN = '__tf_admin__'
PASSWORD = 'QuyoshliKun-92-Chorsu'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    LoginAttempt.objects.filter(username__startswith='__tf').delete()
    User.objects.filter(username__startswith='__tf').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f)
             for f in ('require_2fa_for_admins', 'panel_max_attempts')}
    try:
        settings_obj.require_2fa_for_admins = False
        settings_obj.panel_max_attempts = 5
        settings_obj.save()

        # ── 1. Algoritm ─────────────────────────────────────────
        secret = totp.new_secret()
        now = time.time()
        check('kod olti xonali',
              len(totp.current_code(secret)) == 6, totp.current_code(secret))
        check('to\'g\'ri kod qabul qilindi',
              totp.verify(secret, totp.current_code(secret)))
        check('30 soniya oldingi kod ham qabul qilindi',
              totp.verify(secret, totp.current_code(secret, now - 30)))
        check('ikki daqiqa oldingisi rad etildi',
              not totp.verify(secret, totp.current_code(secret, now - 120)))
        check('bo\'sh va harfli kod rad etildi',
              not totp.verify(secret, '') and not totp.verify(secret, 'abcdef'))
        check('boshqa kalitning kodi rad etildi',
              not totp.verify(secret, totp.current_code(totp.new_secret())))

        # ── 2. Kirish oqimi ─────────────────────────────────────
        user = User.objects.create_user(username=LOGIN, password=PASSWORD,
                                        is_staff=True, is_superuser=True)
        second = TwoFactor.objects.create(user=user, secret=totp.new_secret())

        # Tasdiqlanmagan sozlama kirishga TEGMASLIGI kerak: aks holda
        # kalit yaratib, ilovaga qo'shmagan odam o'z panelidan chiqib
        # qolardi
        client = Client()
        entered = client.post('/login/', {'username': LOGIN, 'password': PASSWORD})
        check('tasdiqlanmagan sozlama kirishni to\'smadi',
              entered.status_code == 302 and entered.url == '/', entered.status_code)
        client.get('/logout/')

        second.confirmed_at = timezone.now()
        second.set_backup_codes()
        backup_codes = second.set_backup_codes()
        second.save()

        client = Client()
        step = client.post('/login/', {'username': LOGIN, 'password': PASSWORD})
        check('parol to\'g\'ri bo\'lgach kod so\'raldi',
              step.status_code == 302 and '2fa' in step.url, step.get('Location'))

        # ENG MUHIM: bu bosqichda foydalanuvchi hali KIRMAGAN bo'lishi kerak
        check('kod bosqichida panel ochilmadi',
              client.get('/stations/').status_code in (301, 302),
              client.get('/stations/').status_code)
        check('bosh sahifa ham ochilmadi',
              client.get('/').status_code in (301, 302))

        wrong = client.post('/login/2fa/', {'code': '000000'})
        check('noto\'g\'ri kod rad etildi',
              wrong.status_code == 200 and 'noto' in wrong.content.decode('utf-8'))
        check('noto\'g\'ri kod hisobga yozildi',
              LoginAttempt.objects.filter(username=LOGIN, successful=False).exists())

        good = client.post('/login/2fa/', {'code': totp.current_code(second.secret)})
        check('to\'g\'ri kod bilan kirildi',
              good.status_code == 302 and good.url == '/', good.status_code)
        check('endi panel ochildi', client.get('/stations/').status_code == 200)

        # ── 3. Zaxira kodi ──────────────────────────────────────
        client.get('/logout/')
        client = Client()
        client.post('/login/', {'username': LOGIN, 'password': PASSWORD})
        used = backup_codes[0]
        entered = client.post('/login/2fa/', {'code': used})
        check('zaxira kodi bilan kirildi', entered.status_code == 302,
              entered.status_code)

        second.refresh_from_db()
        check('ishlatilgan zaxira kodi ro\'yxatdan chiqdi',
              second.backup_left == len(backup_codes) - 1, second.backup_left)

        client.get('/logout/')
        client = Client()
        client.post('/login/', {'username': LOGIN, 'password': PASSWORD})
        again = client.post('/login/2fa/', {'code': used})
        check('o\'sha zaxira kodi ikkinchi marta ishlamadi',
              again.status_code == 200)

        # Kodlar bazada OCHIQ saqlanmaydi: baza oshkor bo'lsa ular
        # parolga teng bo'lardi
        second.refresh_from_db()
        check('zaxira kodlari ochiq saqlanmadi',
              all(code not in str(second.backup_hashes) for code in backup_codes))

        # ── 4. Kod ham tanlanmaydi ──────────────────────────────
        LoginAttempt.objects.filter(username=LOGIN).delete()
        client = Client()
        client.post('/login/', {'username': LOGIN, 'password': PASSWORD})
        blocked = False
        for _ in range(7):
            page = client.post('/login/2fa/', {'code': '111111'})
            if 'chegara' in page.content.decode('utf-8').lower():
                blocked = True
                break
        check('kod tanlash ham to\'sildi', blocked)

        # ── 5. Majburiy rejim ───────────────────────────────────
        LoginAttempt.objects.filter(username=LOGIN).delete()
        settings_obj.require_2fa_for_admins = True
        settings_obj.save()

        from management.totp import required_for

        check('administrator uchun majburiy', required_for(user))

        manager = User.objects.create_user(username='__tf_menejer__',
                                           password=PASSWORD, is_staff=True)
        check('menejer uchun ixtiyoriy', not required_for(manager))

        client = Client()
        client.post('/login/', {'username': LOGIN, 'password': PASSWORD})
        client.post('/login/2fa/', {'code': totp.current_code(second.secret)})
        off = client.post('/profile/2fa/disable/',
                          {'code': totp.current_code(second.secret)})
        second.refresh_from_db()
        check('majburiy rejimda o\'chirib bo\'lmadi',
              TwoFactor.objects.filter(user=user).exists(), off.status_code)

        settings_obj.require_2fa_for_admins = False
        settings_obj.save()

        # ── 6. O'chirish faqat kod bilan ────────────────────────
        wrong_off = client.post('/profile/2fa/disable/', {'code': '000000'})
        check('kodsiz o\'chirib bo\'lmadi',
              TwoFactor.objects.filter(user=user).exists(), wrong_off.status_code)

        client.post('/profile/2fa/disable/',
                    {'code': totp.current_code(second.secret)})
        check('to\'g\'ri kod bilan o\'chirildi',
              not TwoFactor.objects.filter(user=user).exists())

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
