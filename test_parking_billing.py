# -*- coding: utf-8 -*-
"""Parkovkaning daqiqalik hisob-kitobini tekshiradi.

Asosiy savol: pul to'g'ri, o'z vaqtida va IKKI MARTA EMAS yechiladimi.
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.utils import timezone  # noqa: E402

from sessions_app.models import ChargingSession  # noqa: E402
from sessions_app.parking import bill_parking  # noqa: E402
from stations.models import Connector, Station  # noqa: E402
from wallet.models import Transaction, WalletBalance  # noqa: E402

FEE = 500  # so'm/daqiqa

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:44s} {extra}')
    if not condition:
        failures += 1


def make_world(balance):
    driver = User.objects.create(username='__pk_driver__')
    WalletBalance.objects.create(user=driver, amount=balance)
    station = Station.objects.create(
        name='__pk_station__', address='a', latitude=41.0, longitude=69.0,
        power_kw=60, discount_price_per_kwh=1000,
    )
    connector = Connector.objects.create(station=station, label='A', type='DC', power_kw=60)
    session = ChargingSession.objects.create(
        user=driver, station=station, connector=connector, start_percent=50,
        power_kw=60, price_per_kwh=1000, connector_label='A', parking_fee_per_min=FEE,
    )
    return driver, station, connector, session


def set_parking(connector, minutes):
    """Parkovka `minutes` daqiqa oldin boshlangan holatga keltiradi."""
    connector.status = Connector.Status.CHARGING
    connector.parking_started_at = timezone.now() - timedelta(minutes=minutes, seconds=5)
    connector.save(update_fields=['status', 'parking_started_at'])
    connector.__dict__.pop('parking_since', None)
    connector.__dict__.pop('active_session', None)


def balance(user):
    return WalletBalance.objects.get(user=user).amount


def cleanup(driver, station):
    ChargingSession.objects.filter(station=station).delete()
    Transaction.objects.filter(user=driver).delete()
    station.delete()
    driver.delete()


def _clear_leftovers():
    """Oldingi uzilgan yugurishdan qolgan test yozuvlarini tozalaydi."""
    from django.contrib.auth.models import User
    from stations.models import Station

    Station.objects.filter(name__startswith='__').delete()
    User.objects.filter(username__startswith='__').delete()


def main():
    _clear_leftovers()

    # Imtiyoz vaqti sozlamada turadi va bazada har xil bo'lishi mumkin —
    # test uni O'ZI belgilaydi, aks holda natija muhitga bog'liq bo'lardi
    from management.models import SiteSettings

    settings_obj = SiteSettings.load()
    saved_grace = settings_obj.parking_grace_minutes
    settings_obj.parking_grace_minutes = 0
    settings_obj.save(update_fields=['parking_grace_minutes'])

    # ── 1. Oddiy oqim: 10 daqiqa parkovka ─────────────────────
    driver, station, connector, session = make_world(balance=100000)
    set_parking(connector, 10)

    result = bill_parking()
    session.refresh_from_db()
    check('10 daqiqa hisoblandi', result['minutes'] == 10, f"-> {result['minutes']}")
    check('5 000 so\'m yechildi', result['charged'] == 10 * FEE, f"-> {result['charged']}")
    check('hamyondan yechildi', balance(driver) == 100000 - 5000, f'-> {balance(driver)}')
    check('hisob qaydi yozildi', session.parking_billed_minutes == 10)
    check('tranzaksiya yaratildi',
          Transaction.objects.filter(user=driver, description__contains='parkovka').count() == 1)

    # ── 2. Darhol qayta chaqirish — ikki marta yechilmasin ────
    before = balance(driver)
    result = bill_parking()
    check('takroriy chaqiruvda yechilmadi', result['charged'] == 0 and balance(driver) == before,
          f"-> {result['charged']}")

    # ── 3. Yana 5 daqiqa o'tdi — faqat farq yechilsin ─────────
    set_parking(connector, 15)
    result = bill_parking()
    session.refresh_from_db()
    check('faqat yangi 5 daqiqa yechildi', result['minutes'] == 5 and result['charged'] == 2500,
          f"-> {result['minutes']} daq / {result['charged']}")
    check('jami 15 daqiqa hisoblandi', session.parking_billed_minutes == 15)
    check('hamyon 92 500', balance(driver) == 100000 - 7500, f'-> {balance(driver)}')

    # ── 4. Sessiya tugaganda ikki marta yechilmasin ───────────
    paid_so_far = 7500
    session.refresh_from_db()
    energy = session.energy_cost
    before_stop = balance(driver)
    session.stop()
    session.refresh_from_db()

    check('final_cost umumiy summani ko\'rsatadi',
          session.final_cost == energy + 15 * FEE, f'-> {session.final_cost}')
    check('final_parking_cost = 7 500', session.final_parking_cost == 7500, f'-> {session.final_parking_cost}')
    expected = before_stop - (session.final_cost - paid_so_far)
    check('stop() faqat qolgan farqni yechdi', balance(driver) == max(0, expected),
          f'-> {balance(driver)} (kutilgan {max(0, expected)})')

    total_deducted = 100000 - balance(driver)
    check('jami yechilgan = final_cost', total_deducted == session.final_cost,
          f'-> {total_deducted} / {session.final_cost}')

    # Ledger balans bilan mos kelishi shart: tranzaksiyalar yig'indisi
    # hamyondan yechilgan miqdorga teng bo'lishi kerak.
    ledger = sum(
        t.amount for t in Transaction.objects.filter(user=driver, type='charge_payment')
    )
    check("tranzaksiyalar yigindisi = yechilgan summa", ledger == total_deducted,
          f'-> ledger {ledger} / yechilgan {total_deducted}')

    cleanup(driver, station)

    # ── 5. Hamyonda pul yetmasa ───────────────────────────────
    driver, station, connector, session = make_world(balance=1200)   # 2 daqiqaga ham yetmaydi
    set_parking(connector, 10)
    result = bill_parking()
    session.refresh_from_db()

    check('bori yechildi (1 200)', result['charged'] == 1200, f"-> {result['charged']}")
    check('yetmagani qayd etildi', result['unpaid'] == 10 * FEE - 1200, f"-> {result['unpaid']}")
    check('hamyon nolga tushdi, minusga ketmadi', balance(driver) == 0, f'-> {balance(driver)}')
    check('daqiqalar baribir hisoblandi', session.parking_billed_minutes == 10)

    result = bill_parking()
    check('pul yo\'q holatda takror urinilmadi', result['minutes'] == 0, f"-> {result['minutes']}")

    cleanup(driver, station)

    # ── 6. Parkovka rejimida bo'lmagan sessiya tegilmasin ─────
    driver, station, connector, session = make_world(balance=50000)
    connector.status = Connector.Status.CHARGING
    connector.save(update_fields=['status'])          # parking_started_at yo'q
    result = bill_parking()
    check('oddiy zaryadlashdan pul yechilmadi', result['sessions'] == 0 and balance(driver) == 50000)
    cleanup(driver, station)

    # ── 5. Imtiyoz vaqti: birinchi daqiqalar bepul ────────────
    # Zaryad tugagach avtomobilni darhol olib ketish har doim mumkin emas
    settings_obj.parking_grace_minutes = 10
    settings_obj.save(update_fields=['parking_grace_minutes'])

    driver, station, connector, session = make_world(balance=100000)
    set_parking(connector, 8)
    result = bill_parking()
    check('imtiyoz ichida pul yechilmadi',
          result['charged'] == 0 and balance(driver) == 100000, f"-> {result['charged']}")

    set_parking(connector, 25)
    result = bill_parking()
    check('imtiyozdan keyingi daqiqalar hisoblandi',
          result['minutes'] == 15 and result['charged'] == 15 * FEE,
          f"-> {result['minutes']} daq / {result['charged']}")
    cleanup(driver, station)

    settings_obj.parking_grace_minutes = saved_grace
    settings_obj.save(update_fields=['parking_grace_minutes'])

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
