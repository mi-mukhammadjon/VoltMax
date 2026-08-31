# -*- coding: utf-8 -*-
"""Qurilmadan olinadigan ma'lumotlar tekshiruvi.

Asosiy savollar:
  1. BootNotification'dagi pasport saqlanadimi va yuklanishlar sanaladimi?
  2. GetConfiguration javobi sozlamalar jadvaliga tushadimi?
  3. Kengaytirilgan o'lchovlar (fazalar, harorat, chastota) o'qiladimi?
  4. StopTransaction sababi va yakuniy o'lchovlari saqlanadimi?
  5. Jurnal to'ldiriladimi va cheklab turiladimi?
"""
import asyncio
import os
from datetime import timedelta

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from asgiref.sync import async_to_sync  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from ocpp_gateway.consumers import ChargerLogKind, OCPPConsumer, _extract_samples  # noqa: E402
from sessions_app.models import ChargingSession, SessionMeterReading  # noqa: E402
from stations.models import (  # noqa: E402
    ChargerConfiguration, ChargerInfo, ChargerLog, Connector, Station,
)

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:52s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    Station.objects.filter(name__startswith='__dd').delete()
    User.objects.filter(username__startswith='__dd').delete()


def make_consumer(station):
    """Consumer'ning DB yordamchilarini WebSocket'siz sinash uchun nusxa.

    Handlerlar faqat `self.station_id` va `self.ocpp_id` ga tayanadi, shuning
    uchun to'liq ulanishni ko'tarish shart emas.
    """
    consumer = OCPPConsumer()
    consumer.station_id = station.id
    consumer.ocpp_id = station.ocpp_id
    consumer._pending_calls = {}
    consumer._sent_actions = {}
    return consumer


