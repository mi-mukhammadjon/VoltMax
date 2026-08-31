# -*- coding: utf-8 -*-
"""RFID kartalar ro'yxatining filtrlari.

Korporativ mijozlar sahifasidagi tizim shu yerga ham qo'llandi: qidiruv va
holat tabi ko'rinib turadi, qolgan mezonlar «Filtr» oynasida.

Asosiy savollar:
  1. Holat tablari haqiqiy holatni ko'rsatadimi (muddati tugagan karta
     "faol" bo'lib chiqmaydimi)?
  2. Oynadagi mezonlar — korporativ mijoz, egasi, muddati, ishlatilishi,
     qo'shilgan sana — ishlaydimi va birga qo'llanadimi?
  3. «Filtr» tugmasidagi son faqat oynadagi mezonlarni sanaydimi?
  4. Tartiblash ro'yxat tartibini o'zgartiradimi?
  5. Filtr qatori AJAX uchun to'g'ri belgilanganmi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import (  # noqa: E402
    override_settings, setup_test_environment,
)
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import Company, RfidCard  # noqa: E402

# Javobning `context` idishi shu chaqiruvdan keyin to'ladi — natijani
# HTML matnidan emas, ro'yxatning O'ZIDAN tekshiramiz
setup_test_environment()

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    RfidCard.objects.filter(id_tag__startswith='__KF').delete()
    Company.objects.filter(name__startswith='__kf').delete()
    User.objects.filter(username__startswith='__kf').delete()
    User.objects.filter(username__startswith='company-__kf').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    now = timezone.now()
    admin = User.objects.create(username='__kf_admin__', is_staff=True, is_superuser=True)
    try:
        driver = User.objects.create(username='__kf_driver__')
        company = Company.objects.create(
            billing_user=User.objects.create(username='company-__kf_taxi__'),
            name='__kf Taksi',
        )

        # Korporativ, egasi bor, ishlatilgan, muddati yaqin
        corporate = RfidCard.objects.create(
            id_tag='__KF_CORP__', label='Haydovchi A', company=company, user=driver,
            status=RfidCard.Status.ACTIVE, use_count=12,
            expires_at=now + timedelta(days=10),
        )
        # Xizmat kartasi: egasiz, muddatsiz, ishlatilmagan
        service = RfidCard.objects.create(
            id_tag='__KF_SERVICE__', status=RfidCard.Status.ACTIVE, use_count=0,
        )
        # Muddati tugagan
        expired = RfidCard.objects.create(
            id_tag='__KF_OLD__', user=driver, status=RfidCard.Status.ACTIVE,
            use_count=3, expires_at=now - timedelta(days=2),
        )
        # Bloklangan
        blocked = RfidCard.objects.create(
            id_tag='__KF_BLOCK__', status=RfidCard.Status.BLOCKED, use_count=1,
        )

        # "Qo'shilgan sana" filtri uchun sanani orqaga suramiz
        RfidCard.objects.filter(pk=expired.pk).update(
            created_at=now - timedelta(days=40))

        client = Client()
        url = reverse('dashboard:rfid_cards')
        check('anonim foydalanuvchiga yopiq',
              client.get(url).status_code in (302, 403))

        client.force_login(admin)

        def tags(**params):
            rows = client.get(url, params).context['page_obj']
            return sorted(c.id_tag for c in rows if c.id_tag.startswith('__KF'))

        # ── 1. Holat tablari ────────────────────────────────────
        active = tags(status='active')
        check('faol tabida muddati tugagan karta yo\'q',
              '__KF_OLD__' not in active and '__KF_CORP__' in active, active)
        check('muddati tugaganlar tabi', tags(status='expired') == ['__KF_OLD__'],
              tags(status='expired'))
        check('bloklanganlar tabi', tags(status='blocked') == ['__KF_BLOCK__'],
              tags(status='blocked'))

        # ── 2. Qidiruv ──────────────────────────────────────────
        check('karta raqami bo\'yicha topildi',
              tags(q='__KF_SERVICE__') == ['__KF_SERVICE__'])
        check('nomi bo\'yicha topildi', tags(q='Haydovchi A') == ['__KF_CORP__'])
        check('mijoz nomi bo\'yicha topildi', tags(q='__kf Taksi') == ['__KF_CORP__'])

        # ── 3. Oynadagi mezonlar ────────────────────────────────
        check('korporativ mijoz bo\'yicha',
              tags(company=str(company.pk)) == ['__KF_CORP__'],
              tags(company=str(company.pk)))
        no_company = tags(company='none')
        check('"korporativ emas" tanlovi',
              '__KF_SERVICE__' in no_company and '__KF_CORP__' not in no_company,
              no_company)

        check('egasi biriktirilgan filtri',
              tags(owner='with') == ['__KF_CORP__', '__KF_OLD__'], tags(owner='with'))
        without = tags(owner='without')
        check('xizmat kartalari filtri',
              '__KF_SERVICE__' in without and '__KF_CORP__' not in without, without)

        check('muddati yaqin filtri', tags(expiry='soon') == ['__KF_CORP__'],
              tags(expiry='soon'))
        check('muddati belgilangan filtri',
              tags(expiry='set') == ['__KF_CORP__', '__KF_OLD__'], tags(expiry='set'))
        endless = tags(expiry='none')
        check('muddatsiz kartalar filtri',
              '__KF_SERVICE__' in endless and '__KF_CORP__' not in endless, endless)

        check('ishlatilmagan kartalar filtri',
              '__KF_SERVICE__' in tags(usage='unused')
              and '__KF_CORP__' not in tags(usage='unused'), tags(usage='unused'))
        check('ishlatilganlar filtri',
              '__KF_CORP__' in tags(usage='used')
              and '__KF_SERVICE__' not in tags(usage='used'))

        # Qo'shilgan sana
        recent = tags(added_from=(now - timedelta(days=5)).date().isoformat())
        check('sanadan keyingilari',
              '__KF_OLD__' not in recent and '__KF_CORP__' in recent, recent)
        older = tags(added_to=(now - timedelta(days=20)).date().isoformat())
        check('sanagacha bo\'lganlar', older == ['__KF_OLD__'], older)

        # Mezonlar birga ishlaydi
        check('mezonlar birga qo\'llandi',
              tags(status='active', owner='with', usage='used', expiry='soon')
              == ['__KF_CORP__'],
              tags(status='active', owner='with', usage='used', expiry='soon'))

        # ── 4. Tugmadagi son va tartiblash ──────────────────────
        page = client.get(url, {'q': 'x', 'status': 'active'})
        check('qidiruv va tab "Filtr" soniga kirmadi',
              page.context['advanced_count'] == 0, page.context['advanced_count'])
        page = client.get(url, {'owner': 'with', 'usage': 'used', 'company': 'none'})
        check('oynadagi uch mezon sanaldi',
              page.context['advanced_count'] == 3, page.context['advanced_count'])

        def order(**params):
            rows = client.get(url, params).context['page_obj']
            return [c.id_tag for c in rows if c.id_tag.startswith('__KF')]

        check('ko\'p ishlatilgan birinchi',
              order(q='__KF', sort='used')[0] == '__KF_CORP__', order(q='__KF', sort='used'))
        check('karta raqami bo\'yicha tartib',
              order(q='__KF', sort='tag') == sorted(order(q='__KF', sort='tag')),
              order(q='__KF', sort='tag'))

        # ── 5. Sahifa tuzilishi ─────────────────────────────────
        body = client.get(url).content.decode('utf-8')
        check('filtr oynasi sahifada bor', 'card-filter-modal' in body)
        check('AJAX uchun belgilangan',
              'data-live-search' in body and 'id="card-results"' in body
              and 'id="card-filter-actions"' in body)
        check('mezonlar guruhlarga bo\'lindi',
              body.count('filter-group-title') == 4, body.count('filter-group-title'))
        check('filtrsiz holatda tugma oddiy', 'is-filtered' not in body)

        filtered = client.get(url, {'owner': 'with'}).content.decode('utf-8')
        check('qo\'llanilgan filtr tugmada belgilandi',
              'is-filtered' in filtered and 'fb-count">1<' in filtered)
        check('to\'ldirilgan mezon belgilandi',
              filtered.count('field is-set') == 1, filtered.count('field is-set'))

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
