# -*- coding: utf-8 -*-
"""OCPP oqimi uchidan-uchiga: charger ulanishidan pul yechilishigacha.

Alohida qismlar allaqachon sinovdan o'tgan (buyruqlar, telemetriya,
qoidalar), lekin ular BIRGA ishlashi tekshirilmagan edi. Haqiqiy nosozlik
odatda qismlar orasidagi chokda bo'ladi: xabar keladi-yu, sessiya
ochilmaydi; sessiya yopiladi-yu, pul yechilmaydi.

Bu test haqiqiy WebSocket orqali boradi — routing, JSON-RPC qobig'i,
handler'lar va baza yozuvlari birga sinaladi:

    ulanish -> BootNotification -> StatusNotification -> Authorize
    -> StartTransaction -> MeterValues -> StopTransaction -> hisob

Asosiy savollar:
  1. Noma'lum charger ulana oladimi (ulanmasligi kerak)?
  2. Karta ro'yxatga o'zi tushadimi va balans qoidasi qo'llanadimi?
  3. Sessiya ochiladimi va telemetriya yoziladimi?
  4. Sessiya yopilganda pul HAQIQATAN yechiladimi?
  5. Ulagich va stansiya holati oqim davomida to'g'ri o'zgaradimi?
"""
import json
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from asgiref.sync import async_to_sync, sync_to_async  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import RfidCard  # noqa: E402
from management.models import SiteSettings  # noqa: E402
from ocpp_gateway.routing import websocket_urlpatterns  # noqa: E402
from sessions_app.models import ChargingSession, SessionMeterReading  # noqa: E402
from stations.models import ChargerInfo, Connector, Station  # noqa: E402
from wallet.models import Transaction, WalletBalance  # noqa: E402

failures = 0

CP_ID = '__FLOW_CP__'
CARD = '__FLOW_CARD__'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    ChargingSession.objects.filter(station__ocpp_id=CP_ID).delete()
    RfidCard.objects.filter(id_tag=CARD).delete()
    Station.objects.filter(name__startswith='__flow').delete()
    Transaction.objects.filter(user__username__startswith='__flow').delete()
    User.objects.filter(username__startswith='__flow').delete()


def application():
    """Faqat WebSocket marshrutlari — HTTP qismi bu testda kerak emas."""
    from channels.routing import ProtocolTypeRouter, URLRouter

    return ProtocolTypeRouter({'websocket': URLRouter(websocket_urlpatterns)})


async def call(communicator, action, payload, unique_id):
    """OCPP CALL yuboradi va javobni qaytaradi."""
    await communicator.send_to(text_data=json.dumps([2, unique_id, action, payload]))
    raw = await communicator.receive_from(timeout=5)
    message = json.loads(raw)
    # [3, id, payload] — CALLRESULT, [4, ...] — CALLERROR
    return message[0], (message[2] if message[0] == 3 else message[2:])


@sync_to_async
def snapshot(station):
    """Bazaning ayni paytdagi holati — oqim davomida o'lchash uchun."""
    session = ChargingSession.objects.filter(station=station).order_by('-id').first()
    connector = station.connectors.first()
    connector.refresh_from_db()
    return {
        'session_status': session.status if session else None,
        'connector_status': connector.status,
        'kwh': session.kwh_charged if session else None,
    }


async def flow(station, connector):
    """Butun oqim bitta ulanish ichida."""
    communicator = WebsocketCommunicator(
        application(), f'/ws/ocpp/{CP_ID}/', subprotocols=['ocpp1.6'])
    connected, _ = await communicator.connect(timeout=5)
    results = {'connected': connected}

    if not connected:
        return results

    kind, boot = await call(communicator, 'BootNotification', {
        'chargePointVendor': 'VoltMax', 'chargePointModel': 'VM-60',
        'firmwareVersion': '1.2.3', 'chargePointSerialNumber': 'SN-777',
    }, 'b1')
    results['boot'] = (kind, boot)

    kind, status = await call(communicator, 'StatusNotification', {
        'connectorId': 1, 'status': 'Available', 'errorCode': 'NoError',
    }, 's1')
    results['status'] = (kind, status)

    kind, auth = await call(communicator, 'Authorize', {'idTag': CARD}, 'a1')
    results['authorize'] = (kind, auth)

    kind, start = await call(communicator, 'StartTransaction', {
        'connectorId': 1, 'idTag': CARD, 'meterStart': 0,
        'timestamp': timezone.now().isoformat(),
    }, 't1')
    results['start'] = (kind, start)

    transaction_id = (start or {}).get('transactionId')

    # Oraliq holat AYNAN SHU PAYTDA o'lchanadi: oqim tugagach sessiya
    # allaqachon yopilgan bo'ladi va "ketmoqda" holatini ko'rib bo'lmaydi
    results['after_start'] = await snapshot(station)

    kind, meter = await call(communicator, 'MeterValues', {
        'connectorId': 1, 'transactionId': transaction_id,
        'meterValue': [{
            'timestamp': timezone.now().isoformat(),
            'sampledValue': [
                {'measurand': 'Energy.Active.Import.Register', 'value': '5000',
                 'unit': 'Wh'},
                {'measurand': 'Voltage', 'value': '398.5', 'unit': 'V'},
                {'measurand': 'Current.Import', 'value': '62.4', 'unit': 'A'},
                {'measurand': 'SoC', 'value': '45'},
            ],
        }],
    }, 'm1')
    results['meter'] = (kind, meter)
    results['after_meter'] = await snapshot(station)

    kind, stop = await call(communicator, 'StopTransaction', {
        'transactionId': transaction_id, 'idTag': CARD, 'meterStop': 10000,
        'timestamp': timezone.now().isoformat(), 'reason': 'Local',
    }, 'x1')
    results['stop'] = (kind, stop)

    await communicator.disconnect()
    return results


