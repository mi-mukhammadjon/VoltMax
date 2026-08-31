# -*- coding: utf-8 -*-
"""Qurilma boshqaruvi: RFID, bron, quvvat chegarasi, proshivka.

Asosiy savollar:
  1. Avtorizatsiya endi haqiqatan tekshiriladimi (ilgari hammani qabul qilardi)?
  2. Noma'lum karta ro'yxatga tushadimi va qat'iy rejim ishlaydimi?
  3. Bron qurilmaga yetkaziladimi va bekor qilinganda bo'shatiladimi?
  4. Quvvat chegarasi tekshiriladi va yuboriladimi?
  5. Proshivka/diagnostika havolasi tekshiriladimi?
"""
import os
from datetime import timedelta

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from asgiref.sync import async_to_sync  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.contrib.messages import get_messages  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402

import ocpp_gateway.commands as ocpp_commands  # noqa: E402
from accounts.models import RfidCard  # noqa: E402
from bookings.models import Booking  # noqa: E402
from bookings.reservations import hold_connector, release_connector  # noqa: E402
from management.models import SiteSettings  # noqa: E402
from ocpp_gateway.consumers import OCPPConsumer  # noqa: E402
from stations.models import ChargerLog, Connector, Station  # noqa: E402
from stations.services import sync_station_status  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:54s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    RfidCard.objects.filter(id_tag__startswith='__DC').delete()
    Station.objects.filter(name__startswith='__dc').delete()
    User.objects.filter(username__startswith='__dc').delete()


def make_consumer(station):
    consumer = OCPPConsumer()
    consumer.station_id = station.id
    consumer.ocpp_id = station.ocpp_id
    consumer._pending_calls = {}
    consumer._sent_actions = {}
    return consumer