def main():
    _cleanup()

    admin = User.objects.create(username='__dd_admin__', is_staff=True, is_superuser=True)
    driver = User.objects.create(username='__dd_driver__')
    station = Station.objects.create(
        name='__dd_station__', address='a', latitude=41.0, longitude=69.0,
        power_kw=120, ocpp_id='__DD_CP__', ocpp_last_seen_at=timezone.now(),
    )
    connector = Connector.objects.create(
        station=station, label='A', type='DC', power_kw=60, ocpp_connector_id=1,
    )
    consumer = make_consumer(station)

    try:
        # ── 1. Jurnal turlari model bilan mos ───────────────────
        model_kinds = {value for value, _ in ChargerLog.Kind.choices}
        consumer_kinds = {
            getattr(ChargerLogKind, name) for name in dir(ChargerLogKind)
            if not name.startswith('_')
        }
        check('jurnal turlari model bilan mos', consumer_kinds == model_kinds,
              consumer_kinds ^ model_kinds)

        # ── 2. Qurilma pasporti ─────────────────────────────────
        boot = {
            'chargePointVendor': 'ABB', 'chargePointModel': 'Terra AC W22',
            'chargePointSerialNumber': 'SN-4471', 'chargeBoxSerialNumber': 'BOX-9',
            'firmwareVersion': '2.3.1', 'iccid': '8998001234567890123',
            'imsi': '434040123456789', 'meterType': 'AC-3P',
            'meterSerialNumber': 'MTR-55',
        }
        async_to_sync(consumer.on_boot_notification)(boot)

        info = ChargerInfo.objects.get(station=station)
        check('ishlab chiqaruvchi saqlandi', info.vendor == 'ABB', info.vendor)
        check('model saqlandi', info.model == 'Terra AC W22', info.model)
        check('seriya raqami saqlandi', info.serial_number == 'SN-4471')
        check('proshivka saqlandi', info.firmware_version == '2.3.1')
        check('SIM ICCID saqlandi', info.iccid == '8998001234567890123')
        check('hisoblagich saqlandi', info.meter_serial == 'MTR-55')
        check('yuklanish sanaldi', info.boot_count == 1, info.boot_count)
        check('birinchi yuklanish belgilandi', info.first_boot_at is not None)

        # Ikkinchi yuklanish: sanoq oshadi, bo'sh maydon eskisini o'chirmaydi
        async_to_sync(consumer.on_boot_notification)({'chargePointVendor': 'ABB'})
        info.refresh_from_db()
        check('ikkinchi yuklanish sanaldi', info.boot_count == 2, info.boot_count)
        check('bo\'sh maydon eskisini o\'chirmadi',
              info.firmware_version == '2.3.1', info.firmware_version)
        check('yuklanish jurnalga tushdi',
              ChargerLog.objects.filter(station=station, kind='boot').count() == 2)

        # ── 3. Proshivka/diagnostika holati ─────────────────────
        async_to_sync(consumer.on_firmware_status_notification)({'status': 'Installed'})
        async_to_sync(consumer.on_diagnostics_status_notification)({'status': 'Uploaded'})
        info.refresh_from_db()
        check('proshivka holati saqlandi', info.firmware_status == 'Installed')
        check('diagnostika holati saqlandi', info.diagnostics_status == 'Uploaded')

        # ── 4. Sozlamalar (GetConfiguration javobi) ─────────────
        consumer._sent_actions['req-1'] = 'GetConfiguration'
        async_to_sync(consumer._handle_call_result)('req-1', {
            'configurationKey': [
                {'key': 'HeartbeatInterval', 'value': '300', 'readonly': False},
                {'key': 'NumberOfConnectors', 'value': '2', 'readonly': True},
            ],
            'unknownKey': ['SomethingElse'],
        })
        rows = {c.key: c for c in ChargerConfiguration.objects.filter(station=station)}
        check('sozlamalar saqlandi', len(rows) == 3, list(rows))
        check('qiymat to\'g\'ri', rows['HeartbeatInterval'].value == '300')
        check('faqat o\'qish belgilandi', rows['NumberOfConnectors'].is_readonly is True)
        check('noma\'lum kalit belgilandi', rows['SomethingElse'].is_unknown is True)

        # Ikkinchi o'qishda yo'qolgan kalit olib tashlanadi
        consumer._sent_actions['req-2'] = 'GetConfiguration'
        async_to_sync(consumer._handle_call_result)('req-2', {
            'configurationKey': [{'key': 'HeartbeatInterval', 'value': '600', 'readonly': False}],
        })
        rows = {c.key: c for c in ChargerConfiguration.objects.filter(station=station)}
        check('eskirgan kalitlar tozalandi', list(rows) == ['HeartbeatInterval'], list(rows))
        check('qiymat yangilandi', rows['HeartbeatInterval'].value == '600')

        # Rad etilgan buyruq jurnalga tushadi
        consumer._sent_actions['req-3'] = 'ChangeConfiguration'
        async_to_sync(consumer._handle_call_result)('req-3', {'error': 'NotSupported'})
        check('rad etilgan buyruq jurnalda',
              ChargerLog.objects.filter(station=station, kind='error').exists())

        # ── 5. Kengaytirilgan o'lchovlar ────────────────────────
        samples = _extract_samples([{'sampledValue': [
            {'value': '31.5', 'measurand': 'Temperature', 'unit': 'Celsius'},
            {'value': '49.98', 'measurand': 'Frequency', 'unit': 'Hz'},
            {'value': '32.0', 'measurand': 'Current.Offered', 'unit': 'A'},
            {'value': '22000', 'measurand': 'Power.Offered', 'unit': 'W'},
            {'value': '401.2', 'measurand': 'Voltage', 'unit': 'V', 'phase': 'L1-N'},
            {'value': '398.7', 'measurand': 'Voltage', 'unit': 'V', 'phase': 'L2-N'},
            {'value': '402.9', 'measurand': 'Voltage', 'unit': 'V', 'phase': 'L3-N'},
        ]}])
        check('harorat o\'qildi', samples['temperature_c'] == 31.5, samples.get('temperature_c'))
        check('chastota o\'qildi', samples['frequency_hz'] == 49.98)
        check('taklif qilingan tok o\'qildi', samples['current_offered_a'] == 32.0)
        check('taklif qilingan quvvat kVt', samples['power_offered_kw'] == 22.0)
        check('L1 fazasi', samples['voltage_l1_v'] == 401.2, samples.get('voltage_l1_v'))
        check('L2 fazasi', samples['voltage_l2_v'] == 398.7)
        check('L3 fazasi', samples['voltage_l3_v'] == 402.9)
        check('umumiy kuchlanish L1 dan olindi', samples['voltage_v'] == 401.2)

        # Fazasiz qiymat kelsa u ustun turadi
        mixed = _extract_samples([{'sampledValue': [
            {'value': '400.0', 'measurand': 'Voltage', 'unit': 'V'},
            {'value': '395.0', 'measurand': 'Voltage', 'unit': 'V', 'phase': 'L1'},
        ]}])
        check('fazasiz qiymat ustun', mixed['voltage_v'] == 400.0, mixed.get('voltage_v'))
        check('faza baribir yozildi', mixed['voltage_l1_v'] == 395.0)

        # ── 6. Sessiya tugash sababi va yakuniy o'lchov ─────────
        session = ChargingSession.objects.create(
            user=driver, station=station, connector=connector, start_percent=20,
            power_kw=60, price_per_kwh=1500, connector_label='A', is_live=True,
            meter_start_wh=1000, live_meter_wh=1000,
        )
        connector.status = Connector.Status.CHARGING
        connector.save(update_fields=['status'])

        async_to_sync(consumer.on_stop_transaction)({
            'transactionId': session.id, 'meterStop': 9000, 'reason': 'EVDisconnected',
            'transactionData': [{'sampledValue': [
                {'value': '9000', 'measurand': 'Energy.Active.Import.Register', 'unit': 'Wh'},
                {'value': '397.5', 'measurand': 'Voltage', 'unit': 'V'},
            ]}],
        })
        session.refresh_from_db()
        check('tugash sababi saqlandi', session.stop_reason == 'EVDisconnected',
              session.stop_reason)
        check('sessiya yopildi', session.status != ChargingSession.Status.CHARGING,
              session.status)
        final = SessionMeterReading.objects.filter(session=session).last()
        check('yakuniy o\'lchov yozildi', final is not None and final.voltage_v == 397.5,
              final and final.voltage_v)
        check('tugash jurnalga tushdi',
              ChargerLog.objects.filter(station=station, kind='stop').exists())

        # ── 7. Holat xabari jurnalda ────────────────────────────
        async_to_sync(consumer.on_status_notification)({
            'connectorId': 1, 'status': 'Faulted', 'errorCode': 'GroundFailure',
            'vendorErrorCode': 'E-042', 'info': 'RCD tripped',
        })
        fault = ChargerLog.objects.filter(station=station, action='StatusNotification').first()
        check('nosozlik jurnalda "error" turida', fault.kind == 'error', fault.kind)
        check('xom payload saqlandi', fault.payload.get('vendorErrorCode') == 'E-042',
              fault.payload)
        check('izoh o\'qiladigan', 'GroundFailure' in fault.summary, fault.summary)

        # ── 8. Jurnal cheklovi ──────────────────────────────────
        old = ChargerLog.objects.create(station=station, action='Old', summary='eski')
        ChargerLog.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=60))
        removed = ChargerLog.prune(keep_days=30, keep_per_station=500)
        check('eski yozuv tozalandi', removed >= 1 and not ChargerLog.objects.filter(
            pk=old.pk).exists(), removed)

        for i in range(12):
            ChargerLog.objects.create(station=station, action=f'X{i}', summary=str(i))
        ChargerLog.prune(keep_days=30, keep_per_station=5)
        check('soni bo\'yicha cheklandi',
              ChargerLog.objects.filter(station=station).count() == 5,
              ChargerLog.objects.filter(station=station).count())

        # ── 9. Panel sahifasi ───────────────────────────────────
        with override_settings(ALLOWED_HOSTS=['testserver']):
            client = Client()
            client.force_login(admin)
            body = client.get(f'/stations/{station.id}/').content.decode()

            check('pasport ko\'rinadi', 'Terra AC W22' in body)
            check('proshivka ko\'rinadi', '2.3.1' in body)
            check('SIM ko\'rinadi', '8998001234567890123' in body)
            check('sozlamalar jadvali bor', 'HeartbeatInterval' in body)
            check('jurnal ko\'rinadi', 'Qurilma jurnali' in body)
            check('o\'qish tugmasi bor', 'device/read-config/' in body)
            check('reset tugmasi bor', 'device/reset/' in body)

            page = client.get(f'/sessions/{session.id}/').content.decode()
            check('sessiyada tugash sababi', 'Kabel avtomobildan uzildi' in page)

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
