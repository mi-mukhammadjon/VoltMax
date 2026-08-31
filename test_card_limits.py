# -*- coding: utf-8 -*-
"""RFID kartaga qo'yilgan sarf chegarasi.

Kompaniya kartani haydovchiga beradi, hamyon esa kompaniyaniki. Chegara
yo'q edi: bitta karta butun oylik byudjetni bir kunda sarflab yuborishi
mumkin edi va buni faqat hisobdan keyin bilib qolinardi.

Asosiy savollar:
  1. Chegarasiz karta avvalgidek cheksiz ishlaydimi?
  2. Kunlik va oylik chegara HAQIQATAN to'sadimi?
  3. Ketayotgan sessiya ham hisobga olinadimi (aks holda uzoq sessiya
     bilan chegarani aylanib o'tish mumkin edi)?
  4. Chegara faqat SHU kartaning sarfini sanaydimi?
  5. O'tgan davr sarfi chegarani band qilib qolmaydimi?
  6. Sabab foydalanuvchiga tushunarli aytiladimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import RfidCard  # noqa: E402
from management.models import SiteSettings  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Station  # noqa: E402
from stations.rules import can_start, check_card_limits  # noqa: E402
from wallet.models import WalletBalance  # noqa: E402

failures = 0

CARD = '__CL_CARD__'
OTHER = '__CL_OTHER__'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    ChargingSession.objects.filter(id_tag__startswith='__CL').delete()
    ChargingSession.objects.filter(station__name__startswith='__cl').delete()
    RfidCard.objects.filter(id_tag__startswith='__CL').delete()
    Station.objects.filter(name__startswith='__cl').delete()
    User.objects.filter(username__startswith='__cl').delete()


def spent(card, amount, when=None, id_tag=None, station=None, connector=None,
          user=None, running=False):
    """Tugagan (yoki ketayotgan) sessiya yozadi — sarf shundan hisoblanadi."""
    session = ChargingSession.objects.create(
        user=user, station=station, connector=connector,
        start_percent=0, power_kw=60, price_per_kwh=1000,
        connector_label='A', id_tag=id_tag or card.id_tag,
        status=(ChargingSession.Status.CHARGING if running
                else ChargingSession.Status.COMPLETED),
        final_kwh_charged=None if running else amount / 1000,
        final_cost=None if running else amount,
    )
    # `started_at` — auto_now_add, shuning uchun UPDATE bilan siljitiladi
    moment = when or timezone.now()
    ChargingSession.objects.filter(pk=session.pk).update(
        started_at=moment, stopped_at=None if running else moment)
    return ChargingSession.objects.get(pk=session.pk)


def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f)
             for f in ('min_balance_to_start', 'work_all_day')}
    try:
        settings_obj.min_balance_to_start = 0
        settings_obj.work_all_day = True
        settings_obj.save()

        driver = User.objects.create(username='__cl_driver__')
        WalletBalance.objects.create(user=driver, amount=5_000_000)

        station = Station.objects.create(
            name='__cl Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='dc', power_kw=60)
        connector = Connector.objects.create(
            station=station, label='A', type='ccs2', power_kw=60)

        card = RfidCard.objects.create(id_tag=CARD, user=driver,
                                       status=RfidCard.Status.ACTIVE)
        neighbour = RfidCard.objects.create(id_tag=OTHER, user=driver,
                                            status=RfidCard.Status.ACTIVE)

        # ── 1. Chegarasiz karta ─────────────────────────────────
        spent(card, 900_000, station=station, connector=connector, user=driver)
        check('chegarasiz karta ishlayveradi', check_card_limits(card) is None,
              check_card_limits(card))
        check('chegara ro\'yxati bo\'sh', card.limit_state == [], card.limit_state)

        # ── 2. Oylik chegara ────────────────────────────────────
        card.monthly_limit = 1_000_000
        card.save()
        check('chegara ostida ruxsat', check_card_limits(card) is None,
              check_card_limits(card))
        check('sarf to\'g\'ri hisoblandi',
              card.spent_this_month == 900_000, card.spent_this_month)

        spent(card, 150_000, station=station, connector=connector, user=driver)
        reason = check_card_limits(card)
        check('oylik chegara to\'sdi', reason is not None, reason)
        check('sabab tushunarli aytildi',
              reason and 'chegara' in reason.lower() and 'oy' in reason.lower(),
              reason)
        check('can_start ham to\'sdi',
              can_start(driver, card=card) is not None)
        check('kartasiz ilova esa ishlayveradi',
              can_start(driver) is None, can_start(driver))

        # ── 3. Faqat shu kartaning sarfi ────────────────────────
        check('qo\'shni karta erkin', check_card_limits(neighbour) is None)
        spent(neighbour, 700_000, station=station, connector=connector, user=driver)
        check('qo\'shni kartaning sarfi aralashmadi',
              card.spent_this_month == 1_050_000, card.spent_this_month)

        # ── 4. O'tgan oy hisobga olinmaydi ──────────────────────
        ChargingSession.objects.filter(id_tag=CARD).delete()
        month_start = timezone.localtime().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0)
        spent(card, 3_000_000, when=month_start - timedelta(days=2),
              station=station, connector=connector, user=driver)
        check('o\'tgan oy sarfi chegarani band qilmadi',
              check_card_limits(card) is None, check_card_limits(card))
        check('shu oy sarfi nol', card.spent_this_month == 0, card.spent_this_month)

        # ── 5. Kunlik chegara ───────────────────────────────────
        card.monthly_limit = None
        card.daily_limit = 200_000
        card.save()

        yesterday = timezone.localtime().replace(
            hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
        spent(card, 500_000, when=yesterday,
              station=station, connector=connector, user=driver)
        check('kechagi sarf bugungi chegarani band qilmadi',
              check_card_limits(card) is None, check_card_limits(card))

        spent(card, 200_000, station=station, connector=connector, user=driver)
        reason = check_card_limits(card)
        check('kunlik chegara to\'sdi', reason is not None, reason)
        check('sabab bugun haqida', reason and 'bugun' in reason.lower(), reason)

        # ── 6. Ketayotgan sessiya ham sanaladi ──────────────────
        # Bu eng muhim holat: chegarani aylanib o'tishning eng oson yo'li —
        # bitta uzoq sessiya. Tugamagani uchun hisobga tushmasa, chegara
        # qog'ozda qolardi.
        ChargingSession.objects.filter(id_tag=CARD).delete()
        card.daily_limit = 100_000
        card.save()
        check('sessiyasiz karta erkin', check_card_limits(card) is None)

        live = spent(card, 0, station=station, connector=connector, user=driver,
                     running=True)
        # 150 kVt·s × 1000 so'm — hali tugamagan, lekin allaqachon ko'p
        ChargingSession.objects.filter(pk=live.pk).update(
            is_live=True, meter_start_wh=0, live_meter_wh=150_000)
        check('ketayotgan sessiya hisobga olindi',
              check_card_limits(card) is not None, card.spent_today)

        ChargingSession.objects.filter(pk=live.pk).delete()

        # ── 7. Xizmat kartasi ───────────────────────────────────
        check('karta berilmasa tekshiruv o\'tkazib yuboriladi',
              check_card_limits(None) is None)

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
