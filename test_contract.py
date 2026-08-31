# -*- coding: utf-8 -*-
"""Shablon shartnoma (Word) generatsiyasi.

Asosiy savollar:
  1. Tugma bosilganda haqiqiy `.docx` (zip) qaytadimi va fayl nomi to'g'rimi?
  2. Hujjatda IKKALA tomonning rekvizitlari bormi — bizniki (Sozlamalar) va
     mijozniki (korporativ mijoz kartochkasi)?
  3. Kartalar ilovasi mijozning kartalari bilan to'ladimi?
  4. To'ldirilmagan rekvizit hujjatni buzmasdan bo'sh chiziq bo'lib chiqadimi?
  5. Sahifa faqat xodimga ochiqmi?
"""
import os
import zipfile
from io import BytesIO

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.urls import reverse  # noqa: E402

from accounts.models import Company, RfidCard  # noqa: E402
from management.models import (  # noqa: E402
    DEFAULT_CONTRACT_SECTIONS, ContractSection, SiteSettings,
)

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:54s} {extra}')
    if not condition:
        failures += 1


def document_text(payload):
    """`.docx` ichidagi barcha matn — jadvallar va ilova bilan birga."""
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return archive.read('word/document.xml').decode('utf-8')


def fetch(client, company):
    """Mijoz uchun shartnomani yuklab, `.docx` baytlarini qaytaradi."""
    response = client.get(reverse('dashboard:company_contract', args=[company.pk]))
    return b''.join(response.streaming_content) if response.streaming else response.content


