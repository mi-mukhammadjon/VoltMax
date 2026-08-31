# -*- coding: utf-8 -*-
"""Majburan uzish va holat sinxronlashni tekshiradi.

OCPP buyrug'i haqiqatan yuborilayotganini tekshirish uchun
`ocpp_commands.remote_stop_transaction` vaqtincha almashtiriladi (spy).
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from ocpp_gateway import commands as ocpp_commands  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Station  # noqa: E402
from stations.services import sync_all, sync_station_status  # noqa: E402
from wallet.models import WalletBalance  # noqa: E402

sent = []


def spy_remote_stop(ocpp_id, transaction_id):
    sent.append((ocpp_id, transaction_id))


def setup():
    admin, _ = User.objects.get_or_create(
        username='__sync_admin__', defaults={'is_staff': True, 'is_superuser': True}
    )
    admin.is_staff = admin.is_superuser = True
    admin.save()

    driver, _ = User.objects.get_or_create(username='__sync_driver__')
    WalletBalance.objects.update_or_create(user=driver, defaults={'amount': 300000})

    station = Station.objects.create(
        name='__sync_station__', address='test', latitude=41.0, longitude=69.0,
        power_kw=60, discount_price_per_kwh=1000, status=Station.Status.AVAILABLE,
        ocpp_id='__SYNC_CP__', ocpp_last_seen_at=timezone.now(),
    )
    connector = Connector.objects.create(
        station=station, label='A', type='DC', power_kw=60, ocpp_connector_id=1
    )
    return admin, driver, station, connector


def teardown(admin, driver, station):
    ChargingSession.objects.filter(station=station).delete()
    station.delete()
    driver.delete()
    admin.delete()


def main():
    ocpp_commands.remote_stop_transaction = spy_remote_stop
    import sessions_app.services as svc
    svc.ocpp_commands.remote_stop_transaction = spy_remote_stop

    admin, driver, station, connector = setup()
    ok = True

    def check(label, condition, extra=''):
        nonlocal ok
        print(f'{"OK  " if condition else "XATO"}  {label} {extra}')
        ok = ok and condition

    with override_settings(ALLOWED_HOSTS=['testserver']):
        client = Client()
        client.force_login(admin)

        # ── 1. Jonli sessiya boshlanadi ───────────────────────
        session = ChargingSession.objects.create(
            user=driver, station=station, connector=connector, start_percent=20,
            power_kw=60, price_per_kwh=1000, connector_label='A', is_live=True,
            meter_start_wh=0, live_meter_wh=5000,
        )
        connector.status = Connector.Status.CHARGING
        connector.save(update_fields=['status'])
        station.refresh_from_db()
        check('sessiya boshlanganda stansiya "band" bo\'ldi',
              station.status == Station.Status.BUSY, f'({station.status})')

        # ── 2. Panel orqali majburan uzish ────────────────────
        sent.clear()
        response = client.post(f'/sessions/{session.id}/stop/')
        session.refresh_from_db()
        connector.refresh_from_db()
        station.refresh_from_db()

        check('so\'rov qabul qilindi', response.status_code in (200, 302))
        check('chargerga RemoteStopTransaction yuborildi',
              sent == [('__SYNC_CP__', session.id)], f'-> {sent}')
        check('sessiya DB\'da yopildi', session.status == ChargingSession.Status.STOPPED,
              f'({session.status})')
        check('ulagich bo\'shadi', connector.status == Connector.Status.AVAILABLE,
              f'({connector.status})')
        check('stansiya "bo\'sh"ga qaytdi', station.status == Station.Status.AVAILABLE,
              f'({station.status})')
        check('hamyondan pul yechildi',
              WalletBalance.objects.get(user=driver).amount < 300000)

        # ── 3. Charger keyin StopTransaction yuborsa — ikki marta yechilmasin ──
        balance_after = WalletBalance.objects.get(user=driver).amount
        session.stop()  # takroriy chaqiruv (charger javobi kelgandek)
        check('takroriy to\'xtatishda pul ikki marta yechilmadi',
              WalletBalance.objects.get(user=driver).amount == balance_after)

        # ── 4. Nomuvofiqlikni sinxronlash ─────────────────────
        connector.status = Connector.Status.CHARGING   # sessiyasiz "zaryadlanmoqda"
        connector.save(update_fields=['status'])
        result = sync_all()
        connector.refresh_from_db()
        check('sessiyasiz "zaryadlanmoqda" ulagich bo\'shatildi',
              connector.status == Connector.Status.AVAILABLE, f'({result})')

        # ── 5. Charger oflayn bo'lsa ──────────────────────────
        station.ocpp_last_seen_at = timezone.now() - timezone.timedelta(hours=2)
        station.save(update_fields=['ocpp_last_seen_at'])
        session2 = ChargingSession.objects.create(
            user=driver, station=station, connector=connector, start_percent=10,
            power_kw=60, price_per_kwh=1000, connector_label='A', is_live=True,
            meter_start_wh=0, live_meter_wh=1000,
        )
        sent.clear()
        from sessions_app.services import force_stop_session
        res = force_stop_session(session2)
        check('oflayn chargerga buyruq yuborilmadi', sent == [])
        check('operatorga ogohlantirish qaytdi', bool(res.warning), f'-> "{res.warning[:45]}..."')
        check('sessiya baribir hisobda yopildi', res.stopped)

        # ── 6. Ulagich orqali uzish ───────────────────────────
        station.ocpp_last_seen_at = timezone.now()
        station.save(update_fields=['ocpp_last_seen_at'])
        session3 = ChargingSession.objects.create(
            user=driver, station=station, connector=connector, start_percent=10,
            power_kw=60, price_per_kwh=1000, connector_label='A', is_live=True,
            meter_start_wh=0, live_meter_wh=1000,
        )
        connector.status = Connector.Status.CHARGING
        connector.save(update_fields=['status'])
        sent.clear()
        client.post(f'/stations/{station.id}/connectors/{connector.id}/remote-stop/')
        session3.refresh_from_db()
        connector.refresh_from_db()
        check('ulagichdan uzishda ham buyruq ketdi', sent == [('__SYNC_CP__', session3.id)], f'-> {sent}')
        check('sessiya yopildi', session3.status == ChargingSession.Status.STOPPED)
        check('ulagich bo\'shadi', connector.status == Connector.Status.AVAILABLE)

    teardown(admin, driver, station)
    print('\n' + ('HAMMASI OK' if ok else '*** XATOLAR BOR ***'))


if __name__ == '__main__':
    main()
