# -*- coding: utf-8 -*-
"""Korporativ mijozni tahrirlash va telefon raqamlari formati.

Asosiy savollar:
  1. Batafsil sahifada bo'limlar o'z tugmasi bilan tahrirlanadimi va
     alohida tahrirlash sahifasi qolmaganmi?
  2. Bir bo'limni saqlash boshqasining ma'lumotini o'chirib yubormaydimi?
  3. Bir bo'limdagi xato ikkinchisini saqlashga xalaqit qilmaydimi?
  4. Telefon raqami har xil yozilsa ham bazada bir xil saqlanadimi?
  5. Ekranda raqam `+998 (95) 099-55-10` ko'rinishida chiqadimi?
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
from dashboard.phones import format_phone, normalize_phone  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    Company.objects.filter(name__startswith='__ce').delete()
    User.objects.filter(username__startswith='__ce').delete()
    User.objects.filter(username__startswith='company-__ce').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    # ── 1. Raqamni kanonik holga keltirish ──────────────────────
    canonical = '+998950995510'
    variants = ['+998 (95) 099-55-10', '998950995510', '95 099 55 10',
                '+998950995510', '8 95 099 55 10']
    wrong = {v: normalize_phone(v) for v in variants if normalize_phone(v) != canonical}
    check('har xil yozuv bir xil saqlandi', not wrong, wrong)
    check('bo\'sh qiymat bo\'sh qoldi', normalize_phone('') == '' and normalize_phone(None) == '')

    check('ekranda formatlandi',
          format_phone(canonical) == '+998 (95) 099-55-10', format_phone(canonical))
    check('kodsiz raqam ham formatlandi',
          format_phone('950995510') == '+998 (95) 099-55-10', format_phone('950995510'))
    # Bazada eski, to'liqsiz raqamlar bor (maydon ilgari hech narsani
    # tekshirmasdi). Ular ham SHU ko'rinishda chiqadi — yetishmagan joyi
    # bo'sh qoladi va xato ko'zga tashlanadi, raqam esa o'ylab topilmaydi
    check("to'liqsiz raqam ham formatlandi",
          format_phone('99895212121') == '+998 (95) 212-12-1',
          format_phone('99895212121'))
    check("xodim logini o'zgarmadi", format_phone('admin') == 'admin')

    # Chet el raqamini noto'g'ri bo'laklarga bo'lish uni o'qishni qiyinlashtiradi
    check('chet el raqami o\'zgarmadi',
          format_phone('+7 495 123 45 67') == '+7 495 123 45 67',
          format_phone('+7 495 123 45 67'))

    admin = User.objects.create(username='__ce_admin__', is_staff=True, is_superuser=True)
    try:
        client = Client()
        client.force_login(admin)

        # ── 2. Yangi mijoz ──────────────────────────────────────
        client.post(reverse('dashboard:company_new'), {
            'name': '__ce Taksi',
            'contact_name': 'Karimov',
            'contact_phone': '+998 (95) 099-55-10',
            'is_active': 'on',
            'inn': '305111222',
        })
        company = Company.objects.filter(name='__ce Taksi').first()
        check('mijoz yaratildi', company is not None)
        check('telefon kanonik holda saqlandi',
              company.contact_phone == canonical, company.contact_phone)
        check('hamyon ham yaratildi', company.wallet is not None)

        # ── 3. Bo'limlar bo'yicha tahrirlash ────────────────────
        detail = reverse('dashboard:company_detail', args=[company.pk])
        body = client.get(detail).content.decode('utf-8')
        check('bo\'lim oynalari sahifada',
              'company-basics-modal' in body and 'company-requisites-modal' in body)
        check('bo\'limlar ustida tahrirlash tugmasi bor',
              body.count('data-modal-open="#company-basics-modal"') == 1
              and body.count('data-modal-open="#company-requisites-modal"') >= 1)
        check('alohida tahrirlash sahifasiga havola qolmadi',
              f'/companies/{company.pk}/edit/"' not in body)
        check('telefon ekranda formatlangan', '+998 (95) 099-55-10' in body)

        # Eski manzil batafsilga qaytaradi (havola saqlanib qolgan bo'lsa)
        moved = client.get(reverse('dashboard:company_edit', args=[company.pk]))
        check('eski tahrirlash manzili batafsilga yo\'naltirdi',
              moved.status_code == 302 and moved['Location'].endswith(detail),
              moved.status_code)

        # Rekvizitlarni saqlash mijoz nomini o'chirmasligi kerak
        client.post(reverse('dashboard:company_section_edit',
                            args=[company.pk, 'requisites']), {
            'legal_name': '__ce Taksi MChJ',
            'inn': '305999888',
            'bank_account': '20208000900999888777',
            'bank_mfo': '01041',
            'director': 'Valiyev V.V.',
        })
        company.refresh_from_db()
        check('rekvizitlar saqlandi',
              company.inn == '305999888' and company.bank_mfo == '01041', company.inn)
        check('boshqa bo\'lim ma\'lumoti saqlanib qoldi',
              company.name == '__ce Taksi' and company.contact_phone == canonical,
              company.name)

        # Asosiy bo'lim: telefon yana har xil formatda kelishi mumkin
        client.post(reverse('dashboard:company_section_edit',
                            args=[company.pk, 'basics']), {
            'name': '__ce Taksi Park',
            'contact_name': 'Karimov K.',
            'contact_phone': '95 099 55 10',
            'is_active': 'on',
        })
        company.refresh_from_db()
        check('asosiy bo\'lim saqlandi', company.name == '__ce Taksi Park', company.name)
        check('telefon yana kanonik holda',
              company.contact_phone == canonical, company.contact_phone)
        check('rekvizitlarga tegilmadi', company.inn == '305999888', company.inn)

        # ── 4. Xato bo'lgan bo'lim ──────────────────────────────
        response = client.post(reverse('dashboard:company_section_edit',
                                       args=[company.pk, 'requisites']),
                               {'inn': '123', 'legal_name': '__ce Taksi MChJ'},
                               follow=True)
        company.refresh_from_db()
        text = response.content.decode('utf-8')
        check('noto\'g\'ri STIR saqlanmadi', company.inn == '305999888', company.inn)
        check('xato xabari ko\'rsatildi', 'STIR' in text and 'raqamdan' in text)

        # Noma'lum bo'lim nomi hech narsani buzmaydi
        unknown = client.post(reverse('dashboard:company_section_edit',
                                      args=[company.pk, 'yoq-bunday']))
        company.refresh_from_db()
        check('noma\'lum bo\'lim e\'tiborsiz qoldirildi',
              unknown.status_code == 302 and company.name == '__ce Taksi Park')

        # ── 5. Panelning boshqa sahifalarida ham formatlangan ───
        # Mobil foydalanuvchining logini — raqamning O'ZI, shuning uchun
        # ro'yxatlarda u ham formatlanadi
        driver = User.objects.create(username='998901112233')
        import re as _re

        pages = ['/users/', '/rfid/', '/sessions/', '/wallets/', '/payments/']
        raw = {}
        for page_url in pages:
            text = client.get(page_url).content.decode('utf-8')
            found = _re.findall(r'>\s*\+?998\d{9}', text)
            if found:
                raw[page_url] = found[:2]
        check('xom raqam qolmadi', not raw, raw)

        users_page = client.get('/users/').content.decode('utf-8')
        check("ro'yxatda formatlangan raqam bor",
              '+998 (90) 111-22-33' in users_page)

        cards_page = client.get('/rfid/').content.decode('utf-8')
        check("egasini tanlash ro'yxati ham formatlangan",
              '+998 (90) 111-22-33</option>' in cards_page)
        driver.delete()

        # ── 6. Formadagi maydon ─────────────────────────────────
        page = client.get(reverse('dashboard:company_new')).content.decode('utf-8')
        check('telefon maydoni maskalangan',
              'phone-input' in page and 'type="tel"' in page)

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