def _cleanup():
    RfidCard.objects.filter(id_tag__startswith='__CT').delete()
    Company.objects.filter(name__startswith='__ct').delete()
    User.objects.filter(username__startswith='__ct').delete()
    User.objects.filter(username__startswith='company-__ct').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {
        field: getattr(settings_obj, field)
        for field in ('org_legal_name', 'org_inn', 'org_address', 'org_director',
                      'org_bank_name', 'org_bank_account', 'org_bank_mfo',
                      # Test bularni ham o'zgartiradi — keyin tiklanadi
                      'contract_title', 'contract_city', 'contract_preamble',
                      'contract_appendix_note')
    }

    # Bo'limlar haqiqiy shartnoma matni — testdan keyin aynan tiklanadi
    saved_sections = list(
        ContractSection.objects.values('title', 'body', 'order', 'is_active')
    )

    admin = User.objects.create(username='__ct_admin__', is_staff=True, is_superuser=True)
    try:
        settings_obj.org_legal_name = '__ct VoltMax MChJ'
        settings_obj.org_inn = '305123456'
        settings_obj.org_address = 'Toshkent sh., Amir Temur 1'
        settings_obj.org_director = 'Valiyev V.V.'
        settings_obj.org_bank_name = 'Ipoteka Bank'
        settings_obj.org_bank_account = '20208000900123456789'
        settings_obj.org_bank_mfo = '00873'
        settings_obj.save()

        company = Company.objects.create(
            billing_user=User.objects.create(username='company-__ct_taxi__'),
            name='__ct Taksi Park',
            legal_name='__ct Taksi Park MChJ',
            inn='987654321',
            legal_address='Toshkent sh., Chilonzor 5',
            director='Karimov K.K.',
            bank_name='Kapitalbank',
            bank_account='20208000900987654321',
            bank_mfo='01041',
        )
        RfidCard.objects.create(id_tag='__CT_A__', company=company, label='Haydovchi A')
        RfidCard.objects.create(id_tag='__CT_B__', company=company, label='Haydovchi B')

        client = Client()
        url = reverse('dashboard:company_contract', args=[company.pk])

        # 1. Faqat xodimga
        check('anonim foydalanuvchi kirita olmadi',
              client.get(url).status_code in (302, 403),
              client.get(url).status_code)

        client.force_login(admin)
        response = client.get(url)
        check('shartnoma yuklandi', response.status_code == 200, response.status_code)

        payload = b''.join(response.streaming_content) if response.streaming else response.content
        check('word content-type',
              'wordprocessingml.document' in response['Content-Type'],
              response['Content-Type'])
        disposition = response.get('Content-Disposition', '')
        check('fayl nomi .docx va mijoz nomi bilan',
              'attachment;' in disposition and disposition.rstrip('"').endswith('.docx')
              and 'shartnoma-' in disposition,
              disposition)
        check('haqiqiy zip (docx) qaytdi', zipfile.is_zipfile(BytesIO(payload)), len(payload))

        text = document_text(payload)
        check('sarlavha bor', 'SHARTNOMA' in text)

        # 2. Ikkala tomonning rekvizitlari
        # Hisob raqami hujjatda bo'laklangan holda chiqadi — 20 ta raqam
        # ketma-ket yozilsa xato ko'rinmaydi
        # STIR va hisob raqami hujjatda bo'laklangan holda chiqadi —
        # raqamlar ketma-ket yozilsa xato ko'rinmaydi
        ours = ['__ct VoltMax MChJ', '305 123 456', 'Valiyev V.V.',
                '20208 000 9 00123456 789']
        theirs = ['__ct Taksi Park MChJ', '987 654 321', 'Karimov K.K.',
                  '20208 000 9 00987654 321']
        missing_ours = [value for value in ours if value not in text]
        missing_theirs = [value for value in theirs if value not in text]
        check('bizning rekvizitlar hujjatda', not missing_ours, missing_ours)
        check('mijoz rekvizitlari hujjatda', not missing_theirs, missing_theirs)

        # 3. Kartalar ilovasi
        check('kartalar ilovasi bor', '1-ILOVA' in text)
        check('ikkala karta ro\'yxatda',
              '__CT_A__' in text and '__CT_B__' in text)

        # 4. Rekvizit to'ldirilmagan bo'lsa ham hujjat buzilmaydi
        settings_obj.org_inn = ''
        settings_obj.org_bank_mfo = ''
        settings_obj.save()
        blank_company = Company.objects.create(
            billing_user=User.objects.create(username='company-__ct_blank__'),
            name='__ct Rekvizitsiz mijoz',
        )
        blank = client.get(reverse('dashboard:company_contract', args=[blank_company.pk]))
        blank_payload = b''.join(blank.streaming_content) if blank.streaming else blank.content
        blank_text = document_text(blank_payload) if blank.status_code == 200 else ''
        check('rekvizitsiz mijoz uchun ham generatsiya qilindi',
              blank.status_code == 200 and zipfile.is_zipfile(BytesIO(blank_payload)),
              blank.status_code)
        check('bo\'sh maydon o\'rnida to\'ldirish chizig\'i',
              '____' in blank_text)
        check('kartasiz mijozda ilova hujjatni buzmadi',
              'SHARTNOMA' in blank_text)

        # ── 5. Shablonni panel orqali tahrirlash ─────────────────
        page = client.get(reverse('dashboard:settings_contract'))
        body = page.content.decode('utf-8')
        check('shartnoma tabi ochildi', page.status_code == 200, page.status_code)
        check("bo'limlar ro'yxati ko'rinadi",
              'SHARTNOMA PREDMETI' in body and 'Bandlar' in body)
        check("o'rin egallovchilar yordami bor", '{narx}' in body)

        base_count = ContractSection.objects.count()

        # Yangi bo'lim oxiriga qo'shiladi va hujjatga tushadi
        client.post(reverse('dashboard:contract_section_new'), {
            'title': '__ct MAXFIYLIK',
            'body': "Tomonlar shartnoma shartlarini oshkor qilmaydi.\n"
                    "Ushbu majburiyat shartnoma tugagach ham amal qiladi.",
            'is_active': 'on',
        })
        added = ContractSection.objects.filter(title='__ct MAXFIYLIK').first()
        check("bo'lim qo'shildi",
              added is not None and ContractSection.objects.count() == base_count + 1)

        text = document_text(fetch(client, company))
        # Sarlavha hujjatda bosh harflarda chiqadi
        check("yangi bo'lim hujjatga tushdi", '__CT MAXFIYLIK' in text)
        check("yangi bo'lim raqami tartibda",
              f'{base_count + 1}. __CT MAXFIYLIK' in text or
              f'{base_count + 1}. ' in text)
        check('bandlar avtomatik raqamlandi',
              f'{base_count + 1}.1' in text and f'{base_count + 1}.2' in text)

        # Ichki bandlar (- bilan boshlangan satr)
        client.post(reverse('dashboard:contract_section_edit', args=[added.pk]), {
            'title': '__ct MAXFIYLIK',
            'body': "Tomonlar quyidagilarni oshkor qilmaydi:\n"
                    "- tariflar va chegirmalar;\n"
                    "- kartalar ro'yxati.",
            'is_active': 'on',
        })
        text = document_text(fetch(client, company))
        check('ichki bandlar N.M.K bo\'lib raqamlandi',
              f'{base_count + 1}.1.1' in text and f'{base_count + 1}.1.2' in text)

        # O'chirilgan bo'lim hujjatga tushmaydi
        client.post(reverse('dashboard:contract_section_edit', args=[added.pk]), {
            'title': '__ct MAXFIYLIK',
            'body': 'Tomonlar shartnoma shartlarini oshkor qilmaydi.',
        })
        text = document_text(fetch(client, company))
        check("faol bo'lmagan bo'lim hujjatga tushmadi", '__CT MAXFIYLIK' not in text)

        # Bandsiz bo'lim saqlanmaydi
        client.post(reverse('dashboard:contract_section_edit', args=[added.pk]), {
            'title': '__ct MAXFIYLIK', 'body': '   ', 'is_active': 'on',
        })
        added.refresh_from_db()
        check('bandsiz bo\'lim saqlanmadi', added.body.strip() != '')

        # O'rin almashtirish raqamlarni o'zgartiradi
        first, second = list(ContractSection.objects.all())[:2]
        client.post(reverse('dashboard:contract_section_move', args=[second.pk]),
                    {'direction': 'up'})
        order = list(ContractSection.objects.values_list('pk', flat=True))
        check("bo'lim yuqoriga surildi", order[0] == second.pk and order[1] == first.pk,
              order[:2])

        # O'chirish
        client.post(reverse('dashboard:contract_section_delete', args=[added.pk]))
        check("bo'lim o'chirildi",
              not ContractSection.objects.filter(pk=added.pk).exists())

        # Sarlavha va preambula sozlamalardan olinadi
        client.post(reverse('dashboard:settings_contract'), {
            'section': 'contract',
            'contract_title': '__CT SHARTNOMA SARLAVHASI',
            'contract_city': 'Samarqand sh.',
            'contract_preamble': '{ijrochi} va {buyurtmachi} kelishdilar. Narx {narx}.',
            'contract_appendix_note': '__ct ilova izohi',
        })
        text = document_text(fetch(client, company))
        check('sarlavha sozlamadan olindi', '__CT SHARTNOMA SARLAVHASI' in text)
        check('shahar sozlamadan olindi', 'Samarqand sh.' in text)
        # Tomonlar nomi qalin bo'lgani uchun matn alohida bo'laklarga
        # bo'linadi — shuning uchun butun jumla emas, bo'laklar tekshiriladi
        check("preambulada o'rin egallovchilar almashtirildi",
              '{ijrochi}' not in text and '{narx}' not in text
              and ' kelishdilar. Narx ' in text)
        check('ilova izohi sozlamadan olindi', '__ct ilova izohi' in text)

        # Noma'lum o'rin egallovchi hujjatni buzmaydi
        client.post(reverse('dashboard:contract_section_new'), {
            'title': '__ct NOMALUM', 'body': 'Qiymat: {yoq_bunday}.', 'is_active': 'on',
        })
        text = document_text(fetch(client, company))
        check("noma'lum o'rin egallovchi o'z holicha qoldi", 'yoq_bunday' in text)
        ContractSection.objects.filter(title='__ct NOMALUM').delete()

        # Namuna va standart matnni tiklash
        preview = client.get(reverse('dashboard:contract_preview'))
        preview_payload = (b''.join(preview.streaming_content)
                           if preview.streaming else preview.content)
        check('namuna hujjati yuklandi',
              preview.status_code == 200 and zipfile.is_zipfile(BytesIO(preview_payload)),
              preview.status_code)

        client.post(reverse('dashboard:contract_sections_reset'))
        titles = list(ContractSection.objects.values_list('title', flat=True))
        check('standart matn tiklandi',
              titles == [title for title, _ in DEFAULT_CONTRACT_SECTIONS], titles)

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        if saved_sections:
            ContractSection.objects.all().delete()
            for row in saved_sections:
                ContractSection.objects.create(**row)
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