async def stranger():
    """Ro'yxatda yo'q charger ulana olmasligi kerak."""
    communicator = WebsocketCommunicator(
        application(), '/ws/ocpp/__FLOW_YOQ__/', subprotocols=['ocpp1.6'])
    connected, _ = await communicator.connect(timeout=5)
    if connected:
        await communicator.disconnect()
    return connected


def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f)
             for f in ('min_balance_to_start', 'work_all_day', 'require_known_rfid',
                       'default_price_per_kwh')}
    try:
        settings_obj.min_balance_to_start = 0
        settings_obj.work_all_day = True
        settings_obj.require_known_rfid = False
        settings_obj.default_price_per_kwh = 1200
        settings_obj.save()

        driver = User.objects.create(username='__flow_driver__')
        WalletBalance.objects.create(user=driver, amount=100000)

        station = Station.objects.create(
            name='__flow Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='dc', power_kw=60, ocpp_id=CP_ID)
        connector = Connector.objects.create(
            station=station, label='A', type='ccs2', power_kw=60,
            ocpp_connector_id=1, status=Connector.Status.OFFLINE)

        # Karta oldindan yaratiladi — egasi bo'lsa pul uning hisobidan yechiladi
        RfidCard.objects.create(id_tag=CARD, user=driver,
                                status=RfidCard.Status.ACTIVE)

        # ── 1. Noma'lum charger ────────────────────────────────
        check("noma'lum charger ulanmadi", not async_to_sync(stranger)())

        # ── 2. To'liq oqim ─────────────────────────────────────
        results = async_to_sync(flow)(station, connector)
        check('charger ulandi', results['connected'])

        kind, boot = results['boot']
        check('BootNotification qabul qilindi',
              kind == 3 and boot.get('status') == 'Accepted', boot)
        check('heartbeat oralig\'i aytildi', boot.get('interval', 0) > 0, boot.get('interval'))

        info = ChargerInfo.objects.filter(station=station).first()
        check('qurilma pasporti saqlandi',
              info is not None and info.firmware_version == '1.2.3',
              info.firmware_version if info else None)

        connector.refresh_from_db()
        check('ulagich bo\'sh holatga o\'tdi',
              connector.status == Connector.Status.AVAILABLE, connector.status)

        kind, auth = results['authorize']
        check('karta tasdiqlandi',
              kind == 3 and auth['idTagInfo']['status'] == 'Accepted', auth)

        kind, start = results['start']
        check('tranzaksiya ochildi',
              kind == 3 and start.get('transactionId'), start)

        session = ChargingSession.objects.filter(station=station).first()
        check('sessiya yaratildi', session is not None)
        check('sessiya kartaning egasiga bog\'landi',
              session.user_id == driver.id, session.user)
        started = results['after_start']
        check('sessiya ketmoqda (oqim ichida)',
              started['session_status'] == ChargingSession.Status.CHARGING,
              started['session_status'])
        check('ulagich zaryadlash holatida (oqim ichida)',
              started['connector_status'] == Connector.Status.CHARGING,
              started['connector_status'])
        # ── 3. Telemetriya ─────────────────────────────────────
        reading = SessionMeterReading.objects.filter(session=session).first()
        check('telemetriya yozildi', reading is not None)
        check('kuchlanish saqlandi',
              reading and abs((reading.voltage_v or 0) - 398.5) < 0.1,
              reading.voltage_v if reading else None)
        check('zaryad foizi saqlandi',
              reading and reading.soc_percent == 45,
              reading.soc_percent if reading else None)

        # MeterValues kelgan paytda 5 000 Wh = 5 kVt·soat bo'lgan
        check('sessiyada energiya yangilandi (oqim ichida)',
              abs((results['after_meter']['kwh'] or 0) - 5.0) < 0.01,
              results['after_meter']['kwh'])

        # ── 4. Yakun va hisob ──────────────────────────────────
        kind, stop = results['stop']
        check('StopTransaction qabul qilindi', kind == 3, stop)

        session.refresh_from_db()
        check('sessiya yopildi',
              session.status != ChargingSession.Status.CHARGING, session.status)
        # 10 000 Wh = 10 kVt·soat × 1200 = 12 000 so'm
        check('yakuniy energiya to\'g\'ri',
              abs((session.final_kwh_charged or 0) - 10.0) < 0.01,
              session.final_kwh_charged)
        check('yakuniy summa to\'g\'ri',
              session.final_cost == 12000, session.final_cost)

        wallet = WalletBalance.objects.get(user=driver)
        check('PUL HAMYONDAN YECHILDI', wallet.amount == 88000, wallet.amount)
        check('tranzaksiya yozildi',
              Transaction.objects.filter(user=driver,
                                         type=Transaction.Type.CHARGE_PAYMENT,
                                         amount=12000).exists())

        connector.refresh_from_db()
        check('ulagich bo\'shadi',
              connector.status != Connector.Status.CHARGING, connector.status)

        card = RfidCard.objects.get(id_tag=CARD)
        check('karta ishlatilgani sanaldi', card.use_count >= 1, card.use_count)

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
