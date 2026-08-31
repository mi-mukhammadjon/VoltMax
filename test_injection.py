# -*- coding: utf-8 -*-
"""Uchta kamchilik: soxta idTag, CSV formulasi va ochiq yo'naltirish.

Uchalasi ham bir turdagi xato: TASHQARIDAN kelgan ma'lumotga so'roqsiz
ishonish.

  1. `APP-<id>` — charger yuborgan idTag ilgari so'roqsiz qabul
     qilinardi. Foydalanuvchi raqamlari ketma-ket, ya'ni taxmin qilsa
     bo'ladi: buzilgan yoki yomon niyatli charger `APP-5` yuborib,
     BEGONA odamning hamyonidan pul yechishi mumkin edi.
  2. CSV — Excel `=`, `+`, `@` bilan boshlangan katakni formula deb
     o'qiydi. Bizning telefon raqamimiz `+998 (90) ...` ko'rinishida,
     ya'ni oddiy eksport ham noto'g'ri chiqardi.
  3. `next` — «qayerga qaytish» manzili foydalanuvchidan keladi va
     tekshirilmasdi: bizning domendagi havola begona saytga olib
     borishi mumkin edi.

Asosiy savollar:
  1. Tasdiqlanmagan idTag begona hisobga pul yozadimi?
  2. Haqiqiy oqim (ilova so'ragan) ishlayveradimi?
  3. Xavfli katak CSV'da zararsizlantiriladimi va son buzilmaydimi?
  4. Tashqi manzilga yo'naltirish rad etiladimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from asgiref.sync import async_to_sync  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.test import Client, RequestFactory  # noqa: E402
from django.test.utils import override_settings  # noqa: E402

from dashboard.exports import safe_cell  # noqa: E402
from dashboard.redirects import safe_redirect  # noqa: E402
from ocpp_gateway.consumers import OCPPConsumer  # noqa: E402
from sessions_app.models import ChargingSession, RemoteStartIntent  # noqa: E402
from stations.models import ChargerLog, Connector, Station  # noqa: E402
from wallet.models import WalletBalance  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    ChargingSession.objects.filter(station__name__startswith='__inj').delete()
    Station.objects.filter(name__startswith='__inj').delete()
    User.objects.filter(username__startswith='__inj').delete()
    User.objects.filter(username__startswith='APP-').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    try:
        # ── 1. Soxta idTag ──────────────────────────────────────
        victim = User.objects.create(username='__inj_qurbon__')
        WalletBalance.objects.create(user=victim, amount=500_000)

        station = Station.objects.create(
            name='__inj Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='DC', power_kw=60, ocpp_id='__INJ_CP__',
            ocpp_password='parol')
        Connector.objects.create(station=station, label='A', type='ccs2',
                                 power_kw=60, ocpp_connector_id=1)

        consumer = OCPPConsumer()
        consumer.station_id = station.id

        # Hujum: charger begona odamning raqamini yuboradi
        session = async_to_sync(consumer._start_live_session)(
            1, f'APP-{victim.id}', 0)
        check('tasdiqlanmagan idTag qurbonga yozilmadi',
              session.user_id != victim.id, session.user.username)
        check('ogohlantirish yozildi',
              ChargerLog.objects.filter(
                  station=station, summary__startswith='Tasdiqlanmagan').exists())

        wallet = WalletBalance.objects.get(user=victim)
        check('qurbonning balansi tegilmadi', wallet.amount == 500_000,
              wallet.amount)
        ChargingSession.objects.filter(pk=session.pk).delete()

        # Haqiqiy oqim: ilova avval so'rov qoldirgan
        RemoteStartIntent.remember(victim, station, 'BAHOR')
        session = async_to_sync(consumer._start_live_session)(
            1, f'APP-{victim.id}', 0)
        check('ilova so\'ragan sessiya to\'g\'ri yozildi',
              session.user_id == victim.id, session.user.username)

        # So'rov BIR MARTA ishlaydi: charger uni takrorlab, ikkinchi
        # sessiya ochib qo'ya olmasin
        check('so\'rov ishlatilgach o\'chdi',
              not RemoteStartIntent.objects.filter(user=victim).exists())
        ChargingSession.objects.filter(pk=session.pk).delete()

        # Boshqa stansiyaning so'rovi bu yerda ishlamaydi
        other = Station.objects.create(
            name='__inj Boshqa', address='b', latitude=41.1, longitude=69.1,
            charger_type='DC', power_kw=60)
        RemoteStartIntent.remember(victim, other, '')
        session = async_to_sync(consumer._start_live_session)(
            1, f'APP-{victim.id}', 0)
        check('boshqa stansiyaning so\'rovi qabul qilinmadi',
              session.user_id != victim.id, session.user.username)
        ChargingSession.objects.filter(pk=session.pk).delete()

        # ── 2. CSV formulasi ────────────────────────────────────
        dangerous = {
            '=1+1': "'=1+1",
            '+998 (90) 123-45-67': "'+998 (90) 123-45-67",
            '@SUM(A1:A9)': "'@SUM(A1:A9)",
            '-5 dan boshlab': "'-5 dan boshlab",
        }
        wrong = {value: safe_cell(value) for value, want in dangerous.items()
                 if safe_cell(value) != want}
        check('xavfli kataklar zararsizlantirildi', not wrong, wrong)

        # Oddiy matn va SONLAR tegilmasligi kerak: son matnga
        # aylantirilsa jadvalda uni yig'ib bo'lmasdi
        check('oddiy matn tegilmadi', safe_cell('Chilonzor') == 'Chilonzor')
        check('son tegilmadi', safe_cell(12000) == 12000
              and safe_cell(1.5) == 1.5, safe_cell(12000))
        check('bo\'sh qiymat tegilmadi', safe_cell(None) is None)

        # Haqiqiy eksportda ham qo'llanadimi
        admin = User.objects.filter(is_superuser=True).first()
        if admin is not None:
            panel = Client()
            panel.force_login(admin)
            body = panel.get('/reports/export/sessions/').content.decode('utf-8')
            check('eksportda formula bilan boshlangan katak yo\'q',
                  not any(line.startswith(('=', '+', '@'))
                          for line in body.splitlines()[1:]))

        # ── 3. Ochiq yo'naltirish ───────────────────────────────
        factory = RequestFactory()

        outside = ['https://evil.example/login', '//evil.example',
                   'javascript:alert(1)']
        leaked = []
        for target in outside:
            request = factory.post('/x/', {'next': target})
            response = safe_redirect(request, '/stations/')
            if response.url != '/stations/':
                leaked.append((target, response.url))
        check('tashqi manzillar rad etildi', not leaked, leaked)

        request = factory.post('/x/', {'next': '/sessions/12/'})
        check('o\'z saytimizdagi manzil ishladi',
              safe_redirect(request, '/stations/').url == '/sessions/12/')

        request = factory.post('/x/', {})
        check('manzilsiz holatda zaxira manzil ishladi',
              safe_redirect(request, '/stations/').url == '/stations/')

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
