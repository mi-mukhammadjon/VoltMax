# -*- coding: utf-8 -*-
"""Sahifalar nechta so'rov qilishini o'lchaydi.

Sekinlik asta-sekin kirib keladi va uni hech kim payqamaydi: bugun
bitta `annotate` unutiladi, ertaga ro'yxatga ustun qo'shiladi — va
o'n qatorlik jadval yuzta so'rov qiladi. Panel ishlab turadi, faqat
sekin; sekinlik esa xato emas, shuning uchun hech kim shikoyat
qilmaydi ham.

Bu yerda har sahifaga CHEGARA qo'yilgan. Chegara aniq son emas,
YUQORI CHEK: undan oshsa nimadir noto'g'ri qilingan.

Eng muhimi: ro'yxatlarda so'rovlar soni QATORLAR SONIGA BOG'LIQ
BO'LMASLIGI kerak. Bu N+1 ning ta'rifi va u faqat ma'lumot ko'payganda
seziladi — ya'ni ishlab chiqishda emas, serverda.
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.db import connection, reset_queries  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402

from accounts.models import RfidCard  # noqa: E402
from stations.models import Connector, Station  # noqa: E402

failures = 0

# (manzil, chegara). Chegara mavjud holatdan biroz yuqori olingan:
# maqsad o'sishni ushlash, har o'zgarishda sinovni tuzatish emas.
BUDGETS = [
    ('/', 26),
    ('/stations/', 26),
    ('/sessions/', 22),
    ('/users/', 16),
    ('/rfid/', 30),
    ('/companies/', 22),
    ('/managers/', 14),
    ('/system/', 26),
    ('/profile/', 16),
]


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    Connector.objects.filter(station__name__startswith='__qb').delete()
    Station.objects.filter(name__startswith='__qb').delete()
    RfidCard.objects.filter(id_tag__startswith='__QB').delete()
    User.objects.filter(username__startswith='__qb').delete()


def count_queries(client, url):
    reset_queries()
    response = client.get(url)
    return response.status_code, len(connection.queries)


@override_settings(ALLOWED_HOSTS=['testserver'], DEBUG=True)
def main():
    _cleanup()

    admin = User.objects.filter(is_superuser=True, is_active=True).first()
    if admin is None:
        print('Administrator topilmadi — sinov o\'tkazib yuborildi')
        return 0

    client = Client()
    client.force_login(admin)

    try:
        # ── 1. Har sahifaning chegarasi ─────────────────────────
        for url, budget in BUDGETS:
            # Birinchi ochilish keshlarni to'ldiradi (sozlamalar, narx
            # katalogi) — o'lchash IKKINCHISIDA
            client.get(url)
            status, count = count_queries(client, url)
            check(f'{url}', status == 200 and count <= budget,
                  f'{count} ta (chegara {budget})')

        # ── 2. Ro'yxatlar qatorlar soniga bog'liq emas ──────────
        # Bu N+1 ning ta'rifi: u faqat ma'lumot ko'payganda seziladi,
        # ya'ni ishlab chiqishda emas, serverda.
        growth_pages = {
            '/stations/': 'stansiyalar',
            '/users/': 'mijozlar',
            '/rfid/': 'kartalar',
        }
        before = {}
        for url in growth_pages:
            client.get(url)
            before[url] = count_queries(client, url)[1]

        for index in range(10):
            station = Station.objects.create(
                name=f'__qb Stansiya {index}', address='a', latitude=41.0,
                longitude=69.0, charger_type='DC', power_kw=60)
            Connector.objects.create(station=station, label='A', type='ccs2',
                                     power_kw=60)
            person = User.objects.create(username=f'__qb_mijoz{index}__')
            RfidCard.objects.create(id_tag=f'__QB{index}__', user=person)

        for url, name in growth_pages.items():
            client.get(url)
            after = count_queries(client, url)[1]
            # Bir-ikki so'rov farq qilishi mumkin (sahifalash, jami
            # sanoq), lekin O'NTA qator o'nta so'rov qo'shmasligi kerak
            check(f'{name}: o\'nta qator so\'rovni oshirmadi',
                  after <= before[url] + 2, f'{before[url]} -> {after}')

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
