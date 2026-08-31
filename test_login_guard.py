# -*- coding: utf-8 -*-
"""Panel loginini parol tanlashdan himoya qilish.

Mobil ilovaning OTP'si allaqachon himoyalangan edi, xodimlar logini esa
umuman ochiq turardi: cheksiz parol sinab ko'rish mumkin va urinish hech
qayerga yozilmasdi — ya'ni hujumni PAYQASHNING ham iloji yo'q edi. Panel
orqali esa butun tarmoq, hamma hamyon va to'lov kalitlari boshqariladi.

Asosiy savollar:
  1. Chegara tugagach kirish yopiladimi?
  2. Bloklangandan keyin TO'G'RI parol ham ishlamaydimi (aks holda blok
     ma'nosini yo'qotadi)?
  3. Blok boshqa xodimga yoki boshqa manzilga tarqab ketmaydimi?
  4. To'g'ri parol kiritilgach hisob nolga tushadimi?
  5. Muddat o'tgach kirish o'z-o'zidan ochiladimi?
  6. Har urinish yoziladimi — muvaffaqiyatlisi ham?
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

from management import login_guard  # noqa: E402
from management.login_guard import LoginAttempt  # noqa: E402
from management.models import SiteSettings  # noqa: E402

failures = 0

LOGIN = '__lg_operator__'
OTHER = '__lg_boshqa__'
PASSWORD = 'sinov-parol-9812'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    LoginAttempt.objects.filter(username__startswith='__lg').delete()
    User.objects.filter(username__startswith='__lg').delete()


def attempt(client, username=LOGIN, password='yolgon', ip='10.1.1.1'):
    return client.post('/login/', {'username': username, 'password': password},
                       HTTP_X_FORWARDED_FOR=ip)


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f)
             for f in ('panel_max_attempts', 'panel_lockout_minutes')}
    try:
        settings_obj.panel_max_attempts = 3
        settings_obj.panel_lockout_minutes = 15
        settings_obj.save()

        User.objects.create_user(username=LOGIN, password=PASSWORD, is_staff=True)
        User.objects.create_user(username=OTHER, password=PASSWORD, is_staff=True)

        client = Client()

        # ── 1. Chegaragacha ─────────────────────────────────────
        first = attempt(client)
        check('noto\'g\'ri parol rad etildi',
              first.status_code == 200 and b'login' in first.content.lower(),
              first.status_code)
        check('urinish yozildi',
              LoginAttempt.objects.filter(username=LOGIN, successful=False).count() == 1)
        check('manzil saqlandi',
              LoginAttempt.objects.filter(username=LOGIN).first().ip == '10.1.1.1',
              LoginAttempt.objects.filter(username=LOGIN).first().ip)

        body = attempt(client).content.decode('utf-8')
        check('qolgan urinishlar aytildi', 'urinish qoldi' in body, body[-80:])

        # ── 2. Chegara tugagach ─────────────────────────────────
        attempt(client)
        locked, minutes = login_guard.is_locked(LOGIN, '10.1.1.1')
        check('kirish bloklandi', locked, f'{minutes} daq')
        check('qolgan vaqt aytildi', 0 < minutes <= 15, minutes)

        # Bloklangandan keyin TO'G'RI parol ham ishlamasligi kerak, aks
        # holda blok faqat noto'g'ri parolni to'sadi va ma'nosini yo'qotadi
        good = attempt(client, password=PASSWORD)
        check('bloklangach to\'g\'ri parol ham o\'tmadi',
              good.status_code == 200 and 'chegara' in good.content.decode('utf-8').lower(),
              good.status_code)

        # ── 3. Blok tarqab ketmaydi ─────────────────────────────
        # Boshqa xodim shu manzildan bemalol kirishi kerak: aks holda bir
        # kishining xatosi butun ofisni ishga qo'ymay qo'yardi
        other = Client()
        entered = other.post('/login/', {'username': OTHER, 'password': PASSWORD},
                             HTTP_X_FORWARDED_FOR='10.1.1.1')
        check('boshqa xodim shu manzildan kirdi', entered.status_code == 302,
              entered.status_code)

        # O'sha login, lekin boshqa manzil — begona odam «admin» ni ataylab
        # bloklab, haqiqiy operatorni ishga qo'ymay qo'ya olmasligi kerak
        elsewhere = Client()
        entered = elsewhere.post('/login/', {'username': LOGIN, 'password': PASSWORD},
                                 HTTP_X_FORWARDED_FOR='10.2.2.2')
        check('o\'sha login boshqa manzildan kirdi', entered.status_code == 302,
              entered.status_code)

        # ── 4. Muvaffaqiyatdan keyin hisob tozalanadi ───────────
        check('muvaffaqiyat ham yozildi',
              LoginAttempt.objects.filter(username=LOGIN, successful=True).exists())
        check('yangi manzilda hisob nolga tushdi',
              login_guard.recent_failures(LOGIN, '10.2.2.2') == 0)

        # ── 5. Muddat o'tgach o'z-o'zidan ochiladi ──────────────
        LoginAttempt.objects.filter(username=LOGIN, ip='10.1.1.1').update(
            created_at=timezone.now() - timedelta(minutes=20))
        locked, _ = login_guard.is_locked(LOGIN, '10.1.1.1')
        check('muddat o\'tgach blok ochildi', not locked)

        reopened = attempt(client, password=PASSWORD)
        check('blokdan keyin kirish tiklandi', reopened.status_code == 302,
              reopened.status_code)

        # ── 6. Har urinish uzaytiradi ───────────────────────────
        # Tinmay urinish blokni faqat uzaytirishi kerak, aks holda
        # hujumchi kutib turib qayta boshlayverardi
        LoginAttempt.objects.filter(username=LOGIN).delete()
        fresh = Client()
        for _ in range(3):
            attempt(fresh, ip='10.3.3.3')
        _, before = login_guard.is_locked(LOGIN, '10.3.3.3')
        LoginAttempt.objects.filter(username=LOGIN, ip='10.3.3.3').update(
            created_at=timezone.now() - timedelta(minutes=10))
        _, shrunk = login_guard.is_locked(LOGIN, '10.3.3.3')
        check('vaqt o\'tishi bilan muddat qisqardi', shrunk < before,
              f'{before} -> {shrunk}')
        attempt(fresh, ip='10.3.3.3')
        _, after = login_guard.is_locked(LOGIN, '10.3.3.3')
        check('yangi urinish muddatni uzaytirdi', after > shrunk,
              f'{shrunk} -> {after}')

        # ── 7. Chegarani o'chirish ──────────────────────────────
        settings_obj.panel_max_attempts = 0
        settings_obj.save()
        locked, _ = login_guard.is_locked(LOGIN, '10.3.3.3')
        check('chegara 0 bo\'lsa himoya o\'chadi', not locked)
        settings_obj.panel_max_attempts = 3
        settings_obj.save()

        # ── 8. Proksi orqasidagi manzil ─────────────────────────
        # Railway'da so'rov proksi orqali keladi va `REMOTE_ADDR` har doim
        # platformaning manzili bo'ladi — hamma foydalanuvchi bitta
        # manzilda ko'rinib, blok umumiy bo'lib qolardi
        LoginAttempt.objects.filter(username=LOGIN).delete()
        Client().post('/login/', {'username': LOGIN, 'password': 'yolgon'},
                      HTTP_X_FORWARDED_FOR='203.0.113.7, 10.0.0.1')
        row = LoginAttempt.objects.filter(username=LOGIN).first()
        check('haqiqiy manzil olindi (proksi orqali)',
              row and row.ip == '203.0.113.7', row and row.ip)

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
