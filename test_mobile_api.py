# -*- coding: utf-8 -*-
"""Mobil ilova ishlatadigan API.

Panel puxta sinovdan o'tgan, ilova ishlatadigan API esa deyarli emas edi:
31 ta manzildan 17 tasi birorta testda uchramasdi. Backend'da bir maydon
nomini o'zgartirsak, buni faqat telefonda ochib ko'rgandan keyin bilib
qolardik.

Bu test ilovaning HAQIQIY oqimini takrorlaydi: profil, mashinalar,
stansiyalar, sessiya, hamyon, bronlar, xabarlar va kartalar.

Asosiy savollar:
  1. Har bir manzil ishlaydimi va ilova kutgan MAYDONLARNI qaytaradimi?
  2. Begona ma'lumot ko'rinmaydimi (boshqa odamning sessiyasi, hamyoni)?
  3. Tizimga kirmagan foydalanuvchi rad etiladimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from accounts.models import RfidCard, Vehicle  # noqa: E402
from bookings.models import Booking  # noqa: E402
from management.models import SiteSettings, UserNotification  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Review, Station  # noqa: E402
from wallet.models import Transaction, WalletBalance  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    ChargingSession.objects.filter(station__name__startswith='__mb').delete()
    Booking.objects.filter(station__name__startswith='__mb').delete()
    Review.objects.filter(station__name__startswith='__mb').delete()
    UserNotification.objects.filter(user__username__startswith='__mb').delete()
    RfidCard.objects.filter(id_tag__startswith='__MB').delete()
    Vehicle.objects.filter(user__username__startswith='__mb').delete()
    Transaction.objects.filter(user__username__startswith='__mb').delete()
    from management.models import Offer

    Offer.objects.filter(title__startswith='__mb').delete()
    Station.objects.filter(name__startswith='__mb').delete()
    User.objects.filter(username__startswith='__mb').delete()


def api(user):
    client = Client()
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {RefreshToken.for_user(user).access_token}'
    return client


def rows(payload):
    """DRF sahifalangan javobdan ro'yxatni oladi."""
    return payload.get('results', payload) if isinstance(payload, dict) else payload


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f) for f in ('min_balance_to_start', 'work_all_day')}
    try:
        settings_obj.min_balance_to_start = 0
        settings_obj.work_all_day = True
        settings_obj.save()

        driver = User.objects.create(username='__mb_driver__', first_name='Doniyor')
        stranger = User.objects.create(username='__mb_stranger__')
        WalletBalance.objects.create(user=driver, amount=75000)
        WalletBalance.objects.create(user=stranger, amount=1000)

        station = Station.objects.create(
            name='__mb Stansiya', address='Chilonzor', latitude=41.0, longitude=69.0,
            charger_type='dc', power_kw=60)
        connector = Connector.objects.create(
            station=station, label='A', type='ccs2', power_kw=60,
            status=Connector.Status.AVAILABLE)

        me = api(driver)
        anon = Client()

        # ── 1. Profil ───────────────────────────────────────────
        check('tizimga kirmagan rad etildi',
              anon.get('/api/auth/profile/').status_code in (401, 403))

        profile = me.get('/api/auth/profile/')
        check('profil qaytdi', profile.status_code == 200, profile.status_code)
        check('profilda ism va telefon bor',
              'name' in profile.json() and 'phone' in profile.json(), profile.json())

        updated = me.patch('/api/auth/profile/', {'name': 'Doniyor A.'},
                           content_type='application/json')
        driver.refresh_from_db()
        check('ism yangilandi',
              updated.status_code == 200 and driver.first_name == 'Doniyor A.',
              driver.first_name)

        # ── 2. Mashinalar ───────────────────────────────────────
        created = me.post('/api/auth/vehicles/',
                          {'name': '__mb Cobalt', 'vin': 'JTDBR32E720012345'},
                          content_type='application/json')
        check('mashina qo\'shildi', created.status_code in (200, 201), created.status_code)
        vehicle_id = created.json().get('id')

        listed = rows(me.get('/api/auth/vehicles/').json())
        check('mashina ro\'yxatda', any(v['id'] == vehicle_id for v in listed), listed)
        check('begona mashinani ko\'rmadi',
              rows(api(stranger).get('/api/auth/vehicles/').json()) == [])

        bad_vin = me.post('/api/auth/vehicles/', {'name': 'x', 'vin': 'QIO123'},
                          content_type='application/json')
        check('noto\'g\'ri VIN rad etildi', bad_vin.status_code == 400, bad_vin.status_code)

        deleted = me.delete(f'/api/auth/vehicles/{vehicle_id}/')
        check('mashina o\'chirildi',
              deleted.status_code in (200, 204)
              and not Vehicle.objects.filter(pk=vehicle_id).exists())

        # ── 3. Stansiyalar va sharhlar ──────────────────────────
        listing = rows(me.get('/api/stations/').json())
        check('stansiyalar ro\'yxati qaytdi',
              any(s['name'] == '__mb Stansiya' for s in listing), len(listing))

        detail = me.get(f'/api/stations/{station.id}/')
        check('stansiya detali qaytdi', detail.status_code == 200, detail.status_code)
        check('detalda ulagichlar bor',
              detail.json().get('connectors'), list(detail.json())[:6])

        review = me.post(f'/api/stations/{station.id}/reviews/',
                         {'rating': 5, 'comment': '__mb zo\'r'},
                         content_type='application/json')
        check('sharh qoldirildi', review.status_code in (200, 201), review.status_code)
        check('sharh ro\'yxatda',
              any('__mb' in r.get('comment', '')
                  for r in rows(me.get(f'/api/stations/{station.id}/reviews/').json())))

        # ── 3b. Promo-kod ───────────────────────────────────────
        # Kod sessiya boshlashdan OLDIN tekshiriladi: chegirma
        # ishlamaganini zaryadlash tugagach bilish eng noqulay payt.
        from management.models import Offer

        promo = Offer.objects.create(
            title='__mb Aksiya', discount_type=Offer.DiscountType.PERCENT,
            discount_value=20, promo_code='__MBCODE',
            starts_at=timezone.now() - timedelta(days=1))

        bad_code = me.post('/api/stations/promo/check/',
                           {'stationId': station.id, 'code': 'YOQ'},
                           content_type='application/json')
        check('yolg\'on promo-kod rad etildi', bad_code.status_code == 400,
              bad_code.status_code)

        good_code = me.post('/api/stations/promo/check/',
                            {'stationId': station.id, 'code': '__MBCODE'},
                            content_type='application/json')
        check('promo-kod tasdiqlandi', good_code.status_code == 200,
              good_code.content[:120])
        check('yangi narx qaytdi',
              good_code.json().get('pricePerKwh', 0)
              < good_code.json().get('originalPricePerKwh', 0), good_code.json())

        # ── 4. Sessiya ──────────────────────────────────────────
        # Noto'g'ri kod bilan sessiya BOSHLANMASLIGI kerak
        rejected = me.post('/api/sessions/start/',
                           {'stationId': station.id, 'promoCode': 'YOQ'},
                           content_type='application/json')
        check('noto\'g\'ri kod bilan sessiya boshlanmadi',
              rejected.status_code == 400, rejected.status_code)

        started = me.post('/api/sessions/start/',
                          {'stationId': station.id, 'promoCode': '__MBCODE'},
                          content_type='application/json')
        check('sessiya boshlandi', started.status_code in (200, 201), started.status_code)
        session = ChargingSession.objects.filter(user=driver).first()
        check('sessiya bazada', session is not None)

        active = me.get('/api/sessions/active/')
        check('faol sessiya qaytdi', active.status_code == 200, active.status_code)
        check('sessiya chegirmali narxda ochildi',
              started.json().get('pricePerKwh', 0)
              < started.json().get('basePricePerKwh', 0), started.json().get('priceLabel'))
        check('chegirma sababi ilovaga yetkazildi',
              '__mb Aksiya' in (started.json().get('priceLabel') or ''),
              started.json().get('priceLabel'))

        check('faol sessiya shu stansiyaniki',
              str(active.json().get('stationId')) == str(station.id),
              active.json().get('stationId'))

        # Sessiya bo'lmasa 204 qaytadi — tanasi bo'sh, `.json()` ishlamaydi
        check("begona faol sessiyani ko'rmadi",
              api(stranger).get('/api/sessions/active/').status_code == 204)

        one = me.get(f'/api/sessions/{session.id}/')
        check('sessiya detali qaytdi', one.status_code == 200, one.status_code)
        check('begona sessiya detali yopiq',
              api(stranger).get(f'/api/sessions/{session.id}/').status_code == 404)

        stopped = me.post(f'/api/sessions/{session.id}/stop/')
        session.refresh_from_db()
        check('sessiya to\'xtatildi',
              stopped.status_code == 200
              and session.status != ChargingSession.Status.CHARGING, session.status)

        history = rows(me.get('/api/sessions/').json())
        check('tarixda ko\'rindi', any(s['id'] == str(session.id) or s['id'] == session.id
                                       for s in history), history[:1])

        insights = me.get('/api/sessions/insights/')
        check('statistika qaytdi', insights.status_code == 200, insights.status_code)

        # ── 5. Hamyon ───────────────────────────────────────────
        balance = me.get('/api/wallet/balance/')
        check('balans qaytdi',
              balance.status_code == 200 and 'amount' in balance.json(), balance.json())
        check('boshqa odamning balansi ko\'rinmadi',
              api(stranger).get('/api/wallet/balance/').json()['amount'] == 1000)

        moves = rows(me.get('/api/wallet/transactions/').json())
        check('tranzaksiyalar qaytdi', isinstance(moves, list), type(moves).__name__)

        # ── 6. Bronlar ──────────────────────────────────────────
        booked = me.post('/api/bookings/', {
            'stationId': station.id, 'connectorId': connector.id,
            'scheduledAt': (timezone.now() + timedelta(hours=3)).isoformat(),
            'durationMinutes': 60,
        }, content_type='application/json')
        check('bron yaratildi', booked.status_code in (200, 201), booked.content[:120])

        booking = Booking.objects.filter(user=driver).first()
        if booking is not None:
            mine = rows(me.get('/api/bookings/').json())
            check('bron ro\'yxatda', len(mine) >= 1, len(mine))
            check('begona bronni ko\'rmadi',
                  rows(api(stranger).get('/api/bookings/').json()) == [])

            cancelled = me.post(f'/api/bookings/{booking.id}/cancel/')
            booking.refresh_from_db()
            check('bron bekor qilindi',
                  cancelled.status_code == 200
                  and booking.status == Booking.Status.CANCELLED, booking.status)

        # ── 7. Xabarlar ─────────────────────────────────────────
        note = UserNotification.objects.create(
            user=driver, kind=UserNotification.Kind.SYSTEM,
            title='__mb xabar', body='sinov')
        feed = me.get('/api/notifications/')
        check('xabarlar qaytdi',
              feed.status_code == 200 and feed.json().get('unread', 0) >= 1, feed.json())

        me.post(f'/api/notifications/{note.id}/read/')
        note.refresh_from_db()
        check('xabar o\'qilgan deb belgilandi', note.read_at is not None)

        second = UserNotification.objects.create(
            user=driver, kind=UserNotification.Kind.SYSTEM, title='__mb 2', body='x')
        me.post('/api/notifications/read-all/')
        second.refresh_from_db()
        check('hammasi o\'qilgan deb belgilandi', second.read_at is not None)

        check('begona xabarni o\'qib bo\'lmadi',
              api(stranger).post(f'/api/notifications/{note.id}/read/').status_code == 404)

        # ── 8. RFID kartalar ────────────────────────────────────
        card = RfidCard.objects.create(id_tag='__MB_CARD__', user=driver,
                                       status=RfidCard.Status.ACTIVE)
        mine = rows(me.get('/api/auth/rfid-cards/').json())
        check('o\'z kartasi ko\'rindi', len(mine) == 1, mine)

        blocked = me.post(f'/api/auth/rfid-cards/{card.id}/block/',
                          {'status': 'blocked'}, content_type='application/json')
        card.refresh_from_db()
        check('kartani bloklay oldi',
              blocked.status_code == 200 and card.status == RfidCard.Status.BLOCKED,
              card.status)
        check('begona kartani bloklay olmadi',
              api(stranger).post(f'/api/auth/rfid-cards/{card.id}/block/',
                                 {'status': 'active'},
                                 content_type='application/json').status_code == 404)

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
