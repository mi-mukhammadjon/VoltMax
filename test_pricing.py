# -*- coding: utf-8 -*-
"""Narx qanday hisoblanadi: tarif oynasi va aksiyalar.

Aksiyalar panelda yaratilardi-yu, hisobga UMUMAN qo'shilmasdi: butun kod
bo'ylab `discount_value` faqat formada va admin ro'yxatida uchrardi.
Operator aksiya e'lon qilardi, mijoz esa to'liq narxda to'lardi. Vaqtga
bog'liq tarif esa umuman yo'q edi.

Bu sinov narxning uch qatlamini tekshiradi (`stations.pricing`):

    ASOS  →  TARIF (almashtiradi)  →  AKSIYA (chegirma beradi)

Asosiy savollar:
  1. Tarif oynasi soatiga qarab ishlaydimi va tunga o'tuvchi oyna
     to'g'ri hisoblanadimi?
  2. Kun turi (ish kuni / dam olish / bayram) hisobga olinadimi?
  3. Aksiya narxni HAQIQATAN kamaytiradimi — foizda ham, summada ham?
  4. Promo-kodli aksiya kodsiz ishlab ketmaydimi?
  5. Bir nechta aksiya to'g'ri kelsa mijoz uchun eng foydalisi
     tanlanadimi va ular qo'shilib ketmaydimi?
  6. Sessiya boshlanganda narx MUZLATILADIMI?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import time, timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.utils import timezone  # noqa: E402

from management.models import Holiday, Offer, SiteSettings  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations import pricing  # noqa: E402
from stations.models import Connector, Station, TariffWindow  # noqa: E402
from wallet.models import WalletBalance  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    ChargingSession.objects.filter(station__name__startswith='__pr').delete()
    TariffWindow.objects.filter(name__startswith='__pr').delete()
    Offer.objects.filter(title__startswith='__pr').delete()
    Station.objects.filter(name__startswith='__pr').delete()
    Holiday.objects.filter(name__startswith='__pr').delete()
    User.objects.filter(username__startswith='__pr').delete()


def at(hour, minute=0, day=None):
    """Berilgan soatdagi mahalliy vaqt — sinov aniq paytga bog'lanadi."""
    moment = timezone.localtime()
    if day is not None:
        moment += timedelta(days=(day - moment.weekday()) % 7)
    return moment.replace(hour=hour, minute=minute, second=0, microsecond=0)


