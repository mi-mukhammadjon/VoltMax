# -*- coding: utf-8 -*-
"""Elektron pochta: hujjatlar, ogohlantirish va parolni tiklash.

Uch ish uchun kerak edi va uchalasi ham qo'l mehnati bo'lib turgan edi:

  * korporativ hujjatni operator yuklab olib, qo'lda yuborardi — oy
    oxirida o'nlab mijoz uchun bu bir necha soat va bittasini unutish
    oson;
  * tizimdagi muammoni faqat panelga kirgan odam ko'rardi;
  * parolni faqat serverdan tiklash mumkin edi (`changepassword`).

Sinov tarmoqqa CHIQMAYDI: SMTP javoblari almashtiriladi.

Asosiy savollar:
  1. Sozlanmagan pochta asosiy ishni to'xtatib qo'yadimi (qo'ymasligi
     kerak — hujjat baribir yaratiladi)?
  2. Ogohlantirish SPAM qilmaydimi — faqat o'zgarish haqida yoziladimi?
  3. Pochta ishlamaganda ogohlantirish holati "yuborildi" deb
     belgilanmaydimi?
  4. Parolni tiklash havolasi bir marta ishlaydimi?
  5. Tiklash sahifasi manzil ro'yxatda borligini oshkor qiladimi?
"""
import os
import time

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from unittest.mock import patch  # noqa: E402

from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.auth.tokens import default_token_generator  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils.encoding import force_bytes  # noqa: E402
from django.utils.http import urlsafe_base64_encode  # noqa: E402

from management import alerts, mail  # noqa: E402
from management.jobs import JobStatus  # noqa: E402
from management.models import SiteSettings  # noqa: E402

failures = 0

LOGIN = '__ml_xodim__'
EMAIL = 'xodim@voltmax.uz'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    JobStatus.objects.filter(name=alerts.STATE_KEY).delete()
    User.objects.filter(username__startswith='__ml').delete()


