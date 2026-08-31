# -*- coding: utf-8 -*-
"""Bildirishnoma shablonlari: matn panelda tahrirlanadi va yuborishda ishlatiladi.

Asosiy savollar:
  1. Standart matnlar o'zi yaratiladimi (operator toza sahifani emas,
     tayyor matnni ko'rishi kerak)?
  2. O'rin egallovchilar haqiqiy qiymatga almashadimi, noma'lumi
     hujjatni buzmaydimi?
  3. Panelda tahrirlangan matn HAQIQIY xabarga tushadimi?
  4. Shablon o'chirilsa xabar umuman yozilmaydimi?
  5. Bo'sh sarlavha/matn saqlanmaydimi?
  6. O'zgarish jurnalga tushadimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.urls import reverse  # noqa: E402
from datetime import timedelta  # noqa: E402

from django.utils import timezone  # noqa: E402

from bookings.models import Booking  # noqa: E402
from management.models import (  # noqa: E402
    NotificationTemplate, SettingsChange, UserNotification,
)
from stations.maintenance import notify_issue, open_issue  # noqa: E402
from stations.models import Connector, Station  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    UserNotification.objects.filter(user__username__startswith='__nt').delete()
    Booking.objects.filter(user__username__startswith='__nt').delete()
    Station.objects.filter(name__startswith='__nt').delete()
    User.objects.filter(username__startswith='__nt').delete()
    SettingsChange.objects.filter(section__startswith='notification:').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    # ── 1. Standart matnlar ─────────────────────────────────────
    NotificationTemplate.objects.all().delete()
    NotificationTemplate.ensure_defaults()
    check('standart matnlar yaratildi',
          NotificationTemplate.objects.count() == len(NotificationTemplate.Event.choices),
          NotificationTemplate.objects.count())

    down = NotificationTemplate.objects.get(
        event=NotificationTemplate.Event.STATION_DOWN)

    # ── 2. O'rin egallovchilar ──────────────────────────────────
    title, body = down.render({'stansiya': 'Chilonzor', 'ulagich': 'A',
                               'sabab': 'kabel uzilgan'})
    check("o'rin egallovchilar almashtirildi",
          title == 'Chilonzor vaqtincha ishlamayapti' and body == 'A: kabel uzilgan',
          f'{title} | {body}')

    down.body = 'Sabab: {sabab}. Noma\'lum: {yoq_bunday}'
    unknown_title, unknown_body = down.render({'sabab': 'ta\'mirlash'})
    check("noma'lum nom o'z holicha qoldi",
          'yoq_bunday' in unknown_body and "ta'mirlash" in unknown_body, unknown_body)

    sample_title, sample_body = NotificationTemplate.objects.get(
        event=NotificationTemplate.Event.CHARGING_COMPLETE).sample()
    check('namuna qiymatlar bilan ko\'rsatiladi',
          'Chilonzor AZS' in sample_body and '24.50' in sample_body, sample_body)

    admin = User.objects.create(username='__nt_admin__', is_staff=True, is_superuser=True)
    try:
        client = Client()
        url = reverse('dashboard:settings_notification')
        check('anonim foydalanuvchiga yopiq',
              client.get(url).status_code in (302, 403))

        client.force_login(admin)
        page = client.get(url).content.decode('utf-8')
        check('matnlar ro\'yxati sahifada',
              'Xabar matnlari' in page and 'Stansiya ishlamay qoldi' in page)
        check('o\'rin egallovchilar ko\'rsatilgan', '{stansiya}' in page)
        check('namuna matn ko\'rinadi', 'Chilonzor AZS' in page)

        # ── 3. Tahrirlangan matn haqiqiy xabarga tushadi ────────
        NotificationTemplate.objects.filter(
            event=NotificationTemplate.Event.STATION_DOWN).update(
                title='{stansiya} — __nt sinov', body='{ulagich}: {sabab} (__nt)')

        station = Station.objects.create(
            name='__nt Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='dc', power_kw=60,
        )
        connector = Connector.objects.create(station=station, label='A', type='ccs2',
                                             power_kw=60)
        driver = User.objects.create(username='__nt_driver__')
        Booking.objects.create(
            user=driver, station=station, connector=connector,
            scheduled_at=timezone.now() + timedelta(hours=2),
            status=Booking.Status.CONFIRMED,
        )

        # `open_issue` (yozuv, yangi_yaratildimi) juftligini qaytaradi
        issue, _created = open_issue(station=station, connector=connector,
                                     reason='kabel uzilgan')
        sent = notify_issue(issue)
        note = UserNotification.objects.filter(user=driver).first()
        check('xabar yuborildi', sent == 1 and note is not None, sent)
        check('panelda yozilgan sarlavha ishlatildi',
              note.title == '__nt Stansiya — __nt sinov', note.title)
        check('panelda yozilgan matn ishlatildi',
              note.body == 'Ulagich A: kabel uzilgan (__nt)', note.body)

        # ── 4. O'chirilgan shablon ──────────────────────────────
        UserNotification.objects.filter(user=driver).delete()
        NotificationTemplate.objects.filter(
            event=NotificationTemplate.Event.STATION_UP).update(is_active=False)
        from stations.maintenance import resolve_issue

        resolve_issue(issue, user=admin)
        sent_up = notify_issue(issue, resolved=True)
        check("o'chirilgan shablon bo'yicha xabar yozilmadi",
              sent_up == 0 and not UserNotification.objects.filter(user=driver).exists(),
              sent_up)

        # ── 5. Panel orqali tahrirlash ──────────────────────────
        template = NotificationTemplate.objects.get(
            event=NotificationTemplate.Event.LOW_BALANCE)
        client.post(reverse('dashboard:notification_template_edit', args=[template.pk]), {
            'title': '__nt Balans', 'body': 'Qoldiq: {balans}', 'is_active': 'on',
        })
        template.refresh_from_db()
        check('matn panel orqali saqlandi',
              template.title == '__nt Balans' and '{balans}' in template.body,
              template.title)
        check('o\'zgarish jurnalga tushdi',
              SettingsChange.objects.filter(section='notification:low_balance').exists())

        client.post(reverse('dashboard:notification_template_edit', args=[template.pk]),
                    {'title': '', 'body': '', 'is_active': 'on'})
        template.refresh_from_db()
        check('bo\'sh matn saqlanmadi', template.title == '__nt Balans', template.title)

        # Hodisa o'zgartirilmaydi — u kodga bog'langan
        client.post(reverse('dashboard:notification_template_edit', args=[template.pk]), {
            'title': '__nt Balans', 'body': 'Qoldiq: {balans}',
            'event': 'station_down', 'is_active': 'on',
        })
        template.refresh_from_db()
        check('hodisa o\'zgartirilmadi',
              template.event == NotificationTemplate.Event.LOW_BALANCE, template.event)

        # ── 6. Standart matnlarni tiklash ───────────────────────
        client.post(reverse('dashboard:notification_templates_reset'))
        restored = NotificationTemplate.objects.get(
            event=NotificationTemplate.Event.LOW_BALANCE)
        check('standart matn tiklandi',
              '__nt' not in restored.title and restored.is_active, restored.title)

    finally:
        NotificationTemplate.objects.all().delete()
        NotificationTemplate.ensure_defaults()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