def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {'default_price_per_kwh': settings_obj.default_price_per_kwh}

    # Bazadagi HAQIQIY tarif va aksiyalar sinov davomida vaqtincha
    # o'chiriladi. Aks holda natija bazaning holatiga bog'liq bo'lardi:
    # ishlab chiqishda qo'shilgan bitta tungi tarif butun sinovni
    # ag'darib yuborardi va sabab uzoq izlanardi.
    outside_windows = list(TariffWindow.objects.filter(is_active=True)
                           .exclude(name__startswith='__pr')
                           .values_list('pk', flat=True))
    outside_offers = list(Offer.objects.filter(is_active=True)
                          .exclude(title__startswith='__pr')
                          .values_list('pk', flat=True))
    TariffWindow.objects.filter(pk__in=outside_windows).update(is_active=False)
    Offer.objects.filter(pk__in=outside_offers).update(is_active=False)

    try:
        settings_obj.default_price_per_kwh = 1200
        settings_obj.save()

        station = Station.objects.create(
            name='__pr Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='dc', power_kw=60)
        other = Station.objects.create(
            name='__pr Boshqa', address='b', latitude=41.1, longitude=69.1,
            charger_type='dc', power_kw=60)

        # ── 1. Asos ─────────────────────────────────────────────
        pricing.clear_catalogue()
        check('chegirmasiz stansiya markaziy narxda',
              pricing.resolve(station).price == 1200,
              pricing.resolve(station).price)

        station.discount_price_per_kwh = 1000
        station.save()
        pricing.clear_catalogue()
        check("stansiyaning o'z narxi ustun",
              pricing.resolve(station).price == 1000)
        station.discount_price_per_kwh = None
        station.save()

        # ── 2. Tarif oynasi ─────────────────────────────────────
        night = TariffWindow.objects.create(
            name='__pr Tungi', start_time=time(22, 0), end_time=time(6, 0),
            price_per_kwh=800)
        pricing.clear_catalogue()

        check('tunda tarif narxi qo\'llandi',
              pricing.resolve(station, now=at(23, 30)).price == 800,
              pricing.resolve(station, now=at(23, 30)).price)
        check('yarim tundan keyin ham davom etdi',
              pricing.resolve(station, now=at(3, 0)).price == 800,
              pricing.resolve(station, now=at(3, 0)).price)
        check('kunduzi asosiy narx qoldi',
              pricing.resolve(station, now=at(14, 0)).price == 1200,
              pricing.resolve(station, now=at(14, 0)).price)
        check('chegirma sababi aytildi',
              '__pr Tungi' in pricing.resolve(station, now=at(23, 30)).label)

        # Chegara aniq: 22:00 kiradi, 21:59 kirmaydi
        check('oyna chegarasi aniq (22:00 kiradi)',
              pricing.resolve(station, now=at(22, 0)).price == 800)
        check('oyna chegarasi aniq (21:59 kirmaydi)',
              pricing.resolve(station, now=at(21, 59)).price == 1200)

        # O'chirilgan oyna ishlamaydi
        night.is_active = False
        night.save()
        pricing.clear_catalogue()
        check("o'chirilgan tarif ta'sir qilmadi",
              pricing.resolve(station, now=at(23, 30)).price == 1200,
              pricing.resolve(station, now=at(23, 30)).price)
        night.is_active = True
        night.save()

        # ── 3. Kun turi ─────────────────────────────────────────
        weekend = TariffWindow.objects.create(
            name='__pr Dam olish', start_time=time(9, 0), end_time=time(18, 0),
            day_kind=TariffWindow.DayKind.WEEKEND, price_per_kwh=700)
        pricing.clear_catalogue()

        # 5 — shanba, 2 — chorshanba
        check('dam olish kuni qo\'llandi',
              pricing.resolve(station, now=at(12, 0, day=5)).price == 700,
              pricing.resolve(station, now=at(12, 0, day=5)).price)
        check('ish kunida qo\'llanmadi',
              pricing.resolve(station, now=at(12, 0, day=2)).price == 1200,
              pricing.resolve(station, now=at(12, 0, day=2)).price)

        # Bayram — dam olish kuni deb qaraladi
        wednesday = at(12, 0, day=2)
        Holiday.objects.create(date=wednesday.date(), name='__pr Bayram')
        pricing.clear_catalogue()
        check('bayram dam olish deb hisoblandi',
              pricing.resolve(station, now=wednesday).price == 700,
              pricing.resolve(station, now=wednesday).price)
        Holiday.objects.filter(name='__pr Bayram').delete()
        weekend.delete()

        # ── 4. Stansiyaga xos tarif umumiydan ustun ─────────────
        own = TariffWindow.objects.create(
            name='__pr Faqat shu yerda', station=station,
            start_time=time(22, 0), end_time=time(6, 0), price_per_kwh=950)
        pricing.clear_catalogue()
        check('stansiyaga xos tarif ustun turdi',
              pricing.resolve(station, now=at(23, 0)).price == 950,
              pricing.resolve(station, now=at(23, 0)).price)
        check('boshqa stansiyaga tegmadi',
              pricing.resolve(other, now=at(23, 0)).price == 800,
              pricing.resolve(other, now=at(23, 0)).price)
        own.delete()
        night.delete()
        pricing.clear_catalogue()

        # ── 5. Aksiya ───────────────────────────────────────────
        yesterday = timezone.now() - timedelta(days=1)
        percent = Offer.objects.create(
            title='__pr Bahor', discount_type=Offer.DiscountType.PERCENT,
            discount_value=25, starts_at=yesterday)
        pricing.clear_catalogue()

        quote = pricing.resolve(station, now=at(14, 0))
        check('foizli aksiya qo\'llandi', quote.price == 900, quote.price)
        check('chegirmasiz narx saqlandi', quote.base == 1200, quote.base)
        check('aksiya nomi izohda', '__pr Bahor' in quote.label, quote.label)

        # Belgilangan summa — kVt·soatdan ayiriladi
        percent.discount_type = Offer.DiscountType.FIXED
        percent.discount_value = 300
        percent.save()
        pricing.clear_catalogue()
        check('belgilangan summa ayirildi',
              pricing.resolve(station, now=at(14, 0)).price == 900,
              pricing.resolve(station, now=at(14, 0)).price)

        # Chegirma narxdan katta bo'lsa narx manfiy bo'lib ketmasligi kerak
        percent.discount_value = 5000
        percent.save()
        pricing.clear_catalogue()
        check('narx manfiy bo\'lmadi',
              pricing.resolve(station, now=at(14, 0)).price == 0,
              pricing.resolve(station, now=at(14, 0)).price)
        percent.delete()

        # ── 6. Muddat va faollik ────────────────────────────────
        expired = Offer.objects.create(
            title='__pr Tugagan', discount_value=50,
            ends_at=timezone.now() - timedelta(days=1))
        future = Offer.objects.create(
            title='__pr Kelajak', discount_value=50,
            starts_at=timezone.now() + timedelta(days=5))
        off = Offer.objects.create(
            title='__pr O\'chiq', discount_value=50, is_active=False)
        pricing.clear_catalogue()
        check('muddati tugagan aksiya qo\'llanmadi',
              pricing.resolve(station, now=at(14, 0)).price == 1200)
        expired.delete()
        future.delete()
        off.delete()

        # ── 7. Promo-kod ────────────────────────────────────────
        coded = Offer.objects.create(
            title='__pr Kodli', discount_type=Offer.DiscountType.PERCENT,
            discount_value=50, promo_code='VOLT2026', starts_at=yesterday)
        pricing.clear_catalogue()

        check('kodsiz aksiya qo\'llanmadi',
              pricing.resolve(station, now=at(14, 0)).price == 1200,
              pricing.resolve(station, now=at(14, 0)).price)
        check('kod bilan qo\'llandi',
              pricing.resolve(station, now=at(14, 0), promo_code='VOLT2026').price == 600,
              pricing.resolve(station, now=at(14, 0), promo_code='VOLT2026').price)
        check('katta-kichik harf farq qilmadi',
              pricing.resolve(station, now=at(14, 0), promo_code='volt2026').price == 600)

        offer, error = pricing.check_promo(station, 'VOLT2026')
        check('kod tekshiruvi topdi', offer is not None and error is None, error)
        _, error = pricing.check_promo(station, 'YOQ')
        check('yolg\'on kod rad etildi', error is not None, error)
        _, error = pricing.check_promo(station, '')
        check('bo\'sh kod rad etildi', error is not None, error)

        # Kod boshqa stansiyaga bog'langan bo'lsa
        coded.stations.add(other)
        pricing.clear_catalogue()
        _, error = pricing.check_promo(station, 'VOLT2026')
        check('boshqa stansiyaning kodi rad etildi', error is not None, error)
        check('narx ham o\'zgarmadi',
              pricing.resolve(station, now=at(14, 0), promo_code='VOLT2026').price == 1200)
        check('o\'z stansiyasida ishladi',
              pricing.resolve(other, now=at(14, 0), promo_code='VOLT2026').price == 600)
        coded.stations.clear()

        # ── 8. Bir nechta aksiya ────────────────────────────────
        coded.promo_code = ''
        coded.discount_value = 10       # 1200 → 1080
        coded.save()
        big = Offer.objects.create(
            title='__pr Katta', discount_type=Offer.DiscountType.PERCENT,
            discount_value=40, starts_at=yesterday)          # 1200 → 720
        pricing.clear_catalogue()

        quote = pricing.resolve(station, now=at(14, 0))
        check('eng foydali aksiya tanlandi', quote.price == 720, quote.price)
        check('aksiyalar qo\'shilmadi (648 emas)', quote.price != 648)
        check('qaysi aksiya ekani yozildi', quote.offer is not None and quote.offer.pk == big.pk)
        coded.delete()

        # ── 9. Tarif va aksiya birga ────────────────────────────
        evening = TariffWindow.objects.create(
            name='__pr Kechki', start_time=time(18, 0), end_time=time(23, 0),
            price_per_kwh=1000)
        pricing.clear_catalogue()

        quote = pricing.resolve(station, now=at(20, 0))
        # Avval tarif (1200 → 1000), keyin aksiya (1000 → 600)
        check('tarif va aksiya ketma-ket qo\'llandi', quote.price == 600, quote.price)
        check('ikkalasi ham izohda',
              '__pr Kechki' in quote.label and '__pr Katta' in quote.label, quote.label)
        check('tejalgan summa hisoblandi', quote.saved_per_kwh == 600, quote.saved_per_kwh)
        evening.delete()
        big.delete()
        pricing.clear_catalogue()

        # ── 10. Sessiyada narx muzlatiladi ──────────────────────
        driver = User.objects.create(username='__pr_driver__')
        WalletBalance.objects.create(user=driver, amount=100000)
        connector = Connector.objects.create(
            station=station, label='A', type='ccs2', power_kw=60,
            status=Connector.Status.AVAILABLE)

        live = Offer.objects.create(
            title='__pr Jonli', discount_type=Offer.DiscountType.PERCENT,
            discount_value=20, starts_at=yesterday)
        pricing.clear_catalogue()

        quote = pricing.resolve(station)
        session = ChargingSession.objects.create(
            user=driver, station=station, connector=connector,
            start_percent=10, power_kw=60, price_per_kwh=quote.price,
            base_price_per_kwh=quote.base, offer=quote.offer,
            price_label=quote.label, connector_label='A',
        )
        check('sessiya chegirmali narxda ochildi',
              session.price_per_kwh == 960, session.price_per_kwh)

        # Aksiya O'CHIRILADI — ketayotgan sessiyaga tegmasligi kerak
        live.is_active = False
        live.save()
        pricing.clear_catalogue()
        session.refresh_from_db()
        check("aksiya o'chirilgach sessiya narxi o'zgarmadi",
              session.price_per_kwh == 960, session.price_per_kwh)
        check('yangi sessiya esa to\'liq narxda bo\'lardi',
              pricing.resolve(station).price == 1200)

        session.final_kwh_charged = 10
        session.save()
        check('tejalgan summa ko\'rsatildi',
              session.saved_amount == 2400, session.saved_amount)

        live.delete()

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        TariffWindow.objects.filter(pk__in=outside_windows).update(is_active=True)
        Offer.objects.filter(pk__in=outside_offers).update(is_active=True)
        _cleanup()
        pricing.clear_catalogue()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
