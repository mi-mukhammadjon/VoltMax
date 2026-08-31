# -*- coding: utf-8 -*-
"""Bank hisob raqami: format va 20 xonalik tekshiruv.

Asosiy savollar:
  1. Raqam hamma joyda `20208 000 5 00123612 001` ko'rinishida chiqadimi —
     panelda ham, Word hujjatlarida ham?
  2. Bazada bo'laklarsiz, faqat raqamlar saqlanadimi (bir hisob ikki xil
     yozilib qolmasligi uchun)?
  3. 20 xonadan farq qilsa saqlanmaydimi va sabab aytiladimi?
  4. Bu tekshiruv IKKALA tomon uchun ham ishlaydimi — mijoz kartochkasida
     ham, o'z rekvizitlarimizda ham (Sozlamalar)?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.urls import reverse  # noqa: E402

from accounts.models import Company  # noqa: E402
from dashboard.banking import (  # noqa: E402
    format_account, format_inn, normalize_account, normalize_inn,
)
from management.models import SiteSettings  # noqa: E402

failures = 0

FULL = '20208000500123612001'
PRETTY = '20208 000 5 00123612 001'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    Company.objects.filter(name__startswith='__ba').delete()
    User.objects.filter(username__startswith='__ba').delete()
    User.objects.filter(username__startswith='company-__ba').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    # ── 1. Format ───────────────────────────────────────────────
    check('20 xonali raqam bo\'laklandi', format_account(FULL) == PRETTY, format_account(FULL))
    check('bo\'laklangan qiymat qayta bo\'laklanmadi',
          format_account(PRETTY) == PRETTY, format_account(PRETTY))
    check('bazaga bo\'laksiz tushadi', normalize_account(PRETTY) == FULL,
          normalize_account(PRETTY))
    check('bo\'sh qiymat bo\'sh qoldi', format_account('') == '' and normalize_account(None) == '')
    # To'liqsiz raqam ham bo'laklanadi: xato ko'zga tashlanadi
    check('to\'liqsiz raqam ham bo\'laklandi',
          format_account('20208000500') == '20208 000 5 00', format_account('20208000500'))
    check('ortiqcha raqam yo\'qolmadi',
          format_account(FULL + '99').endswith('99'), format_account(FULL + '99'))

    settings_obj = SiteSettings.load()
    saved = settings_obj.org_bank_account
    saved_inn = settings_obj.org_inn
    admin = User.objects.create(username='__ba_admin__', is_staff=True, is_superuser=True)
    try:
        client = Client()
        client.force_login(admin)

        # ── 2. Mijoz kartochkasi ────────────────────────────────
        client.post(reverse('dashboard:company_new'), {
            'name': '__ba Taksi', 'is_active': 'on', 'bank_account': PRETTY,
            'inn': '305 123 456',
        })
        company = Company.objects.filter(name='__ba Taksi').first()
        check('mijoz yaratildi', company is not None)
        check('hisob raqami bo\'laksiz saqlandi',
              company.bank_account == FULL, company.bank_account)

        detail = client.get(reverse('dashboard:company_detail',
                                    args=[company.pk])).content.decode('utf-8')
        check("STIR ham bo'laksiz saqlandi", company.inn == '305123456', company.inn)
        check('batafsil sahifada bo\'laklangan', PRETTY in detail)
        check('maydonda ham bo\'laklangan',
              f'value="{PRETTY}"' in detail, PRETTY in detail)
        check('maydon maskalangan',
              'account-input' in detail and 'inn-input' in detail)
        check("STIR sahifada bo'laklangan", '305 123 456' in detail)

        # ── 3. 20 xonalik tekshiruv ─────────────────────────────
        section = reverse('dashboard:company_section_edit', args=[company.pk, 'requisites'])
        response = client.post(section, {'bank_account': '20208 000 5 001'}, follow=True)
        company.refresh_from_db()
        check('qisqa raqam saqlanmadi', company.bank_account == FULL, company.bank_account)
        text = response.content.decode('utf-8')
        check('sabab aytildi — nechta raqam kerakligi',
              '20 ta raqamdan iborat' in text and 'hozir 12 ta' in text,
              [line for line in text.splitlines() if '20 ta raqam' in line][:1])

        response = client.post(section, {'bank_account': FULL + '5'}, follow=True)
        company.refresh_from_db()
        check('uzun raqam ham saqlanmadi', company.bank_account == FULL, company.bank_account)

        # Bo'sh qoldirish mumkin — rekvizit keyin to'ldiriladi
        client.post(section, {'bank_account': ''})
        company.refresh_from_db()
        check('bo\'sh qoldirishga ruxsat', company.bank_account == '', company.bank_account)

        # STIR ham 9 xona bo'lishi kerak. Bo'lim formasi BUTUN bo'limni
        # saqlaydi, shuning uchun avval to'g'ri qiymatni qaytarib qo'yamiz
        client.post(section, {'inn': '305 123 456'})
        response = client.post(section, {'inn': '30512'}, follow=True)
        company.refresh_from_db()
        check('qisqa STIR saqlanmadi', company.inn == '305123456', company.inn)
        check('STIR uchun sabab aytildi',
              '9 ta raqamdan iborat' in response.content.decode('utf-8'))

        # ── 4. Bizning rekvizitlar (Sozlamalar) ─────────────────
        # Rekvizitlar «Tashkilot» tabida, o'z bo'limida saqlanadi
        settings_url = reverse('dashboard:settings_org')
        client.post(settings_url, {
            'section': 'org', 'org_bank_account': PRETTY, 'org_inn': '305 123 456',
        })
        settings_obj.refresh_from_db()
        check("sozlamalarda STIR bo'laksiz saqlandi",
              settings_obj.org_inn == '305123456', settings_obj.org_inn)
        check('sozlamalarda ham bo\'laksiz saqlandi',
              settings_obj.org_bank_account == FULL, settings_obj.org_bank_account)

        page = client.get(settings_url).content.decode('utf-8')
        check('sozlamalar maydonida bo\'laklangan', f'value="{PRETTY}"' in page)

        client.post(settings_url, {'section': 'org', 'org_bank_account': '2020800050'})
        settings_obj.refresh_from_db()
        check('sozlamalarda qisqa raqam saqlanmadi',
              settings_obj.org_bank_account == FULL, settings_obj.org_bank_account)

    finally:
        settings_obj.org_bank_account = saved
        settings_obj.org_inn = saved_inn
        settings_obj.save(update_fields=['org_bank_account', 'org_inn'])
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
