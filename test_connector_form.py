# -*- coding: utf-8 -*-
"""Ulagich formasi tekshiruvi.

Asosiy savollar:
  1. Holat va ishlamaslik sababi formadan chiqarilganmi?
  2. Bir stansiya ichida yorliq va connectorId takrorlanmasligi ushlanadimi?
  3. OCPP'da 0 raqami chargerning o'zi — u rad etiladimi?
  4. Ketayotgan sessiya paytida OCPP raqami himoyalanganmi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402

from dashboard.forms import ConnectorForm  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Station  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:50s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    Station.objects.filter(name__startswith='__cf').delete()
    User.objects.filter(username__startswith='__cf').delete()


def base_data(**over):
    data = {'label': 'B', 'type': 'DC', 'power_kw': '60', 'ocpp_connector_id': '2'}
    data.update(over)
    return data


def main():
    _cleanup()

    admin = User.objects.create(username='__cf_admin__', is_staff=True, is_superuser=True)
    driver = User.objects.create(username='__cf_driver__')
    station = Station.objects.create(
        name='__cf_station__', address='a', latitude=41.0, longitude=69.0, power_kw=120,
    )
    existing = Connector.objects.create(
        station=station, label='A', type='DC', power_kw=60, ocpp_connector_id=1,
    )

    try:
        # ── 1. Formada nima bor va nima yo'q ────────────────────
        fields = list(ConnectorForm(station=station).fields)
        check('holat maydoni yo\'q', 'status' not in fields, fields)
        check('sabab maydoni yo\'q', 'offline_reason' not in fields, fields)
        check('kerakli maydonlar bor',
              fields == ['label', 'type', 'power_kw', 'ocpp_connector_id'], fields)

        html = str(ConnectorForm(station=station))
        check('shaklda status select yo\'q', 'name="status"' not in html)
        ocpp_field = ConnectorForm(station=station).fields['ocpp_connector_id']
        check('OCPP maydoni izohli', "Chargerdagi" in ocpp_field.help_text,
              ocpp_field.help_text)
        check('OCPP maydoni majburiy emas', ocpp_field.required is False)

        # ── 2. To'g'ri ma'lumot saqlanadi ──────────────────────
        form = ConnectorForm(base_data(), station=station)
        check('yaroqli forma o\'tdi', form.is_valid(), form.errors.as_text()[:150])

        # ── 3. Takrorlanish ushlanadi ──────────────────────────
        form = ConnectorForm(base_data(label='a'), station=station)
        check('yorliq takrorlanishi ushlandi (registr farqsiz)',
              not form.is_valid() and 'label' in form.errors,
              form.errors.get('label'))

        form = ConnectorForm(base_data(ocpp_connector_id='1'), station=station)
        check('connectorId takrorlanishi ushlandi',
              not form.is_valid() and 'ocpp_connector_id' in form.errors,
              form.errors.get('ocpp_connector_id'))

        # O'zini o'zi bilan solishtirmasin
        form = ConnectorForm(base_data(label='A', ocpp_connector_id='1'), instance=existing)
        check('tahrirlashda o\'z qiymati xato emas', form.is_valid(),
              form.errors.as_text()[:150])

        # ── 4. OCPP qoidalari ──────────────────────────────────
        form = ConnectorForm(base_data(ocpp_connector_id='0'), station=station)
        check('connectorId=0 rad etildi',
              not form.is_valid() and 'ocpp_connector_id' in form.errors,
              form.errors.get('ocpp_connector_id'))

        form = ConnectorForm(base_data(ocpp_connector_id=''), station=station)
        check('bo\'sh connectorId ruxsat etiladi', form.is_valid(),
              form.errors.as_text()[:150])

        # ── 5. Quvvat stansiyanikidan oshmasin ─────────────────
        form = ConnectorForm(base_data(power_kw='500'), station=station)
        check('haddan ortiq quvvat ushlandi',
              not form.is_valid() and 'power_kw' in form.errors,
              form.errors.get('power_kw'))

        form = ConnectorForm(base_data(power_kw='120'), station=station)
        check('stansiyaga teng quvvat ruxsat etiladi', form.is_valid(),
              form.errors.as_text()[:150])

        # ── 6. Panel sahifalari ────────────────────────────────
        with override_settings(ALLOWED_HOSTS=['testserver']):
            client = Client()
            client.force_login(admin)

            page = client.get(f'/stations/{station.id}/connectors/{existing.id}/edit/')
            body = page.content.decode()
            check('sahifa ochildi', page.status_code == 200, page.status_code)
            check('sahifada status tanlagichi yo\'q', 'name="status"' not in body)
            check('sahifada sabab maydoni yo\'q', 'name="offline_reason"' not in body)
            check('holat bloki ko\'rinadi', 'device-state' in body)
            check('profilaktikaga havola bor', '/maintenance/' in body)

            # Qo'shish formasi ham holatsiz
            detail = client.get(f'/stations/{station.id}/').content.decode()
            check('qo\'shish formasida holat yo\'q',
                  'add_connector' in detail and 'name="status"' not in detail)

            # Takrorlangan yorliq bilan qo'shishga urinish — sabab ko'rinsin
            resp = client.post(f'/stations/{station.id}/', {
                'action': 'add_connector', 'label': 'A', 'type': 'DC',
                'power_kw': '60', 'ocpp_connector_id': '3',
            })
            from django.contrib.messages import get_messages
            texts = [str(m) for m in get_messages(resp.wsgi_request)]
            check('takrorlangan yorliq sababi aytildi',
                  any('band' in t for t in texts), texts)

            # ── 7. Faol sessiya OCPP raqamini himoyalaydi ──────
            session = ChargingSession.objects.create(
                user=driver, station=station, connector=existing, start_percent=20,
                power_kw=60, price_per_kwh=1500, connector_label='A',
            )
            resp = client.post(
                f'/stations/{station.id}/connectors/{existing.id}/edit/',
                base_data(label='A', ocpp_connector_id='7'))
            existing.refresh_from_db()
            texts = [str(m) for m in get_messages(resp.wsgi_request)]
            check('sessiya paytida OCPP raqami o\'zgarmadi',
                  existing.ocpp_connector_id == 1, existing.ocpp_connector_id)
            check('sabab tushuntirildi',
                  any('sessiyani' in t.lower() or 'zaryadlash' in t.lower() for t in texts),
                  texts)

            # Boshqa maydonlarni o'zgartirish esa taqiqlanmagan
            resp = client.post(
                f'/stations/{station.id}/connectors/{existing.id}/edit/',
                base_data(label='A', power_kw='45', ocpp_connector_id='1'))
            existing.refresh_from_db()
            check('sessiya paytida quvvat saqlandi', existing.power_kw == 45,
                  existing.power_kw)

            session.delete()

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