class Spy:
    """OCPP buyruqlarini ushlab qoladi — testda haqiqiy charger yo'q."""

    def __init__(self, *names):
        self.calls = []
        self.names = names
        self.originals = {}

    def __enter__(self):
        for name in self.names:
            self.originals[name] = getattr(ocpp_commands, name)
            setattr(ocpp_commands, name, self._record(name))
        return self

    def _record(self, name):
        def inner(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return inner

    def __exit__(self, *exc):
        for name, original in self.originals.items():
            setattr(ocpp_commands, name, original)
        return False

    def names_called(self):
        return [c[0] for c in self.calls]


def main():
    _cleanup()
    settings_obj = SiteSettings.load()
    original_strict = settings_obj.require_known_rfid

    admin = User.objects.create(username='__dc_admin__', is_staff=True, is_superuser=True)
    driver = User.objects.create(username='__dc_driver__')
    station = Station.objects.create(
        name='__dc_station__', address='a', latitude=41.0, longitude=69.0,
        power_kw=120, ocpp_id='__DC_CP__', ocpp_last_seen_at=timezone.now(),
    )
    connector = Connector.objects.create(
        station=station, label='A', type='DC', power_kw=60, ocpp_connector_id=1,
    )
    consumer = make_consumer(station)

    try:
        # ── 1. Ichki idTag'lar tekshirilmaydi ───────────────────
        result = async_to_sync(consumer.on_authorize)({'idTag': f'APP-{driver.id}'})
        check('mobil ilova idTag qabul qilindi',
              result['idTagInfo']['status'] == 'Accepted', result)
        check('ichki idTag karta yaratmadi',
              not RfidCard.objects.filter(id_tag__startswith='APP-').exists())

        # Bo'sh idTag rad etiladi
        empty = async_to_sync(consumer.on_authorize)({'idTag': ''})
        check("bo'sh idTag rad etildi", empty['idTagInfo']['status'] == 'Invalid', empty)

        # ── 2. Noma'lum karta: yumshoq rejim ────────────────────
        settings_obj.require_known_rfid = False
        settings_obj.save()

        res = async_to_sync(consumer.on_authorize)({'idTag': '__DC_NEW__'})
        card = RfidCard.objects.get(id_tag='__DC_NEW__')
        check("noma'lum karta qabul qilindi (yumshoq rejim)",
              res['idTagInfo']['status'] == 'Accepted', res)
        check("karta ro'yxatga tushdi", card.status == RfidCard.Status.PENDING, card.status)
        check('qaysi stansiyada ko\'rilgani yozildi', card.first_seen_station_id == station.id)
        check('ishlatilish sanaldi', card.use_count == 1, card.use_count)
        check('yangi karta jurnalga tushdi',
              ChargerLog.objects.filter(station=station, action='Authorize').exists())

        # ── 3. Qat'iy rejim ────────────────────────────────────
        settings_obj.require_known_rfid = True
        settings_obj.save()

        res = async_to_sync(consumer.on_authorize)({'idTag': '__DC_NEW__'})
        check("qat'iy rejimda tasdiqlanmagan karta rad etildi",
              res['idTagInfo']['status'] == 'Invalid', res)

        card.status = RfidCard.Status.ACTIVE
        card.save(update_fields=['status'])
        res = async_to_sync(consumer.on_authorize)({'idTag': '__DC_NEW__'})
        check('tasdiqlangan karta qabul qilindi',
              res['idTagInfo']['status'] == 'Accepted', res)

        # ── 4. Bloklangan va muddati tugagan ───────────────────
        blocked = RfidCard.objects.create(
            id_tag='__DC_BLOCK__', status=RfidCard.Status.BLOCKED)
        res = async_to_sync(consumer.on_authorize)({'idTag': '__DC_BLOCK__'})
        check('bloklangan karta rad etildi',
              res['idTagInfo']['status'] == 'Blocked', res)

        expired = RfidCard.objects.create(
            id_tag='__DC_EXP__', status=RfidCard.Status.ACTIVE,
            expires_at=timezone.now() - timedelta(days=1))
        res = async_to_sync(consumer.on_authorize)({'idTag': '__DC_EXP__'})
        check('muddati tugagan karta rad etildi',
              res['idTagInfo']['status'] == 'Expired', res)
        check('rad etilgan karta sanoqni oshirmadi',
              RfidCard.objects.get(pk=blocked.pk).use_count == 0)

        # ── 4b. Karta EGASIGA bog'lanadi ───────────────────────
        # Ilgari har RFID sessiyasi karta raqami nomli YANGI foydalanuvchi
        # yaratardi — pul hech kimning hamyonidan yechilmasdi.
        from wallet.models import WalletBalance

        owner = User.objects.create(username='__dc_owner__')
        WalletBalance.objects.create(user=owner, amount=50000)
        owned = RfidCard.objects.create(
            id_tag='__DC_OWNED__', status=RfidCard.Status.ACTIVE, user=owner)

        res = async_to_sync(consumer.on_authorize)({'idTag': '__DC_OWNED__'})
        check('balansi bor karta qabul qilindi',
              res['idTagInfo']['status'] == 'Accepted', res)

        connector.status = Connector.Status.AVAILABLE
        connector.save(update_fields=['status'])
        session = async_to_sync(consumer._start_live_session)(1, '__DC_OWNED__', 0)
        check('sessiya karta egasiga yozildi', session.user_id == owner.id,
              session.user.username)
        check('ortiqcha foydalanuvchi yaratilmadi',
              not User.objects.filter(username='__DC_OWNED__').exists())
        session.delete()

        # Balans tugasa karta ishlamaydi
        WalletBalance.objects.filter(user=owner).update(amount=0)
        res = async_to_sync(consumer.on_authorize)({'idTag': '__DC_OWNED__'})
        check('bo\'sh hamyonli karta rad etildi',
              res['idTagInfo']['status'] == 'Blocked', res)

        # Xizmat kartasida (egasiz) balans tekshirilmaydi
        service = RfidCard.objects.create(
            id_tag='__DC_SERVICE__', status=RfidCard.Status.ACTIVE)
        res = async_to_sync(consumer.on_authorize)({'idTag': '__DC_SERVICE__'})
        check('xizmat kartasi balanssiz ishlaydi',
              res['idTagInfo']['status'] == 'Accepted', res)

        settings_obj.require_known_rfid = False
        settings_obj.save()

        # ── 5. Bron qurilmaga yetkaziladi ──────────────────────
        booking = Booking.objects.create(
            user=driver, station=station, connector=connector,
            scheduled_at=timezone.now() + timedelta(hours=2), duration_minutes=60,
        )
        with Spy('reserve_now') as spy:
            sent = hold_connector(booking)
        booking.refresh_from_db()
        check('bron qurilmaga yuborildi', sent and spy.names_called() == ['reserve_now'],
              spy.names_called())
        check('bron raqami saqlandi', booking.ocpp_reservation_id == booking.id,
              booking.ocpp_reservation_id)
        args = spy.calls[0][1] if spy.calls else ()
        check('bron egasining idTag i uzatildi',
              spy.calls and spy.calls[0][2].get('id_tag') == f'APP-{driver.id}',
              spy.calls and spy.calls[0][2])

        with Spy('cancel_reservation') as spy:
            released = release_connector(booking)
        booking.refresh_from_db()
        check('bron bekor qilindi', released and spy.names_called() == ['cancel_reservation'])
        check('bron raqami tozalandi', booking.ocpp_reservation_id is None)

        # Ulagichsiz bron qurilmaga yuborilmaydi
        loose = Booking.objects.create(
            user=driver, station=station, scheduled_at=timezone.now() + timedelta(hours=3),
            duration_minutes=60,
        )
        with Spy('reserve_now') as spy:
            check('ulagichsiz bron yuborilmadi', hold_connector(loose) is False and not spy.calls)

        # ── 6. "Bron qilingan" holati ──────────────────────────
        async_to_sync(consumer._update_connector_status)(1, 'Reserved', 'NoError')
        connector.refresh_from_db()
        check('Reserved holati o\'girildi',
              connector.status == Connector.Status.RESERVED, connector.status)

        station.refresh_from_db()
        sync_station_status(station)
        station.refresh_from_db()
        check('bron qilingan stansiya "band" bo\'ldi',
              station.status == Station.Status.BUSY, station.status)

        # ── 7. Panel amallari ──────────────────────────────────
        with override_settings(ALLOWED_HOSTS=['testserver']):
            client = Client()
            client.force_login(admin)

            # Quvvat chegarasi
            with Spy('set_charging_profile') as spy:
                client.post(f'/stations/{station.id}/device/{connector.id}/power-limit/',
                            {'limit_kw': '30'})
            connector.refresh_from_db()
            check('chegara qurilmaga yuborildi',
                  spy.names_called() == ['set_charging_profile'], spy.names_called())
            check('chegara saqlandi', connector.power_limit_kw == 30, connector.power_limit_kw)

            with Spy('set_charging_profile') as spy:
                resp = client.post(f'/stations/{station.id}/device/{connector.id}/power-limit/',
                                   {'limit_kw': '999'})
            texts = [str(m) for m in get_messages(resp.wsgi_request)]
            check('haddan ortiq chegara rad etildi',
                  not spy.calls and any('kVt gacha' in t for t in texts), texts)

            with Spy('clear_charging_profile') as spy:
                client.post(f'/stations/{station.id}/device/{connector.id}/power-limit/',
                            {'limit_kw': ''})
            connector.refresh_from_db()
            check('chegara olib tashlandi',
                  spy.names_called() == ['clear_charging_profile']
                  and connector.power_limit_kw is None, connector.power_limit_kw)

            # Proshivka
            with Spy('update_firmware') as spy:
                resp = client.post(f'/stations/{station.id}/device/firmware/',
                                   {'location': 'not-a-url'})
            texts = [str(m) for m in get_messages(resp.wsgi_request)]
            check('yaroqsiz havola rad etildi',
                  not spy.calls and any('boshlanishi kerak' in t for t in texts), texts)

            with Spy('update_firmware') as spy:
                client.post(f'/stations/{station.id}/device/firmware/',
                            {'location': 'https://example.com/fw.bin'})
            check('proshivka buyrug\'i yuborildi',
                  spy.names_called() == ['update_firmware'], spy.names_called())
            check('proshivka jurnalga yozildi',
                  ChargerLog.objects.filter(station=station, action='UpdateFirmware').exists())

            # Diagnostika
            with Spy('get_diagnostics') as spy:
                client.post(f'/stations/{station.id}/device/diagnostics/',
                            {'location': 'ftp://example.com/upload'})
            check('diagnostika so\'raldi', spy.names_called() == ['get_diagnostics'])

            # RFID sahifasi va ro'yxatni yuborish
            body = client.get('/rfid/').content.decode()
            check('RFID sahifasi ochildi', '__DC_NEW__' in body)

            # Ustunlar mosligi — yangi ustun qo'shilsa darhol bilinadi
            import re as _re
            head = body.split('<thead>')[1].split('</thead>')[0]
            rows = body.split('<tbody>')[1].split('</tbody>')[0]
            th = len(_re.findall(r'<th[\s>]', head))
            td = len(_re.findall(r'<td[\s>]', rows.split('</tr>')[0]))
            check('jadval ustunlari mos', th == td, f'th={th} td={td}')

            # Hech narsa topilmaydigan qidiruv — bo'sh holat qatorini ko'ramiz
            empty_body = client.get('/rfid/?q=__HECH_NARSA__').content.decode()
            empty_rows = empty_body.split('<tbody>')[1].split('</tbody>')[0]
            span = _re.search(r'colspan="(\d+)"', empty_rows)
            check("bo'sh holat colspan'i mos",
                  span is not None and int(span.group(1)) == th,
                  span.group(1) if span else 'topilmadi')
            check('qat\'iy rejim ogohlantirishi bor', "Qat'iy rejim o'chiq" in body)

            with Spy('send_local_list') as spy:
                resp = client.post('/rfid/push/', {'station': str(station.id)})
            check('ro\'yxat qurilmaga yuborildi',
                  spy.names_called() == ['send_local_list'], spy.names_called())
            pushed = spy.calls[0][1][2] if spy.calls else []
            tags = {c['idTag'] for c in pushed}
            check('tasdiqlangan karta ro\'yxatga kirdi', '__DC_NEW__' in tags, tags)

            # Tasdiqlanmagan karta qurilmaga yuborilmasligi kerak — aks holda
            # u internet uzilganda ishlab ketardi
            pending = RfidCard.objects.create(
                id_tag='__DC_PEND__', status=RfidCard.Status.PENDING)
            with Spy('send_local_list') as spy2:
                client.post('/rfid/push/', {'station': str(station.id)})
            pushed2 = spy2.calls[0][1][2] if spy2.calls else []
            check('tasdiqlanmagan karta yuborilmadi',
                  '__DC_PEND__' not in {c['idTag'] for c in pushed2},
                  [c['idTag'] for c in pushed2])
            pending.delete()
            check('bloklangan karta holati bilan ketdi',
                  any(c['idTag'] == '__DC_BLOCK__' and c['status'] == 'Blocked' for c in pushed),
                  pushed)

            # Karta holatini o'zgartirish
            client.post(f'/rfid/{blocked.id}/status/', {'status': 'active'})
            blocked.refresh_from_db()
            check('karta tasdiqlandi', blocked.status == RfidCard.Status.ACTIVE)

            # Mijoz sahifasida uning kartasi ko'rinadi
            page = client.get(f'/users/{owner.id}/').content.decode()
            check('mijoz sahifasida karta bor', '__DC_OWNED__' in page)

            # Oflayn charger — buyruq ketmaydi
            station.ocpp_last_seen_at = timezone.now() - timedelta(hours=2)
            station.save(update_fields=['ocpp_last_seen_at'])
            with Spy('set_charging_profile') as spy:
                resp = client.post(f'/stations/{station.id}/device/{connector.id}/power-limit/',
                                   {'limit_kw': '20'})
            texts = [str(m) for m in get_messages(resp.wsgi_request)]
            check('oflayn chargerga buyruq yuborilmadi',
                  not spy.calls and any('oflayn' in t for t in texts), texts)

    finally:
        Booking.objects.filter(station=station).delete()
        User.objects.filter(username='__dc_owner__').delete()
        settings_obj.require_known_rfid = original_strict
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
