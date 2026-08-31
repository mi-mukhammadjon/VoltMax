# -*- coding: utf-8 -*-
"""Hisobotlarni faylga yuklab olish.

Panel raqamlarni ekranda ko'rsatadi, buxgalteriya esa ular bilan
ishlaydi. Ekrandan ko'chirib olish xatoga olib keladi.

Asosiy savollar:
  1. Uch xil kesim (kunlik, stansiyalar, sessiyalar) to'g'ri chiqadimi?
  2. Fayl Excel'da to'g'ri ochiladimi — BOM va nuqta-vergul bormi?
  3. Sonlar SON bo'lib chiqadimi (formatlangan matn Excel'da yig'ilmaydi)?
  4. Davr chegarasi hurmat qilinadimi (30 kun so'ralsa 90 kunlik ma'lumot
     tushib ketmasligi kerak)?
  5. Yuklab olish amallar jurnaliga tushadimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from management.models import ActivityLog  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Station  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    ChargingSession.objects.filter(station__name__startswith='__ex').delete()
    ActivityLog.objects.filter(title__contains='__ex').delete()
    Station.objects.filter(name__startswith='__ex').delete()
    User.objects.filter(username__startswith='__ex').delete()
    User.objects.filter(username='998900000199').delete()


def body_of(response):
    payload = (b''.join(response.streaming_content)
               if response.streaming else response.content)
    return payload.decode('utf-8')


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    admin = User.objects.create(username='__ex_admin__', is_staff=True, is_superuser=True)
    try:
        # Raqamli login — formatlash tekshiruvi uchun. Bazadagi haqiqiy
        # foydalanuvchi bilan to'qnashmasligi kerak
        driver, _ = User.objects.get_or_create(username='998900000199')
        station = Station.objects.create(
            name='__ex Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='dc', power_kw=60)
        connector = Connector.objects.create(station=station, label='A',
                                             type='ccs2', power_kw=60)

        now = timezone.now()
        recent = ChargingSession.objects.create(
            user=driver, station=station, connector=connector, start_percent=20,
            power_kw=60, price_per_kwh=1200, connector_label='A',
            status=ChargingSession.Status.COMPLETED,
            final_kwh_charged=12.5, final_cost=17500, final_parking_cost=2500,
            final_parking_minutes=5)
        ChargingSession.objects.filter(pk=recent.pk).update(
            started_at=now - timedelta(days=2), stopped_at=now - timedelta(days=2))

        old = ChargingSession.objects.create(
            user=driver, station=station, connector=connector, start_percent=20,
            power_kw=60, price_per_kwh=1200, connector_label='A',
            status=ChargingSession.Status.COMPLETED,
            final_kwh_charged=100.0, final_cost=120000)
        ChargingSession.objects.filter(pk=old.pk).update(
            started_at=now - timedelta(days=60), stopped_at=now - timedelta(days=60))

        client = Client()
        url = reverse('dashboard:report_export', args=['sessions'])
        check('anonim foydalanuvchiga yopiq',
              client.get(url).status_code in (302, 403))

        client.force_login(admin)

        # ── 1. Sessiyalar kesimi ────────────────────────────────
        response = client.get(url, {'days': 30})
        text = body_of(response)
        check('CSV qaytdi', 'text/csv' in response['Content-Type'], response['Content-Type'])
        check('fayl nomida davr bor',
              'sessiyalar-30kun' in response.get('Content-Disposition', ''),
              response.get('Content-Disposition'))

        # Excel uchun ikki nozik joy
        check('BOM bor (Excel UTF-8 ni shundan biladi)', text.startswith('﻿'))
        # BOM konsolda chiqmasin — u faqat fayl uchun
        first_line = text.splitlines()[0].lstrip('﻿')
        check('ajratgich nuqta-vergul', ';' in first_line, first_line[:40])

        lines = text.strip().splitlines()
        check('sarlavha qatori bor', 'Stansiya' in first_line and 'Jami' in first_line)
        check('davr ichidagi sessiya kirdi',
              any('__ex Stansiya' in line for line in lines[1:]))
        check('davrdan tashqaridagi sessiya kirmadi',
              not any('120000' in line for line in lines[1:]),
              [line for line in lines[1:] if '120000' in line])

        row = [line for line in lines[1:] if '__ex Stansiya' in line][0]
        parts = row.split(';')
        check('foydalanuvchi raqami formatlangan',
              '+998 (90) 000-01-99' in row, parts[3])
        check('energiya son bo\'lib chiqdi (matn emas)', '12.5' in row, parts[6])
        check('summalar ajratgichsiz son',
              '15000' in row and '2500' in row and '17500' in row, row)

        # ── 2. Boshqa kesimlar ──────────────────────────────────
        daily = body_of(client.get(reverse('dashboard:report_export', args=['revenue']),
                                   {'days': 30}))
        check('kunlik kesimda sana bor', 'Sana' in daily.splitlines()[0])
        check('kunlik kesimda tushum bor', '17500' in daily, daily.splitlines()[-1][:60])

        stations = body_of(client.get(reverse('dashboard:report_export', args=['stations']),
                                      {'days': 30}))
        check('stansiyalar kesimida nom bor', '__ex Stansiya' in stations)

        # ── 3. Noma'lum kesim ───────────────────────────────────
        unknown = client.get(reverse('dashboard:report_export', args=['yoq-bunday']))
        check('noma\'lum hisobot rad etildi',
              unknown.status_code == 302, unknown.status_code)

        # ── 4. Jurnalga tushdi ──────────────────────────────────
        check('yuklab olish jurnalga yozildi',
              ActivityLog.objects.filter(title__contains='Hisobot yuklab olindi').exists())

        # ── 5. Sahifadagi tugmalar ──────────────────────────────
        page = client.get(reverse('dashboard:reports_revenue')).content.decode('utf-8')
        check('hisobot sahifasida uch tugma bor',
              page.count('report/export') + page.count('reports/export') == 3,
              page.count('reports/export'))
        check('tugmalar AJAX qatlamidan chetlab o\'tadi',
              page.count('data-no-ajax') >= 3)

    finally:
        ActivityLog.objects.filter(title__contains='Hisobot yuklab olindi').delete()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
