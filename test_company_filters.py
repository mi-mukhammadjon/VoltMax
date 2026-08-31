# -*- coding: utf-8 -*-
"""Korporativ mijozlar ro'yxatining filtrlari.

Asosiy savollar:
  1. Qidiruv rekvizitlarni (STIR, hisob raqami) ham qamraydimi — buxgalteriya
     odatda shular bilan qidiradi?
  2. Holat tablari (faol / to'xtatilgan / balansi bo'sh) to'g'ri ajratadimi?
  3. Oynadagi mezonlar (STIR, hisob raqami, MFO, balans oralig'i, kartalar,
     rekvizitlar) ishlaydimi va BIR-BIRI bilan birga qo'llanadimi?
  4. «Filtr» tugmasidagi son faqat oynadagi mezonlarni sanaydimi?
  5. Tartiblash tanlovi ro'yxat tartibini o'zgartiradimi?
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

from accounts.models import Company, RfidCard  # noqa: E402
from wallet.models import WalletBalance  # noqa: E402

# Javobning `context` idishi shu chaqiruvdan keyin to'ladi — filtr
# natijasini HTML matnidan emas, ro'yxatning O'ZIDAN tekshiramiz
setup_test_environment()

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    RfidCard.objects.filter(id_tag__startswith='__CF').delete()
    Company.objects.filter(name__startswith='__cf').delete()
    User.objects.filter(username__startswith='__cf').delete()
    User.objects.filter(username__startswith='company-__cf').delete()


def make_company(slug, **fields):
    user = User.objects.create(username=f'company-__cf_{slug}__')
    WalletBalance.objects.create(user=user, amount=fields.pop('balance', 0))
    return Company.objects.create(billing_user=user, name=f'__cf {slug}', **fields)


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    admin = User.objects.create(username='__cf_admin__', is_staff=True, is_superuser=True)
    try:
        taxi = make_company(
            'taksi', legal_name='__cf Taksi MChJ', inn='305111222',
            bank_account='20208000900111222333', bank_mfo='00873',
            contact_name='Karimov', balance=5000000,
        )
        delivery = make_company(
            'dostavka', inn='305999888', bank_account='20208000900999888777',
            bank_mfo='01041', balance=0,
        )
        stopped = make_company('toxtagan', is_active=False, balance=250000)

        RfidCard.objects.create(id_tag='__CF_A__', company=taxi)

        client = Client()
        url = reverse('dashboard:companies')
        check('anonim foydalanuvchiga yopiq',
              client.get(url).status_code in (302, 403))

        client.force_login(admin)

        def names(**params):
            rows = client.get(url, params).context['page_obj']
            return sorted(c.name for c in rows if c.name.startswith('__cf'))

        # ── 1. Qidiruv ──────────────────────────────────────────
        check('nom bo\'yicha topildi', names(q='taksi') == ['__cf taksi'], names(q='taksi'))
        check('STIR bo\'yicha topildi', names(q='305999888') == ['__cf dostavka'],
              names(q='305999888'))
        check('hisob raqamining qismi bo\'yicha topildi',
              names(q='111222333') == ['__cf taksi'], names(q='111222333'))
        check('mas\'ul shaxs bo\'yicha topildi', names(q='Karimov') == ['__cf taksi'])

        # ── 2. Holat tablari ────────────────────────────────────
        active = names(status='active')
        check('faol tabida to\'xtatilgani yo\'q', '__cf toxtagan' not in active, active)
        check('to\'xtatilganlar tabi', names(status='inactive') == ['__cf toxtagan'],
              names(status='inactive'))
        debtors = names(status='debtor')
        check('balansi bo\'sh tabi', '__cf dostavka' in debtors and '__cf taksi' not in debtors,
              debtors)

        # ── 3. Oynadagi mezonlar ────────────────────────────────
        check('STIR filtri', names(inn='305111') == ['__cf taksi'], names(inn='305111'))
        check('hisob raqami filtri', names(account='999888') == ['__cf dostavka'])
        check('MFO filtri', names(mfo='01041') == ['__cf dostavka'], names(mfo='01041'))

        check('balans "dan" filtri',
              names(min_balance='1 000 000') == ['__cf taksi'],
              names(min_balance='1 000 000'))
        check('balans oralig\'i filtri',
              names(min_balance='100000', max_balance='300000') == ['__cf toxtagan'],
              names(min_balance='100000', max_balance='300000'))

        # Pul maydoni fokusdan chiqqanda "1 000 000.00" ko'rinishiga keladi —
        # kasr qismi bilan ham, ajratilmas bo'shliq bilan ham ishlashi kerak
        check("kasrli qiymat bilan ishladi",
              names(min_balance='1 000 000.00') == ['__cf taksi'],
              names(min_balance='1 000 000.00'))
        check("ajratilmas bo'shliqli qiymat bilan ishladi",
              names(min_balance='1 000 000.00') == ['__cf taksi'],
              names(min_balance='1 000 000.00'))
        check("vergulli kasr bilan ishladi",
              names(max_balance='300 000,00') == ['__cf dostavka', '__cf toxtagan'],
              names(max_balance='300 000,00'))
        check("bema'ni qiymat filtrni buzmadi",
              len(names(min_balance='salom')) == 3, names(min_balance='salom'))

        check('kartasi bor filtri', names(cards='with') == ['__cf taksi'])
        without = names(cards='without')
        check('kartasi yo\'q filtri',
              '__cf dostavka' in without and '__cf taksi' not in without, without)

        check('rekvizitlari to\'liq filtri',
              names(bank='full') == ['__cf dostavka', '__cf taksi'], names(bank='full'))
        missing = names(bank='missing')
        check('rekvizitlari to\'liq emas filtri',
              '__cf toxtagan' in missing and '__cf taksi' not in missing, missing)

        # Mezonlar birga ishlaydi
        check('qidiruv va filtr birga qo\'llandi',
              names(q='__cf', bank='full', cards='with') == ['__cf taksi'],
              names(q='__cf', bank='full', cards='with'))

        # ── 4. Tugmadagi son ────────────────────────────────────
        page = client.get(url, {'q': 'taksi', 'status': 'active'})
        check('qidiruv va tab "Filtr" soniga kirmadi',
              page.context['advanced_count'] == 0, page.context['advanced_count'])
        page = client.get(url, {'inn': '305', 'cards': 'with', 'q': 'a'})
        check('oynadagi ikki mezon sanaldi',
              page.context['advanced_count'] == 2, page.context['advanced_count'])

        # ── 5. Tartiblash ───────────────────────────────────────
        def order(**params):
            rows = client.get(url, params).context['page_obj']
            return [c.name for c in rows if c.name.startswith('__cf')]

        check('balans bo\'yicha tartiblandi',
              order(q='__cf', sort='balance')[0] == '__cf taksi',
              order(q='__cf', sort='balance'))
        check('nomi bo\'yicha tartib standart',
              order(q='__cf') == ['__cf dostavka', '__cf taksi', '__cf toxtagan'],
              order(q='__cf'))

        # ── 6. Sahifa ko'rinishi ────────────────────────────────
        body = client.get(url).content.decode('utf-8')
        check('filtr oynasi sahifada bor', 'company-filter-modal' in body)
        check('jonli filtr hududi bor',
              'id="company-results"' in body and 'data-live-search' in body)
        check('filtr bitta formada',
              body.count('<form method="get"') == 1, body.count('<form method="get"'))

        # Qo'llanilgan filtr ko'zga tashlanadi (qizil belgilar)
        plain = client.get(url).content.decode('utf-8')
        check('filtrsiz holatda tugma oddiy', 'is-filtered' not in plain)
        filtered = client.get(url, {'inn': '305'}).content.decode('utf-8')
        check("tugmada voronka belgisi bor", '<svg' in plain and 'filter-btn' in plain)
        check("filtrsiz holatda son ko'rsatilmadi", 'fb-count' not in plain)
        check("qo'llanilgan filtrda tugma belgilandi", 'is-filtered' in filtered)
        check("mezonlar guruhlarga bo'lindi",
              filtered.count('filter-group-title') == 3,
              filtered.count('filter-group-title'))
        check("balans maydonida o'lchov birligi ko'rsatildi",
              filtered.count('data-suffix') == 2, filtered.count('data-suffix'))
        check("qo'llanilgan mezonlar soni tugmada",
              'fb-count">1<' in filtered, 'fb-count' in filtered)
        check("to'ldirilgan maydon belgilandi",
              'field is-set' in filtered, 'field is-set' in filtered)
        check("bo'sh maydon belgilanmadi",
              filtered.count('field is-set') == 1, filtered.count('field is-set'))

        empty = client.get(url, {'q': '__cf yoq bunday mijoz'}).content.decode('utf-8')
        check('topilmagan holat matni ko\'rsatildi', 'Filtrga mos mijoz topilmadi' in empty)

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
