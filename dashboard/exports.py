# -*- coding: utf-8 -*-
"""Hisobotlarni faylga yuklab olish (CSV).

Panel raqamlarni ekranda ko'rsatadi, buxgalteriya esa ular bilan ISHLAYDI:
o'z jadvalida guruhlaydi, boshqa manbalar bilan solishtiradi, hisobotga
qo'shadi. Ekrandan ko'chirib olish esa xatoga olib keladi.

Nima uchun CSV, `.xlsx` emas: Excel CSV'ni bemalol ochadi, qo'shimcha
kutubxona kerak emas va fayl har qanday dasturda o'qiladi. Ikki nozik
joyi bor va ikkalasi ham hisobga olingan:

  * **BOM** — Excel faylni UTF-8 ekanini shundan biladi, aks holda
    o'zbekcha harflar buziladi;
  * **nuqta-vergul** — o'nlik ajratgichi vergul bo'lgan tizimda Excel
    vergulli CSV'ni bitta ustunga tiqib qo'yadi.
"""

import csv
from io import StringIO

from django.http import HttpResponse
from django.utils import timezone

BOM = '﻿'
DELIMITER = ';'


def csv_response(filename, header, rows):
    """Qatorlardan CSV javob yasaydi.

    `rows` — ro'yxatlar ketma-ketligi. Sonlar o'z holicha yoziladi:
    formatlangan matn (`123 000.00`) Excel'da son emas, matn bo'lib
    tushardi va uni yig'ib bo'lmasdi.
    """
    buffer = StringIO()
    buffer.write(BOM)
    writer = csv.writer(buffer, delimiter=DELIMITER, lineterminator='\r\n')
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)

    stamp = timezone.localdate().strftime('%Y%m%d')
    response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}-{stamp}.csv"'
    return response


def revenue_rows(days):
    """Kunlik tushum: sana, sessiyalar soni, energiya, summa."""
    from datetime import timedelta

    from django.db.models import Count, Sum
    from django.db.models.functions import TruncDate

    from sessions_app.models import ChargingSession

    start = timezone.localdate() - timedelta(days=days - 1)
    rows = (ChargingSession.objects
            .filter(started_at__date__gte=start)
            .exclude(status=ChargingSession.Status.CHARGING)
            .annotate(day=TruncDate('started_at'))
            .values('day')
            .annotate(count=Count('id'),
                      kwh=Sum('final_kwh_charged'),
                      revenue=Sum('final_cost'))
            .order_by('day'))

    return [
        [f"{r['day']:%d.%m.%Y}", r['count'], round(r['kwh'] or 0, 2), r['revenue'] or 0]
        for r in rows
    ]


def station_rows(days):
    """Stansiyalar kesimi: nomi, sessiyalar, energiya, tushum."""
    from datetime import timedelta

    from django.db.models import Count, Sum

    from sessions_app.models import ChargingSession

    start = timezone.localdate() - timedelta(days=days - 1)
    rows = (ChargingSession.objects
            .filter(started_at__date__gte=start)
            .exclude(status=ChargingSession.Status.CHARGING)
            .values('station__name')
            .annotate(count=Count('id'),
                      kwh=Sum('final_kwh_charged'),
                      revenue=Sum('final_cost'))
            .order_by('-revenue'))

    return [
        [r['station__name'] or '—', r['count'], round(r['kwh'] or 0, 2), r['revenue'] or 0]
        for r in rows
    ]


def session_rows(days):
    """Sessiyalar ro'yxati — eng batafsil kesim.

    Buxgalteriya odatda shuni so'raydi: har bir sessiya, kim, qayerda,
    qancha energiya va qancha pul.
    """
    from datetime import timedelta

    from sessions_app.models import ChargingSession

    start = timezone.localdate() - timedelta(days=days - 1)
    rows = (ChargingSession.objects
            .filter(started_at__date__gte=start)
            .exclude(status=ChargingSession.Status.CHARGING)
            .select_related('station', 'user')
            .order_by('started_at'))

    from dashboard.phones import format_phone

    return [
        [
            session.pk,
            f'{timezone.localtime(session.started_at):%d.%m.%Y %H:%M}',
            f'{timezone.localtime(session.stopped_at):%d.%m.%Y %H:%M}'
            if session.stopped_at else '',
            format_phone(session.user.username) if session.user else '',
            session.station.name if session.station else '',
            session.connector_label or '',
            round(session.kwh_charged or 0, 2),
            session.energy_cost or 0,
            session.parking_cost or 0,
            session.final_cost or 0,
            session.get_status_display(),
        ]
        for session in rows
    ]


REPORTS = {
    'revenue': {
        'filename': 'tushum',
        'header': ['Sana', 'Sessiyalar', 'Energiya (kVt·s)', "Tushum (so'm)"],
        'rows': revenue_rows,
    },
    'stations': {
        'filename': 'stansiyalar',
        'header': ['Stansiya', 'Sessiyalar', 'Energiya (kVt·s)', "Tushum (so'm)"],
        'rows': station_rows,
    },
    'sessions': {
        'filename': 'sessiyalar',
        'header': ['№', 'Boshlandi', 'Tugadi', 'Foydalanuvchi', 'Stansiya', 'Ulagich',
                   'Energiya (kVt·s)', "Energiya (so'm)", "Parkovka (so'm)",
                   "Jami (so'm)", 'Holat'],
        'rows': session_rows,
    },
}
