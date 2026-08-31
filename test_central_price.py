# -*- coding: utf-8 -*-
"""Markazlashgan narx tekshiruvi.

Asosiy savol: Sozlamalar > To'lov dagi standart narx o'zgarsa, u haqiqatan
hamma joyga (API, panel, yangi sessiya, bron) tarqaladimi.
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402

from management.models import SiteSettings  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Station  # noqa: E402
from wallet.models import WalletBalance  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:46s} {extra}')
    if not condition:
        failures += 1


def _clear_leftovers():
    """Oldingi uzilgan yugurishdan qolgan test yozuvlarini tozalaydi."""
    from django.contrib.auth.models import User
    from stations.models import Station

    Station.objects.filter(name__startswith='__').delete()
    User.objects.filter(username__startswith='__').delete()


def main():
    _clear_leftovers()

    settings_obj = SiteSettings.load()
    original_standard = settings_obj.default_price_per_kwh

    admin, _ = User.objects.get_or_create(
        username='__cp_admin__', defaults={'is_staff': True, 'is_superuser': True}
    )
    admin.is_staff = admin.is_superuser = True
    admin.save()
    driver, _ = User.objects.get_or_create(username='__cp_driver__')
    WalletBalance.objects.update_or_create(user=driver, defaults={'amount': 500000})

    # Ikkita stansiya: biri standart narxda, ikkinchisi o'z chegirmasi bilan
    plain = Station.objects.create(
        name='__cp_plain__', address='a', latitude=41.0, longitude=69.0, power_kw=60,
    )
    discounted = Station.objects.create(
        name='__cp_discount__', address='b', latitude=41.1, longitude=69.1, power_kw=60,
        discount_price_per_kwh=900,
    )
    connector = Connector.objects.create(station=plain, label='A', type='DC', power_kw=60)

    try:
        # ── 1. Standart narxni o'zgartiramiz ──────────────────
        settings_obj.default_price_per_kwh = 2000
        settings_obj.save()

        plain.refresh_from_db()
        discounted.refresh_from_db()

        check('chegirmasiz stansiya yangi narxga o\'tdi', plain.price_per_kwh == 2000,
              f'-> {plain.price_per_kwh}')
        check('o\'z narxi bor stansiya o\'zgarmadi', discounted.price_per_kwh == 900,
              f'-> {discounted.price_per_kwh}')
        check('chegirma aniqlandi', discounted.has_discount is True)
        check('chizib ko\'rsatiladigan narx = standart',
              discounted.original_price_per_kwh == 2000, f'-> {discounted.original_price_per_kwh}')
        check('chegirmasizda chizilgan narx yo\'q', plain.original_price_per_kwh is None)

        # ── 2. Mobil API ham shu narxni beradi ────────────────
        with override_settings(ALLOWED_HOSTS=['testserver']):
            client = Client()
            client.force_login(driver)
            rows = client.get('/api/stations/').json()
            rows = rows.get('results', rows)
            by_name = {r['name']: r for r in rows}

            check('API: chegirmasiz stansiya', by_name['__cp_plain__']['pricePerKwh'] == 2000,
                  f"-> {by_name['__cp_plain__']['pricePerKwh']}")
            check('API: chegirmali stansiya', by_name['__cp_discount__']['pricePerKwh'] == 900)
            check('API: originalPricePerKwh = standart',
                  by_name['__cp_discount__']['originalPricePerKwh'] == 2000)
            check('API: chegirmasizda original = null',
                  by_name['__cp_plain__']['originalPricePerKwh'] is None)

            # ── 3. Panel sahifasi ─────────────────────────────
            client.force_login(admin)
            html = client.get('/stations/').content.decode()
            # Shablon ming ajratgichi sifatida uzuluvchi bo'lmagan bo'shliq chiqaradi
            check("panel royxatida yangi narx", "2 000.00" in html)

            html = client.get(f'/stations/{plain.id}/').content.decode()
            check('stansiya detalida manba ko\'rsatilgan',
                  'Sozlamalardagi standart narx' in html)

            # ── 4. Yangi stansiya formasi standart narx so'ramaydi ──
            html = client.get('/stations/new/').content.decode()
            check('formada standart narx maydoni yo\'q',
                  'name="price_per_kwh"' not in html and 'name="original_price_per_kwh"' not in html)
            check('formada chegirma maydoni bor', 'name="discount_price_per_kwh"' in html)
            check('formada joriy standart eslatildi', '2 000' in html or '2000' in html)

        # ── 5. Yangi sessiya narxni suratga oladi ─────────────
        session = ChargingSession.objects.create(
            user=driver, station=plain, connector=connector, start_percent=10,
            power_kw=60, price_per_kwh=plain.price_per_kwh, connector_label='A',
        )
        check('sessiya joriy narxni oldi', session.price_per_kwh == 2000)

        # Narx keyin o'zgarsa, boshlangan sessiya tegilmasin
        settings_obj.default_price_per_kwh = 3000
        settings_obj.save()
        session.refresh_from_db()
        plain.refresh_from_db()
        check('boshlangan sessiya narxi muzlatilgan', session.price_per_kwh == 2000)
        check('stansiya esa yangi narxda', plain.price_per_kwh == 3000, f'-> {plain.price_per_kwh}')

    finally:
        ChargingSession.objects.filter(user=driver).delete()
        plain.delete()
        discounted.delete()
        driver.delete()
        admin.delete()
        settings_obj.default_price_per_kwh = original_standard
        settings_obj.save()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