def report(down_keys):
    """Soxta holat hisoboti."""
    checks = [{'key': key, 'title': f'Tekshiruv {key}', 'state': 'down',
               'value': 'yo\'q', 'hint': 'sinov'} for key in down_keys]
    return {'checks': checks, 'down': checks, 'warn': [],
            'overall': 'down' if checks else 'ok', 'checked_at': None}


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f)
             for f in ('mail_enabled', 'mail_host', 'mail_from', 'mail_user',
                       'mail_password', 'mail_alerts_to')}
    try:
        # ── 1. Sozlanmagan pochta ───────────────────────────────
        settings_obj.mail_enabled = False
        settings_obj.save()
        check('sozlanmagan deb topildi', not mail.is_configured())

        ok, reason = mail.try_send('a@b.uz', 'mavzu', 'matn')
        check('sozlanmaganda xato TASHLANMADI', ok is False and reason,
              reason)

        settings_obj.mail_enabled = True
        settings_obj.mail_host = 'smtp.sinov.uz'
        settings_obj.mail_from = 'VoltMax <bot@voltmax.uz>'
        settings_obj.mail_alerts_to = 'admin@voltmax.uz, texnik@voltmax.uz'
        settings_obj.save()
        check('sozlangach topildi', mail.is_configured())

        # ── 2. Manzil tekshiruvi ────────────────────────────────
        check('yaroqli manzil qabul qilindi', mail.valid_address('a@b.uz'))
        check('yaroqsiz manzil rad etildi',
              not mail.valid_address('salom') and not mail.valid_address('a@b'))

        with patch('django.core.mail.EmailMessage.send', return_value=1):
            ok, _ = mail.try_send(['a@b.uz', 'buzuq'], 'mavzu', 'matn')
            check('yaroqsiz manzil o\'tkazib yuborildi', ok)

        with patch('django.core.mail.EmailMessage.send', return_value=1):
            ok, reason = mail.try_send('buzuq', 'mavzu', 'matn')
            check('birorta yaroqli manzil bo\'lmasa yuborilmadi',
                  not ok, reason)

        # SMTP yiqilsa ham xato tashlanmaydi
        with patch('django.core.mail.EmailMessage.send',
                   side_effect=OSError('ulanib bo\'lmadi')):
            ok, reason = mail.try_send('a@b.uz', 'mavzu', 'matn')
            check('SMTP yiqilganda ish to\'xtamadi', not ok and 'ulanib' in reason,
                  reason)

        # ── 3. Ogohlantirish faqat O'ZGARISHDA ──────────────────
        JobStatus.objects.filter(name=alerts.STATE_KEY).delete()

        with patch('management.health.collect', return_value=report(['job:push'])), \
             patch('management.mail.try_send', return_value=(True, '')) as sent:
            fired, note = alerts.check_and_notify()
            check('birinchi muammoda xabar ketdi', fired, note)
            check('manzillar to\'g\'ri', sent.call_args[0][0] ==
                  ['admin@voltmax.uz', 'texnik@voltmax.uz'], sent.call_args[0][0])
            check('mavzuda muammolar soni bor',
                  '1 ta muammo' in sent.call_args[0][1], sent.call_args[0][1])

        # Ayni muammo davom etsa — QAYTA yozilmaydi, aks holda pochta
        # spamga aylanib, e'tibordan chiqardi
        with patch('management.health.collect', return_value=report(['job:push'])), \
             patch('management.mail.try_send', return_value=(True, '')) as sent:
            fired, _ = alerts.check_and_notify()
            check('o\'zgarish bo\'lmasa xabar ketmadi',
                  not fired and not sent.called)

        # Yangi muammo qo'shilsa — yoziladi
        with patch('management.health.collect',
                   return_value=report(['job:push', 'payments'])), \
             patch('management.mail.try_send', return_value=(True, '')) as sent:
            fired, _ = alerts.check_and_notify()
            check('yangi muammo haqida xabar ketdi', fired)
            check('xatda faqat YANGI muammo ajratilgan',
                  'YANGI MUAMMO' in sent.call_args[0][2]
                  and 'Hali ham ochiq' in sent.call_args[0][2])

        # Tuzalganda ham xabar keladi
        with patch('management.health.collect', return_value=report([])), \
             patch('management.mail.try_send', return_value=(True, '')) as sent:
            fired, _ = alerts.check_and_notify()
            check('tuzalgani haqida xabar ketdi', fired)
            check('mavzu tuzalganini aytdi',
                  'tuzaldi' in sent.call_args[0][1], sent.call_args[0][1])

        # ── 4. Pochta ishlamasa holat SAQLANMAYDI ───────────────
        # Aks holda o'sha muammo haqida hech qachon xabar kelmasdi
        JobStatus.objects.filter(name=alerts.STATE_KEY).delete()
        with patch('management.health.collect', return_value=report(['ocpp'])), \
             patch('management.mail.try_send', return_value=(False, 'smtp yiqildi')):
            fired, _ = alerts.check_and_notify()
            check('yuborilmagan xabar "yuborildi" deb belgilanmadi', not fired)

        with patch('management.health.collect', return_value=report(['ocpp'])), \
             patch('management.mail.try_send', return_value=(True, '')) as sent:
            fired, _ = alerts.check_and_notify()
            check('pochta tiklangach xabar ketdi', fired and sent.called)

        # ── 5. Parolni tiklash ──────────────────────────────────
        user = User.objects.create_user(username=LOGIN, password='QuyoshliKun-92',
                                        email=EMAIL, is_staff=True)
        client = Client()

        with patch('management.mail.try_send', return_value=(True, '')) as sent:
            known = client.post('/parol/tiklash/', {'email': EMAIL})
            check('havola yuborildi',
                  sent.called and '/parol/tiklash/' in sent.call_args[0][2])

        with patch('management.mail.try_send', return_value=(True, '')) as sent:
            unknown = client.post('/parol/tiklash/', {'email': 'yoq@voltmax.uz'})
            check('noma\'lum manzilga xat ketmadi', not sent.called)

        # Javob IKKALA holatda bir xil: aks holda bu sahifa "kim xodim
        # ekan" degan savolga javob beradigan vositaga aylanardi
        check('javob bir xil (manzil oshkor bo\'lmadi)',
              known.content == unknown.content)

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        page = client.get(f'/parol/tiklash/{uid}/{token}/')
        check('tiklash sahifasi ochildi', page.status_code == 200)

        weak = client.post(f'/parol/tiklash/{uid}/{token}/',
                           {'new_password': 'voltmax2026',
                            'confirm_password': 'voltmax2026'})
        user.refresh_from_db()
        check('zaif parol rad etildi', not user.check_password('voltmax2026'))

        mismatch = client.post(f'/parol/tiklash/{uid}/{token}/',
                               {'new_password': 'BirinchiParol-77',
                                'confirm_password': 'Boshqasi-88'})
        user.refresh_from_db()
        check('mos kelmagan parollar rad etildi',
              not user.check_password('BirinchiParol-77'))

        client.post(f'/parol/tiklash/{uid}/{token}/',
                    {'new_password': 'YangiKuchli-2026',
                     'confirm_password': 'YangiKuchli-2026'})
        user.refresh_from_db()
        check('parol yangilandi', user.check_password('YangiKuchli-2026'))

        # Havola BIR MARTA ishlaydi: token parol hash'iga bog'langan
        again = client.get(f'/parol/tiklash/{uid}/{token}/')
        check('havola ikkinchi marta ishlamadi',
              'yaroqsiz' in again.content.decode('utf-8').lower())

        broken = client.get('/parol/tiklash/xxx/yyy-zzz/')
        check('buzuq havola ham xato bermadi', broken.status_code == 200)

        # ── 6. Havola muddati ───────────────────────────────────
        # Django ning standarti UCH KUN. Panel butun tarmoqni
        # boshqaradi, xat esa pochtada qolib ketishi mumkin — uch kun
        # juda uzoq. Ilgari o'zgarmas faqat XATDAGI MATNDA ishlatilardi:
        # xat "2 soat" der, havola esa uch kun ishlayverardi.
        check('muddat ikki soatga qisqartirilgan',
              settings.PASSWORD_RESET_TIMEOUT == 2 * 3600,
              settings.PASSWORD_RESET_TIMEOUT)

        fresh = default_token_generator.make_token(user)
        with override_settings(PASSWORD_RESET_TIMEOUT=2):
            time.sleep(3.5)
            stale = client.get(f'/parol/tiklash/{uid}/{fresh}/')
            check("muddat o'tgach havola yaroqsiz",
                  'yaroqsiz' in stale.content.decode('utf-8').lower())

        # ── 7. Bir xil pochtali ikki hisob ──────────────────────
        # Django'da pochta NOYOB EMAS. Ilgari `.first()` olinardi va
        # qaysi hisob tanlanishi tasodifga bog'liq edi — odam kutgan
        # hisobi o'rniga boshqasining havolasini olardi.
        shared = 'ofis@voltmax.uz'
        User.objects.filter(username__startswith='__ml_ofis').delete()
        one = User.objects.create_user(username='__ml_ofis_a__', email=shared,
                                       password='QuyoshliKun-92', is_staff=True)
        two = User.objects.create_user(username='__ml_ofis_b__', email=shared,
                                       password='QuyoshliKun-92', is_staff=True)

        with patch('management.mail.try_send', return_value=(True, '')) as sent:
            Client().post('/parol/tiklash/', {'email': shared})
            check('har ikkala hisobga ham havola ketdi',
                  sent.call_count == 2, sent.call_count)
            bodies = ' '.join(call[0][2] for call in sent.call_args_list)
            check('xatda qaysi hisob ekani aytildi',
                  one.username in bodies and two.username in bodies)

        one.delete()
        two.delete()

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
