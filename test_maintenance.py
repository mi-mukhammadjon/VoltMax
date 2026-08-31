# -*- coding: utf-8 -*-
"""Profilaktika oqimi tekshiruvi.

Asosiy savollar:
  1. Stansiya holati formadan olib tashlandi — u endi qurilmadan hisoblanadimi?
  2. Nosozlik yozuvi avtomatik ochiladimi va takrorlanmaydimi?
  3. Tuzatilganda yozuv yopilib, ulagich xizmatga qaytadimi?
  4. Xabar KIMGA ketadi va ikki marta ketmaydimi?
  5. Mobil API xabarlarni to'g'ri qaytaradimi?
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

from bookings.models import Booking  # noqa: E402
from dashboard.forms import StationForm  # noqa: E402
from management.models import UserNotification  # noqa: E402
from stations.maintenance import (  # noqa: E402
    affected_users,
    notify_issue,
    open_issue,
    sync_issues_from_devices,
)
from stations.models import Connector, MaintenanceIssue, Station  # noqa: E402
from stations.services import sync_station_status  # noqa: E402

failures = 0


def api_client(user):
    """Mobil API faqat JWT bilan ishlaydi — sessiya logini yetmaydi."""
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(user).access_token
    client = Client()
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


def _messages(response):
    """Amaldan keyingi xabarlar matni. Yo'naltirish javobidan o'qiladi —
    `follow=True` bilan kontekst har doim ham tiklanmaydi."""
    from django.contrib.messages import get_messages

    return [str(m) for m in get_messages(response.wsgi_request)]


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:52s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    Station.objects.filter(name__startswith='__mt').delete()
    User.objects.filter(username__startswith='__mt').delete()


def main():
    _cleanup()

    admin = User.objects.create(username='__mt_admin__', is_staff=True, is_superuser=True)
    driver = User.objects.create(username='__mt_driver__')
    stranger = User.objects.create(username='__mt_stranger__')

    station = Station.objects.create(
        name='__mt_station__', address='a', latitude=41.0, longitude=69.0,
        power_kw=60, ocpp_id='__MT_CP__', ocpp_last_seen_at=timezone.now(),
    )
    connector = Connector.objects.create(station=station, label='A', type='DC', power_kw=60,
                                         ocpp_connector_id=1)

    try:
        # ── 1. Forma ────────────────────────────────────────────
        form_html = str(StationForm(instance=station))
        check('formada holat tanlagichi yo\'q', 'name="status"' not in form_html)

        # ── 2. Holat qurilmadan hisoblanadi ─────────────────────
        station.status = Station.Status.AVAILABLE
        station.save(update_fields=['status'])
        station.ocpp_last_seen_at = timezone.now() - timedelta(hours=2)
        station.save(update_fields=['ocpp_last_seen_at'])

        changed = sync_station_status(station)
        station.refresh_from_db()
        check('aloqa yo\'qolsa stansiya oflayn bo\'ldi',
              changed and station.status == Station.Status.OFFLINE, station.status)

        station.ocpp_last_seen_at = timezone.now()
        station.save(update_fields=['ocpp_last_seen_at'])
        sync_station_status(station)
        station.refresh_from_db()
        check('aloqa tiklansa holat ulagichdan olindi',
              station.status == Station.Status.AVAILABLE, station.status)

        # ── 3. Yozuv ochiladi va takrorlanmaydi ─────────────────
        connector.status = Connector.Status.OFFLINE
        connector.offline_reason = 'Ulagich qulfi ishlamayapti'
        connector.save(update_fields=['status', 'offline_reason'])

        result = sync_issues_from_devices()
        check('nosozlik yozuvi ochildi', result['opened'] == 1, result)

        again = sync_issues_from_devices()
        check('takroriy sinxronlash yangi yozuv yaratmadi', again['opened'] == 0, again)

        issue = MaintenanceIssue.objects.get(station=station, connector=connector,
                                             status=MaintenanceIssue.Status.OPEN)
        check('sabab saqlandi', issue.reason == 'Ulagich qulfi ishlamayapti', issue.reason)
        check('nishon nomi to\'g\'ri', issue.target_label == 'Ulagich A', issue.target_label)

        # Sabab aniqlashsa — yozuv yangilanadi, `opened_at` tegilmaydi
        opened_before = issue.opened_at
        open_issue(station=station, connector=connector, reason='Yerga ulanishda nosozlik',
                   error_code='GroundFailure')
        issue.refresh_from_db()
        check('aniqlashgan sabab yangilandi', issue.reason == 'Yerga ulanishda nosozlik')
        check('error_code yozildi', issue.error_code == 'GroundFailure')
        check('boshlanish vaqti o\'zgarmadi', issue.opened_at == opened_before)

        # ── 3b. Xabar oluvchi yo'q holat ────────────────────────
        # Hali hech kimning broni yo'q. Xabar yuborilmasligi kerak, LEKIN
        # yozuv "xabar berilgan" deb belgilanib qolmasligi ham kerak —
        # aks holda keyinroq kimdir bron qilganda ogohlantirib bo'lmasdi.
        check('oluvchisiz xabar yuborilmadi', notify_issue(issue) == 0)
        issue.refresh_from_db()
        check("oluvchisiz belgi qo'yilmadi", issue.notified_at is None)

        with override_settings(ALLOWED_HOSTS=['testserver']):
            panel = Client()
            panel.force_login(admin)
            resp = panel.post(f'/maintenance/{issue.id}/notify/')
            texts = _messages(resp)
            check('birinchi bosishda "allaqachon" demaydi',
                  not any('allaqachon' in t for t in texts), texts)
            check("oluvchi yo'qligi aytildi",
                  any('topilmadi' in t for t in texts), texts)

        # ── 4. Xabar auditoriyasi ───────────────────────────────
        Booking.objects.create(
            user=driver, station=station, scheduled_at=timezone.now() + timedelta(hours=3),
            duration_minutes=60,
        )
        audience = set(affected_users(station).values_list('username', flat=True))
        check('broni borga xabar ketadi', '__mt_driver__' in audience, audience)
        check('begonaga xabar ketmaydi', '__mt_stranger__' not in audience)

        # Doimiy mijoz — oxirgi 30 kunda shu stansiyada zaryadlagan
        from sessions_app.models import ChargingSession

        regular = User.objects.create(username='__mt_regular__')
        old_one = User.objects.create(username='__mt_oldtimer__')
        fresh = ChargingSession.objects.create(
            user=regular, station=station, connector=connector, start_percent=20,
            power_kw=60, price_per_kwh=1500, connector_label='A',
            status=ChargingSession.Status.STOPPED,
        )
        stale = ChargingSession.objects.create(
            user=old_one, station=station, connector=connector, start_percent=20,
            power_kw=60, price_per_kwh=1500, connector_label='A',
            status=ChargingSession.Status.STOPPED,
        )
        # `started_at` — auto_now_add, shuning uchun to'g'ridan-to'g'ri yoziladi
        ChargingSession.objects.filter(pk=stale.pk).update(
            started_at=timezone.now() - timedelta(days=45))

        audience = set(affected_users(station).values_list('username', flat=True))
        check('doimiy mijozga xabar ketadi', '__mt_regular__' in audience, audience)
        check('45 kun oldingi mijoz chiqarildi', '__mt_oldtimer__' not in audience, audience)

        # Panelda oluvchilar soni ko'rinadimi
        with override_settings(ALLOWED_HOSTS=['testserver']):
            panel = Client()
            panel.force_login(admin)
            html = panel.get('/maintenance/').content.decode()

            # Jadvalda FAQAT son turadi — ismlar oynada
            check('jadvalda oluvchilar soni bor', '>2</button>' in html,
                  re.findall(r'link-count[^>]*>(\d+)', html))
            check("jadvalda ismlar yo'q",
                  '__mt_driver__' not in html and '__mt_regular__' not in html)
            check('oyna bloki bor', 'id="recipients-modal"' in html)

            # Ustunlar soni: sarlavha, qator va bo'sh holat mos bo'lishi kerak
            head = html.split('<thead>')[1].split('</thead>')[0]
            body = html.split('<tbody>')[1].split('</tbody>')[0]
            th_count = len(re.findall(r'<th[\s>]', head))
            td_count = len(re.findall(r'<td[\s>]', body.split('</tr>')[0]))
            check('qator ustunlari sarlavhaga mos', th_count == td_count,
                  f'th={th_count} td={td_count}')

            # Bo'sh holat qatorini ham ko'ramiz — mavjud bo'lmagan stansiya
            # bo'yicha filtrlaymiz, shunda jadval bo'sh chiqadi.
            empty_html = panel.get('/maintenance/?station=99999999').content.decode()
            empty_body = empty_html.split('<tbody>')[1].split('</tbody>')[0]
            colspan = re.search(r'colspan="(\d+)"', empty_body)
            check("bo'sh holat colspan'i sarlavhaga mos",
                  colspan is not None and int(colspan.group(1)) == th_count,
                  colspan.group(1) if colspan else 'colspan topilmadi')

            # Ismlar oynasi uchun ma'lumot alohida so'rov bilan keladi
            data = panel.get(f'/maintenance/{issue.id}/recipients/').json()
            names = {r['name'] for r in data['recipients']}
            check("oyna ro'yxatida ismlar bor",
                  '__mt_driver__' in names and '__mt_regular__' in names, names)
            check('oyna sababni ham beradi',
                  all(r['reason'] for r in data['recipients']),
                  [r['reason'] for r in data['recipients']])
            check('oyna stansiyani nomlaydi', data['station'] == station.name, data['station'])

        fresh.delete()
        stale.delete()
        regular.delete()
        old_one.delete()

        sent = notify_issue(issue)
        check('xabar yuborildi', sent == 1, sent)

        again_sent = notify_issue(issue)
        check('ikkinchi marta yuborilmadi', again_sent == 0, again_sent)

        with override_settings(ALLOWED_HOSTS=['testserver']):
            panel = Client()
            panel.force_login(admin)
            resp = panel.post(f'/maintenance/{issue.id}/notify/')
            texts = _messages(resp)
            check('haqiqiy takrorda "allaqachon" chiqdi',
                  any('allaqachon' in t for t in texts), texts)

        note = UserNotification.objects.filter(user=driver).first()
        check('xabar matni stansiyani nomlaydi', note and station.name in note.title, note and note.title)
        check('xabar turi to\'g\'ri', note and note.kind == UserNotification.Kind.STATION_DOWN)
        check('xabar stansiyaga bog\'landi', note and note.station_id == station.id)

        # ── 5. Panel orqali tuzatish ────────────────────────────
        with override_settings(ALLOWED_HOSTS=['testserver']):
            client = Client()
            client.force_login(admin)

            page = client.get('/maintenance/')
            check('profilaktika sahifasi ochildi', page.status_code == 200, page.status_code)
            check('sahifada sabab ko\'rinadi',
                  'Yerga ulanishda nosozlik' in page.content.decode())

            resp = client.post(f'/maintenance/{issue.id}/resolve/', {'note': 'Kabel almashtirildi'})
            check('tuzatish so\'rovi qabul qilindi', resp.status_code == 302, resp.status_code)

        issue.refresh_from_db()
        connector.refresh_from_db()
        check('yozuv yopildi', issue.status == MaintenanceIssue.Status.RESOLVED, issue.status)
        check('kim yopgani saqlandi', issue.resolved_by_id == admin.id)
        check('izoh saqlandi', issue.resolution_note == 'Kabel almashtirildi')
        check('ulagich xizmatga qaytdi', connector.status == Connector.Status.AVAILABLE,
              connector.status)
        check('nosozlik sababi tozalandi', connector.offline_reason == '')

        # Nosozlik haqida xabar bergan edik — tuzatilgani haqida ham aytilishi kerak
        check('tuzatilgani haqida xabar ketdi', issue.resolved_notified_at is not None)
        up = UserNotification.objects.filter(
            user=driver, kind=UserNotification.Kind.STATION_UP
        ).first()
        check('"yana ishlamoqda" xabari yozildi', up is not None, up and up.title)

        # ── 5b. Qurilmaga buyruq ketadimi ───────────────────────
        # ChangeAvailability channel layer orqali ketadi. Testda haqiqiy
        # charger yo'q, shuning uchun buyruq yuboruvchini ushlab qolamiz va
        # HAR BIR yo'l (tezkor tugma, forma, profilaktika) uni chaqirishini
        # tekshiramiz — ilgari forma buni qilmasdi.
        import ocpp_gateway.commands as ocpp_commands

        calls = []
        original = ocpp_commands.change_availability

        def spy(ocpp_id, ocpp_connector_id, operative):
            calls.append((ocpp_id, ocpp_connector_id, operative))

        # `dashboard.views` moduli buyruqni `ocpp_commands.` orqali chaqiradi,
        # shuning uchun modul atributini almashtirish kifoya.
        ocpp_commands.change_availability = spy
        try:
            station.ocpp_last_seen_at = timezone.now()
            station.save(update_fields=['ocpp_last_seen_at'])

            with override_settings(ALLOWED_HOSTS=['testserver']):
                panel = Client()
                panel.force_login(admin)

                # a) Profilaktika: ta'mirga qo'yish
                calls.clear()
                panel.post('/maintenance/open/', {'connector': connector.id, 'reason': 'Kabel'})
                check("ta'mirga qo'yish qurilmaga yetdi",
                      calls == [('__MT_CP__', 1, False)], calls)

                # b) Profilaktika: tuzatildi
                opened = MaintenanceIssue.objects.filter(
                    connector=connector, status=MaintenanceIssue.Status.OPEN).first()
                calls.clear()
                panel.post(f'/maintenance/{opened.id}/resolve/')
                check('tuzatish qurilmaga yetdi',
                      calls == [('__MT_CP__', 1, True)], calls)

                # c) Ulagich sahifasidagi tezkor tugma
                calls.clear()
                panel.post(
                    f'/stations/{station.id}/connectors/{connector.id}/toggle-service/',
                    {'reason': 'Panel orqali'})
                connector.refresh_from_db()
                check('tezkor tugma qurilmaga yetdi',
                      calls == [('__MT_CP__', 1, False)], calls)
                check('tugma holatni ham o\'zgartirdi',
                      connector.status == Connector.Status.OFFLINE, connector.status)

                # d) Xossalar formasi holatga TEGMAYDI
                calls.clear()
                panel.post(f'/stations/{station.id}/connectors/{connector.id}/edit/', {
                    'label': 'A', 'type': 'DC', 'power_kw': '55', 'ocpp_connector_id': '1',
                })
                connector.refresh_from_db()
                check('forma quvvatni saqladi', connector.power_kw == 55, connector.power_kw)
                check('forma holatga tegmadi',
                      connector.status == Connector.Status.OFFLINE, connector.status)
                check('forma qurilmaga buyruq yubormadi', calls == [], calls)

                # e) Charger oflayn bo'lsa — buyruq ketmaydi, ogohlantiriladi
                station.ocpp_last_seen_at = timezone.now() - timedelta(hours=2)
                station.save(update_fields=['ocpp_last_seen_at'])
                calls.clear()
                resp = panel.post(
                    f'/stations/{station.id}/connectors/{connector.id}/toggle-service/')
                texts = _messages(resp)
                check('oflayn chargerga buyruq yuborilmadi', calls == [], calls)
                check('oflayn holat haqida ogohlantirildi',
                      any('oflayn' in t for t in texts), texts)
        finally:
            ocpp_gateway_restore = original
            ocpp_commands.change_availability = ocpp_gateway_restore
            station.ocpp_last_seen_at = timezone.now()
            station.save(update_fields=['ocpp_last_seen_at'])

        # ── 6. Mobil API ────────────────────────────────────────
        with override_settings(ALLOWED_HOSTS=['testserver']):
            client = api_client(driver)

            data = client.get('/api/notifications/').json()
            rows = data.get('results', data)
            check('API xabarlarni qaytardi', len(rows) == 2, len(rows))
            check('API o\'qilmaganlar sonini berdi', data.get('unread') == 2, data.get('unread'))
            check('API camelCase ishlatadi', 'createdAt' in rows[0], list(rows[0])[:4])

            client.post('/api/notifications/read-all/')
            data = client.get('/api/notifications/').json()
            check('o\'qilgan deb belgilandi', data.get('unread') == 0, data.get('unread'))

            # Begona foydalanuvchi boshqaning xabarini ko'rmasin
            rows = api_client(stranger).get('/api/notifications/').json()
            check('begona xabarlarni ko\'rmadi', len(rows.get('results', rows)) == 0)

    finally:
        Booking.objects.filter(station=station).delete()
        UserNotification.objects.filter(user__username__startswith='__mt').delete()
        MaintenanceIssue.objects.filter(station=station).delete()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
