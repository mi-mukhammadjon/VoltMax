# -*- coding: utf-8 -*-
"""Amallar jurnali: panelda kim nima qilgani yozib boriladimi.

Tizimda pul harakati ko'p — onlayn to'lov, qaytarish, korporativ hisoblar.
Nizo chiqqanda «kim va qachon qildi?» degan savolga javob bo'lishi kerak.

Asosiy savollar:
  1. Pulga va kartaga tegadigan amallar yozib boriladimi?
  2. Yozuvda KIM qilgani va qaysi yozuv ustida ekani bormi?
  3. Jurnal xato bersa asosiy amal to'xtab qolmaydimi?
  4. Filtrlar (bo'lim, qidiruv, xodim, sana) ishlaydimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import (  # noqa: E402
    override_settings, setup_test_environment,
)
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import Company, CompanyInvoice, RfidCard  # noqa: E402
from management.activity import log_action  # noqa: E402
from management.models import ActivityLog  # noqa: E402
from wallet.models import WalletBalance  # noqa: E402

setup_test_environment()

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    ActivityLog.objects.filter(title__contains='__al').delete()
    CompanyInvoice.objects.filter(company__name__startswith='__al').delete()
    RfidCard.objects.filter(id_tag__startswith='__AL').delete()
    Company.objects.filter(name__startswith='__al').delete()
    User.objects.filter(username__startswith='__al').delete()
    User.objects.filter(username__startswith='company-__al').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    admin = User.objects.create(username='__al_admin__', is_staff=True, is_superuser=True)
    other = User.objects.create(username='__al_boshqa__', is_staff=True)
    try:
        client = Client()
        url = reverse('dashboard:activity')
        check('anonim foydalanuvchiga yopiq',
              client.get(url).status_code in (302, 403))

        client.force_login(admin)

        # ── 1. Karta amali ──────────────────────────────────────
        card = RfidCard.objects.create(id_tag='__AL_CARD__', label='__al karta')
        client.post(reverse('dashboard:rfid_card_status', args=[card.pk]),
                    {'status': 'blocked'})
        row = ActivityLog.objects.filter(title__contains='__AL_CARD__').first()
        check('karta bloklash yozildi', row is not None, row)
        check('kim qilgani yozildi', row.actor_id == admin.id, row.actor)
        check('yozuvga havola bor', f'/rfid/{card.pk}/' == row.target_url, row.target_url)
        check("bo'lim to'g'ri", row.action == ActivityLog.Action.CARD, row.action)

        # ── 2. Pul amali ────────────────────────────────────────
        company = Company.objects.create(
            billing_user=User.objects.create(username='company-__al_taxi__'),
            name='__al Taksi')
        WalletBalance.objects.create(user=company.billing_user, amount=0)

        client.post(reverse('dashboard:company_topup', args=[company.pk]),
                    {'amount': '50 000', 'reference': '__al t/t 15'})
        money = ActivityLog.objects.filter(action=ActivityLog.Action.WALLET,
                                           title__contains='__al Taksi').first()
        check("qo'lda to'ldirish yozildi", money is not None, money)
        check('summa yozuvda ko\'rinadi',
              '50' in money.title, money.title)
        check('to\'lov asosi tafsilotda', '__al t/t 15' in money.detail, money.detail)

        invoice = CompanyInvoice.objects.create(
            company=company, number=CompanyInvoice.next_number(), amount=30000)
        client.post(reverse('dashboard:company_invoice_paid', args=[invoice.pk]),
                    {'payment_ref': '__al 77'})
        paid = ActivityLog.objects.filter(action=ActivityLog.Action.INVOICE).first()
        check('hisob to\'lovi yozildi',
              paid is not None and invoice.number in paid.title, paid)

        # ── 3. Jurnal amalni to'xtatmaydi ───────────────────────
        # Yozib bo'lmasa xato logga tushadi, amal esa davom etadi
        class BrokenRequest:
            user = admin

        too_long = 'x' * 500
        written = log_action(BrokenRequest(), ActivityLog.Action.OTHER,
                             f'__al {too_long}', detail=too_long)
        check('juda uzun matn yozuvni buzmadi',
              written is not None and len(written.title) <= 150, len(written.title))

        broken = log_action(None, ActivityLog.Action.OTHER, '__al so\'rovsiz')
        check('so\'rovsiz chaqiruv ham xato bermadi', broken is not None)

        # ── 4. Filtrlar ─────────────────────────────────────────
        log_action(BrokenRequest(), ActivityLog.Action.SESSION, '__al sessiya amali')
        ActivityLog.objects.filter(title='__al sessiya amali').update(actor=other)

        def titles(**params):
            rows = client.get(url, params).context['page_obj']
            # Karta yozuvi katta harfda (`__AL_CARD__`), qolganlari kichikda
            return [r.title for r in rows if '__al' in r.title.lower()]

        check("bo'lim tabi filtrladi",
              all('sessiya' in t for t in titles(action='session')),
              titles(action='session'))
        check('qidiruv ishladi',
              titles(q='__AL_CARD__') and all('__AL_CARD__' in t
                                              for t in titles(q='__AL_CARD__')))
        check('xodim bo\'yicha filtr',
              titles(actor=str(other.id)) == ['__al sessiya amali'],
              titles(actor=str(other.id)))

        today = timezone.localdate().isoformat()
        check('sana oralig\'i bugungi amallarni qamradi', len(titles(**{'from': today})) > 0)
        check('kelajakdagi sana bo\'sh natija berdi',
              titles(**{'from': '2099-01-01'}) == [])

        page = client.get(url).content.decode('utf-8')
        check('sahifada jurnal ko\'rinadi', '__AL_CARD__' in page)
        check('filtr oynasi bor', 'activity-filter-modal' in page)
        check('AJAX uchun belgilangan',
              'data-live-search' in page and 'id="activity-results"' in page)
        check('menyuda havola bor',
              '/activity/' in client.get(reverse('dashboard:home')).content.decode('utf-8'))

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
