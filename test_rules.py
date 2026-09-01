# -*- coding: utf-8 -*-
"""Zaryadlash qoidalari: sozlamalardagi cheklovlar HAQIQATAN qo'llanadimi.

Ilgari bu cheklovlar faqat sozlamalar sahifasida turardi — operator ularni
belgilardi, tizim esa qaramasdi. Panelda bor, lekin ishlamaydigan sozlama
eng yomon holat: operator himoya bor deb o'ylaydi.

Asosiy savollar:
  1. Minimal balans chegarasi ishlaydimi (karta, ilova va panelda bir xil)?
  2. Ish vaqti tashqarisida sessiya boshlanmaydimi, tunga o'tuvchi jadval
     ham to'g'ri hisoblanadimi?
  3. Vaqt chegarasidan oshgan sessiya topilib, to'xtatiladimi?
  4. Parkovka imtiyoz vaqti chegirib tashlanadimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import time as dtime, timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from management.models import Holiday, SiteSettings, UserNotification  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Station  # noqa: E402
from stations.rules import (  # noqa: E402
    can_start, check_balance, is_working_now, overdue_sessions, parking_minutes,
)
from wallet.models import WalletBalance  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    ChargingSession.objects.filter(station__name__startswith='__rl').delete()
    UserNotification.objects.filter(user__username__startswith='__rl').delete()
    Station.objects.filter(name__startswith='__rl').delete()
    User.objects.filter(username__startswith='__rl').delete()
    Holiday.objects.filter(name__startswith='__rl').delete()


def api(user):
    client = Client()
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {RefreshToken.for_user(user).access_token}'
    return client


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {
        f: getattr(settings_obj, f)
        for f in ('min_balance_to_start', 'max_session_minutes',
                  'parking_grace_minutes', 'work_all_day', 'work_start', 'work_end')
    }
    try:
        # ── 1. Balans chegarasi ─────────────────────────────────
        settings_obj.min_balance_to_start = 10000
        settings_obj.work_all_day = True
        settings_obj.save()

        driver = User.objects.create(username='__rl_driver__')
        wallet = WalletBalance.objects.create(user=driver, amount=0)

        check('bo\'sh hamyon rad etildi', 'mablag' in (check_balance(driver) or ''))

        wallet.amount = 5000
        wallet.save(update_fields=['amount'])
        reason = check_balance(driver)
        check('chegaradan kam balans rad etildi', reason is not None, reason)
        # Pul formati ajratilmas bo'shliq ishlatadi — solishtirishdan oldin
        # oddiy bo'shliqqa keltiramiz
        plain = (reason or '').replace(' ', ' ')
        check('sabab aniq: qancha kerakligi aytildi',
              '10 000' in plain and '5 000' in plain, plain)

        wallet.amount = 15000
        wallet.save(update_fields=['amount'])
        check('yetarli balansda ruxsat berildi', check_balance(driver) is None)
        check('xizmat kartasi (egasiz) tekshiruvdan o\'tdi', check_balance(None) is None)

        # ── 2. Ish vaqti ────────────────────────────────────────
        settings_obj.work_all_day = False
        settings_obj.work_start = dtime(8, 0)
        settings_obj.work_end = dtime(22, 0)
        settings_obj.save()

        noon = timezone.localtime().replace(hour=12, minute=0)
        night = timezone.localtime().replace(hour=3, minute=0)
        check('ish vaqtida ochiq', is_working_now(now=noon)[0])
        working, why = is_working_now(now=night)
        check('ish vaqtidan tashqarida yopiq', not working)
        check('sabab soatlarni ko\'rsatdi', '08:00' in (why or '') and '22:00' in (why or ''), why)

        # Tunga o'tuvchi jadval: 22:00 → 06:00
        settings_obj.work_start = dtime(22, 0)
        settings_obj.work_end = dtime(6, 0)
        settings_obj.save()
        check('tunga o\'tuvchi jadval: kechasi ochiq', is_working_now(now=night)[0])
        check('tunga o\'tuvchi jadval: kunduzi yopiq', not is_working_now(now=noon)[0])

        # Bayram kuni sabab matnida ko'rinadi
        Holiday.objects.update_or_create(
            date=timezone.localdate(),
            defaults={'name': '__rl Mustaqillik kuni', 'source': Holiday.Source.MANUAL})
        # Oyna HOZIRGI paytdan ikki soat keyin boshlanadi: shunda u
        # hech qachon hozirni ichiga olmaydi. Ilgari bu yerda aniq
        # 08:00–09:00 turardi va sinov o'sha soatda ishga tushsa
        # yiqilardi — soatiga bir marta. Bunday sinov yo'qdan ham
        # yomon: unga ishonch qolmaydi.
        closed_start = (timezone.localtime() + timedelta(hours=2)).time()
        closed_end = (timezone.localtime() + timedelta(hours=3)).time()
        settings_obj.work_start = closed_start.replace(second=0, microsecond=0)
        settings_obj.work_end = closed_end.replace(second=0, microsecond=0)
        settings_obj.save()
        blocked = can_start(driver)
        check('bayram kuni sababda aytildi', '__rl Mustaqillik kuni' in (blocked or ''), blocked)
        Holiday.objects.filter(name__startswith='__rl').delete()

        # ── 3. Mobil ilova ham shu qoidaga bo'ysunadi ───────────
        station = Station.objects.create(
            name='__rl Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='dc', power_kw=60,
        )
        connector = Connector.objects.create(
            station=station, label='A', type='ccs2', power_kw=60,
            status=Connector.Status.AVAILABLE)

        response = api(driver).post('/api/sessions/start/',
                                    {'stationId': station.id}, content_type='application/json')
        check('ilova ish vaqtidan tashqarida boshlamadi',
              response.status_code == 400, response.status_code)
        check('ilovaga sabab qaytdi',
              'ishlaydi' in response.json().get('detail', ''), response.json())

        settings_obj.work_all_day = True
        settings_obj.min_balance_to_start = 100000
        settings_obj.save()
        response = api(driver).post('/api/sessions/start/',
                                    {'stationId': station.id}, content_type='application/json')
        check('ilova balans yetmasa boshlamadi',
              response.status_code == 400 and 'kerak' in response.json().get('detail', ''),
              response.json())

        settings_obj.min_balance_to_start = 0
        settings_obj.save()

        # ── 4. Vaqt chegarasi ───────────────────────────────────
        session = ChargingSession.objects.create(
            user=driver, station=station, connector=connector,
            power_kw=60, price_per_kwh=1200, connector_label='A',
            start_percent=20,
        )
        ChargingSession.objects.filter(pk=session.pk).update(
            started_at=timezone.now() - timedelta(minutes=200))

        settings_obj.max_session_minutes = 0
        settings_obj.save(update_fields=['max_session_minutes'])
        check('chegara 0 bo\'lsa hech narsa topilmadi', overdue_sessions().count() == 0)

        settings_obj.max_session_minutes = 120
        settings_obj.save(update_fields=['max_session_minutes'])
        check('chegaradan oshgan sessiya topildi',
              overdue_sessions().filter(pk=session.pk).exists())

        from django.core.management import call_command
        from io import StringIO

        call_command('stop_overdue', stdout=StringIO(), stderr=StringIO())
        session.refresh_from_db()
        check('sessiya to\'xtatildi',
              session.status == ChargingSession.Status.STOPPED, session.status)
        check('to\'xtatish sababi yozildi',
              'chegara' in (session.stop_reason or '').lower(), session.stop_reason)
        check('foydalanuvchi xabardor qilindi',
              UserNotification.objects.filter(user=driver).exists())

        # ── 5. Parkovka imtiyozi ────────────────────────────────
        settings_obj.parking_grace_minutes = 10
        settings_obj.save(update_fields=['parking_grace_minutes'])
        since = timezone.now() - timedelta(minutes=8)
        check('imtiyoz ichida daqiqa hisoblanmadi', parking_minutes(since) == 0)
        since = timezone.now() - timedelta(minutes=25)
        check('imtiyozdan keyingi daqiqalar hisoblandi',
              parking_minutes(since) == 15, parking_minutes(since))
        check('parkovkasiz holat nol', parking_minutes(None) == 0)

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
