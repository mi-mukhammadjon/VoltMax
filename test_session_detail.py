# -*- coding: utf-8 -*-
"""Sessiya detali sahifasi va telemetriya tekshiruvi.

Asosiy savollar:
  1. MeterValues'dagi kuchlanish/tok/quvvat o'lchovlari saqlanadimi?
  2. Grafik koordinatalari to'g'ri hisoblanadimi (bir nuqta / o'zgarmas qiymat)?
  3. Sessiyaga mashina va VIN biriktiriladimi va mashina o'chsa qoladimi?
  4. Sahifada hamma tafsilot ko'rinadimi?
"""
import os
import re
from datetime import timedelta

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import Vehicle  # noqa: E402
from accounts.serializers import VehicleSerializer  # noqa: E402
from dashboard.charts import line_chart  # noqa: E402
from ocpp_gateway.consumers import _extract_samples  # noqa: E402
from sessions_app.models import ChargingSession, SessionMeterReading  # noqa: E402
from sessions_app.services import vehicle_snapshot  # noqa: E402
from stations.models import Connector, Station  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:52s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    Station.objects.filter(name__startswith='__sd').delete()
    User.objects.filter(username__startswith='__sd').delete()


def main():
    _cleanup()

    admin = User.objects.create(username='__sd_admin__', is_staff=True, is_superuser=True)
    driver = User.objects.create(username='__sd_driver__')
    station = Station.objects.create(
        name='__sd_station__', address='a', latitude=41.0, longitude=69.0, power_kw=120,
    )
    connector = Connector.objects.create(
        station=station, label='A', type='DC', power_kw=60, ocpp_connector_id=1,
    )

    try:
        # ── 1. MeterValues tahlili ──────────────────────────────
        payload = [{
            'timestamp': '2026-08-30T10:00:00Z',
            'sampledValue': [
                {'value': '12500', 'measurand': 'Energy.Active.Import.Register', 'unit': 'Wh'},
                {'value': '398.4', 'measurand': 'Voltage', 'unit': 'V'},
                {'value': '148.2', 'measurand': 'Current.Import', 'unit': 'A'},
                {'value': '59000', 'measurand': 'Power.Active.Import', 'unit': 'W'},
                {'value': '64', 'measurand': 'SoC', 'unit': 'Percent'},
            ],
        }]
        samples = _extract_samples(payload)
        check('kuchlanish o\'qildi', samples['voltage_v'] == 398.4, samples.get('voltage_v'))
        check('tok o\'qildi', samples['current_a'] == 148.2, samples.get('current_a'))
        check('quvvat W -> kVt', samples['power_kw'] == 59.0, samples.get('power_kw'))
        check('energiya o\'qildi', samples['energy_wh'] == 12500, samples.get('energy_wh'))
        check('SoC o\'qildi', samples['soc_percent'] == 64, samples.get('soc_percent'))

        # kWh -> Wh o'girish
        kwh = _extract_samples([{'sampledValue': [
            {'value': '12.5', 'measurand': 'Energy.Active.Import.Register', 'unit': 'kWh'}]}])
        check('kWh -> Wh o\'girildi', kwh['energy_wh'] == 12500, kwh.get('energy_wh'))

        # Birlik ko'rsatilmasa — standart birlik
        default_unit = _extract_samples([{'sampledValue': [
            {'value': '401', 'measurand': 'Voltage'}]}])
        check('birliksiz qiymat qabul qilindi',
              default_unit.get('voltage_v') == 401, default_unit)

        # Biz kuzatmaydigan o'lchov jimgina o'tkaziladi (RPM — ventilyator
        # aylanishi, bizga kerak emas)
        unknown = _extract_samples([{'sampledValue': [
            {'value': '1200', 'measurand': 'RPM'}]}])
        check('kuzatilmaydigan o\'lchov tashlandi', unknown == {}, unknown)

        # ── 2. Mashina biriktirish ──────────────────────────────
        vehicle = Vehicle.objects.create(
            user=driver, name='Kundalik', make='Chevrolet', model='Bolt EV',
            year=2022, battery_capacity_kwh=65, vin='1G1FY6S07P4100001', is_default=True,
        )
        found, label, vin = vehicle_snapshot(driver)
        check('standart mashina topildi', found == vehicle)
        check('nom suratga olindi', label == 'Chevrolet Bolt EV', label)
        check('VIN suratga olindi', vin == '1G1FY6S07P4100001', vin)

        session = ChargingSession.objects.create(
            user=driver, station=station, connector=connector, start_percent=20,
            power_kw=60, price_per_kwh=1500, connector_label='A', is_live=True,
            vehicle=found, vehicle_label=label, vehicle_vin=vin,
        )

        # ── 3. O'lchovlar va grafik ─────────────────────────────
        base = timezone.now() - timedelta(minutes=20)
        volts = [400, 396, 402, 391, 399, 405, 398]
        for i, v in enumerate(volts):
            SessionMeterReading.objects.create(
                session=session, recorded_at=base + timedelta(minutes=i * 3),
                voltage_v=v, current_a=150 - i * 4, energy_wh=1000 * i,
            )

        rows = list(session.readings.all())
        check('o\'lchovlar vaqt bo\'yicha tartiblangan',
              [r.voltage_v for r in rows] == volts, [r.voltage_v for r in rows])

        chart = line_chart(rows, value_getter=lambda r: r.voltage_v, unit='V')
        check('grafik qurildi', chart is not None)
        check('nuqtalar soni to\'g\'ri', chart['count'] == len(volts), chart['count'])
        check('eng past qiymat', chart['min'] == '391', chart['min'])
        check('eng yuqori qiymat', chart['max'] == '405', chart['max'])
        check('oxirgi qiymat', chart['last'] == '398', chart['last'])
        coords = [tuple(map(float, p.split(','))) for p in chart['polyline'].split()]
        check('birinchi nuqta chap chekkada',
              abs(coords[0][0] - chart['plot_x']) < 0.5, coords[0])
        check('oxirgi nuqta o\'ng chekkada',
              abs(coords[-1][0] - (chart['plot_x'] + chart['plot_w'])) < 0.5, coords[-1])
        check('eng past qiymat eng pastda',
              coords[3][1] == max(y for _, y in coords), coords[3])
        check('barcha nuqtalar ramka ichida',
              all(chart['plot_y'] <= y <= chart['plot_y'] + chart['plot_h'] for _, y in coords))

        # Chekka holatlar
        check('bitta nuqtada grafik yo\'q',
              line_chart(rows[:1], value_getter=lambda r: r.voltage_v) is None)
        check('qiymatsiz o\'lchovlarda grafik yo\'q',
              line_chart(rows, value_getter=lambda r: r.soc_percent) is None)

        flat = line_chart(rows, value_getter=lambda r: 400.0)
        check('o\'zgarmas qiymat ham chiziladi', flat is not None and flat['min'] == '400',
              flat and flat['min'])

        # ── 4. Panel sahifasi ───────────────────────────────────
        with override_settings(ALLOWED_HOSTS=['testserver']):
            client = Client()
            client.force_login(admin)
            page = client.get(f'/sessions/{session.id}/')
            body = page.content.decode()

            check('sahifa ochildi', page.status_code == 200, page.status_code)
            check('VIN ko\'rinadi', '1G1FY6S07P4100001' in body)
            check('mashina nomi ko\'rinadi', 'Chevrolet Bolt EV' in body)
            check('batareya sig\'imi ko\'rinadi', '65 kVt·s' in body)
            check('grafik chizildi', 'lc-line' in body and 'polyline' in body)
            check('grafik statistikasi bor', 'Eng past' in body and 'O\'rtacha' in body)
            check('tok grafigi ham bor', 'is-current' in body)
            check('o\'lchangan kuchlanish ko\'rsatilgan', "o'lchangan" in body)
            check('davomiylik formatlangan', 'daq' in body or 'soat' in body)

            # O'lchovsiz sessiyada bo'sh holat
            plain = ChargingSession.objects.create(
                user=driver, station=station, connector=connector, start_percent=30,
                power_kw=60, price_per_kwh=1500, connector_label='A',
            )
            body = client.get(f'/sessions/{plain.id}/').content.decode()
            check('o\'lchovsiz sahifada bo\'sh holat', "O'lchov ma'lumoti yo'q" in body)
            check('o\'lchovsiz sahifada grafik yo\'q', 'lc-line' not in body)
            check('mashinasiz sessiya haqida aytildi',
                  'Mashina biriktirilmagan' in body)

        # ── 5. Mashina o'chsa VIN tarixda qoladi ───────────────
        vehicle.delete()
        session.refresh_from_db()
        check('havola bo\'shadi', session.vehicle_id is None)
        check('VIN tarixda qoldi', session.vehicle_vin == '1G1FY6S07P4100001',
              session.vehicle_vin)
        check('nom tarixda qoldi', session.vehicle_label == 'Chevrolet Bolt EV')

        # ── 6. VIN tekshiruvi (mobil API) ──────────────────────
        bad = VehicleSerializer(data={'name': 'x', 'vin': 'QQQ'})
        check('qisqa VIN rad etildi', not bad.is_valid() and 'vin' in bad.errors,
              bad.errors.get('vin'))

        bad = VehicleSerializer(data={'name': 'x', 'vin': '1G1FY6S07P41OOOO1'})
        check('taqiqlangan harf rad etildi', not bad.is_valid() and 'vin' in bad.errors,
              bad.errors.get('vin'))

        good = VehicleSerializer(data={'name': 'x', 'vin': '1g1fy6s07p4100002'})
        check('kichik harf qabul qilindi', good.is_valid(), good.errors)
        check('VIN katta harfga o\'girildi',
              good.is_valid() and good.validated_data['vin'] == '1G1FY6S07P4100002',
              good.validated_data.get('vin') if good.is_valid() else '')

        empty = VehicleSerializer(data={'name': 'x', 'vin': ''})
        check('bo\'sh VIN ruxsat etiladi', empty.is_valid(), empty.errors)

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
