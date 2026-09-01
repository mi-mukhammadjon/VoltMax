# -*- coding: utf-8 -*-
"""Hamkorlar bilan oylik hisob-kitob.

Stansiya hamkorga tegishli, tushum esa bizga keladi. Ilgari bu hisob
umuman yo'q edi: `commission_percent` saqlanardi, lekin u bilan hech
narsa qilinmasdi.

Asosiy savollar:
  1. Ulush to'g'ri hisoblanadimi va faqat SHU DAVRdagi sessiyalar
     kiradimi?
  2. Hisob muzlatilgach komissiya foizi o'zgarsa ham davr o'zgarmaydimi?
  3. Bir davr uchun ikkita yozuv yaratib bo'lmaydimi (ikki marta to'lash
     xavfi)?
  4. To'lov qayd etilgach jurnalga tushadimi?
  5. CSV eksport to'g'ri chiqadimi?
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

from dashboard.payouts import build_period, freeze, partner_totals  # noqa: E402
from management.models import ActivityLog, Partner, PartnerPayout  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Station  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    ChargingSession.objects.filter(station__name__startswith='__po').delete()
    PartnerPayout.objects.filter(partner__name__startswith='__po').delete()
    ActivityLog.objects.filter(title__contains='__po').delete()
    Station.objects.filter(name__startswith='__po').delete()
    Partner.objects.filter(name__startswith='__po').delete()
    User.objects.filter(username__startswith='__po').delete()


def make_session(station, when, cost, kwh=10.0,
                 status=ChargingSession.Status.COMPLETED, user=None):
    session = ChargingSession.objects.create(
        user=user, station=station, connector=station.connectors.first(),
        start_percent=20, power_kw=60, price_per_kwh=1200, connector_label='A',
        status=status, final_kwh_charged=kwh, final_cost=cost)
    ChargingSession.objects.filter(pk=session.pk).update(
        started_at=when, stopped_at=when)
    return session


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    admin = User.objects.create(username='__po_admin__', is_staff=True, is_superuser=True)
    try:
        partner = Partner.objects.create(name='__po Hamkor', commission_percent=20)
        station = Station.objects.create(
            name='__po Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='dc', power_kw=60, partner=partner)
        Connector.objects.create(station=station, label='A', type='ccs2', power_kw=60)

        today = timezone.localdate()
        year, month = today.year, today.month

        # Sanalar OY CHEGARASIDAN qat'i nazar to'g'ri tushishi kerak.
        # Ilgari "kecha" olinardi va oyning BIRINCHI kunida u oldingi
        # oyga tushib qolardi — sinov oyiga bir marta yiqilardi. Bunday
        # sinov yo'qdan ham yomon: unga ishonch qolmaydi.
        month_start = timezone.now().replace(day=1, hour=0, minute=0,
                                             second=0, microsecond=0)
        # Oy boshi bilan hozirgi payt orasidagi o'rta nuqta — har doim
        # shu oyda va har doim o'tmishda
        inside = month_start + (timezone.now() - month_start) / 2
        # 45 kun emas: qisqa oylarda ham albatta oldingi oyga tushsin
        outside = month_start - timedelta(days=5)

        make_session(station, inside, 100000, kwh=80.0, user=admin)
        make_session(station, inside, 50000, kwh=40.0, user=admin)
        make_session(station, outside, 900000, kwh=700.0, user=admin)     # oldingi davr
        make_session(station, inside, 70000, kwh=55.0, user=admin,
                     status=ChargingSession.Status.CHARGING)              # ketayapti

        # ── 1. Hisob ────────────────────────────────────────────
        totals = partner_totals(partner, year, month)
        check('faqat davr sessiyalari yig\'ildi',
              totals['gross'] == 150000 and totals['sessions'] == 2, totals)
        check('energiya yig\'indisi', totals['kwh'] == 120.0, totals['kwh'])
        # 20% biznikida qoladi: 150 000 * 20 / 100 = 30 000
        check('bizning ulush to\'g\'ri', totals['commission'] == 30000, totals['commission'])
        check('hamkor ulushi to\'g\'ri', totals['amount'] == 120000, totals['amount'])

        # Yaxlitlash: kasr bizda qoladi, hamkor ulushi kamaymaydi
        partner.commission_percent = 7
        partner.save(update_fields=['commission_percent'])
        odd = partner_totals(partner, year, month)
        check('yaxlitlash yo\'qotishsiz',
              odd['commission'] + odd['amount'] == odd['gross'],
              (odd['commission'], odd['amount']))
        partner.commission_percent = 20
        partner.save(update_fields=['commission_percent'])

        client = Client()
        url = reverse('dashboard:payouts')
        check('anonim foydalanuvchiga yopiq',
              client.get(url).status_code in (302, 403))

        client.force_login(admin)
        page = client.get(url, {'year': year, 'month': month}).content.decode('utf-8')
        check('sahifada hamkor ko\'rinadi', '__po Hamkor' in page)
        check('hisoblanmagan deb belgilandi', 'Hisoblanmagan' in page)

        # ── 2. Muzlatish ────────────────────────────────────────
        client.post(reverse('dashboard:payout_freeze', args=[partner.pk, year, month]))
        record = PartnerPayout.objects.filter(partner=partner).first()
        check('hisob yozuvi yaratildi',
              record is not None and record.amount == 120000, record)
        check('foiz yozuvda muzlatildi', record.commission_percent == 20)

        # Foiz o'zgarsa ham muzlatilgan davr o'zgarmaydi
        partner.commission_percent = 50
        partner.save(update_fields=['commission_percent'])
        rows = build_period(year, month)
        row = [r for r in rows if r['partner'].pk == partner.pk][0]
        check('muzlatilgan davr o\'zgarmadi',
              row['amount'] == 120000 and row['commission_percent'] == 20, row['amount'])
        partner.commission_percent = 20
        partner.save(update_fields=['commission_percent'])

        # ── 3. Ikkinchi yozuv yaratilmaydi ──────────────────────
        client.post(reverse('dashboard:payout_freeze', args=[partner.pk, year, month]))
        check('bir davrga ikkita yozuv yaratilmadi',
              PartnerPayout.objects.filter(partner=partner, year=year,
                                           month=month).count() == 1)
        again, created = freeze(partner, year, month, user=admin)
        check('takroriy chaqiruv mavjudini qaytardi',
              not created and again.pk == record.pk)

        # ── 4. To'lov ───────────────────────────────────────────
        client.post(reverse('dashboard:payout_paid', args=[record.pk]),
                    {'payment_ref': '__po 42'})
        record.refresh_from_db()
        check('to\'langan deb belgilandi', record.is_paid and record.paid_at is not None)
        check('topshiriqnoma raqami saqlandi', record.payment_ref == '__po 42')
        check('jurnalga tushdi',
              ActivityLog.objects.filter(title__contains='__po Hamkor').exists())

        before = record.paid_at
        client.post(reverse('dashboard:payout_paid', args=[record.pk]),
                    {'payment_ref': 'boshqa'})
        record.refresh_from_db()
        check('ikkinchi marta to\'lanmadi',
              record.paid_at == before and record.payment_ref == '__po 42')

        # ── 5. CSV ──────────────────────────────────────────────
        response = client.get(reverse('dashboard:payouts_export'),
                              {'year': year, 'month': month})
        text = (b''.join(response.streaming_content)
                if response.streaming else response.content).decode('utf-8')
        check('CSV qaytdi', 'text/csv' in response['Content-Type'])
        check('hamkor qatori bor', '__po Hamkor' in text)
        check('summalar CSV da',
              '150000' in text and '120000' in text,
              [line for line in text.splitlines() if '__po' in line][:1])

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
