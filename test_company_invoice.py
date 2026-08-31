# -*- coding: utf-8 -*-
"""Korporativ mijozning bank o'tkazmasi bilan to'lovi (to'lov hisoblari).

Asosiy savollar:
  1. Hisob yozilganda hamyon o'zgarmay turadimi (pul hali kelmagan)?
  2. To'lov qayd etilganda mablag' hamyonga tushib, tranzaksiya bilan
     bog'lanadimi?
  3. Bitta hisob ikki marta to'lana oladimi (ikki operator bir vaqtda bosса)?
  4. To'langan hisobni bekor qilib bo'lmasligi ta'minlanganmi?
  5. Word hisobida ikkala tomon rekvizitlari va summa so'z bilan bormi?
  6. Hisob raqamlari yil ichida ketma-ket boradimi?
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

from accounts.models import Company, CompanyInvoice  # noqa: E402
from dashboard.invoices import amount_in_words  # noqa: E402
from management.models import SiteSettings  # noqa: E402
from wallet.models import Transaction, WalletBalance  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def document_text(payload):
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return archive.read('word/document.xml').decode('utf-8')


def _cleanup():
    CompanyInvoice.objects.filter(company__name__startswith='__ci').delete()
    Company.objects.filter(name__startswith='__ci').delete()
    User.objects.filter(username__startswith='__ci').delete()
    User.objects.filter(username__startswith='company-__ci').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    # ── Summani so'z bilan yozish ───────────────────────────────
    words = {
        0: 'nol',
        7: 'yetti',
        15: "o'n besh",
        90: "to'qson",
        100: 'bir yuz',
        # 1000 — «ming», lekin 1 000 000 — «bir million» (o'zbek tilida shunday)
        1000: 'ming',
        2500: "ikki ming besh yuz",
        1000000: 'bir million',
        12345678: "o'n ikki million uch yuz qirq besh ming olti yuz yetmish sakkiz",
    }
    wrong = {n: amount_in_words(n) for n, text in words.items() if amount_in_words(n) != text}
    check("summa so'z bilan to'g'ri yozildi", not wrong, wrong)

    settings_obj = SiteSettings.load()
    saved = {
        field: getattr(settings_obj, field)
        for field in ('org_legal_name', 'org_inn', 'org_bank_account', 'org_director')
    }

    admin = User.objects.create(username='__ci_admin__', is_staff=True, is_superuser=True)
    try:
        settings_obj.org_legal_name = '__ci VoltMax MChJ'
        settings_obj.org_inn = '305000111'
        settings_obj.org_bank_account = '20208000900000111222'
        settings_obj.org_director = 'Valiyev V.V.'
        settings_obj.save()

        company = Company.objects.create(
            billing_user=User.objects.create(username='company-__ci_taxi__'),
            name='__ci Taksi Park',
            legal_name='__ci Taksi Park MChJ',
            inn='987000111',
            bank_name='Kapitalbank',
            bank_account='20208000900999888777',
            bank_mfo='01041',
        )
        WalletBalance.objects.create(user=company.billing_user, amount=0)

        client = Client()
        create_url = reverse('dashboard:company_invoice_create', args=[company.pk])

        check('anonim foydalanuvchi hisob yoza olmadi',
              client.post(create_url, {'amount': '5 000 000'}).status_code in (302, 403))
        check('anonim urinishdan keyin hisob yaratilmadi',
              not CompanyInvoice.objects.filter(company=company).exists())

        client.force_login(admin)

        # ── 1. Hisob yozish ─────────────────────────────────────
        client.post(create_url, {'amount': '5 000 000', 'purpose': '__ci avans'})
        invoice = CompanyInvoice.objects.filter(company=company).first()
        check('hisob yozildi', invoice is not None and invoice.amount == 5000000,
              invoice.amount if invoice else None)
        check('hisob to\'lov kutish holatida', invoice.is_pending, invoice.status)
        check('hisob yozilganda hamyon o\'zgarmadi', company.balance == 0, company.balance)

        # Noto'g'ri summa
        client.post(create_url, {'amount': 'salom'})
        client.post(create_url, {'amount': '0'})
        check('noto\'g\'ri va nol summa rad etildi',
              CompanyInvoice.objects.filter(company=company).count() == 1)

        # ── 2. Word hujjati ─────────────────────────────────────
        document = client.get(reverse('dashboard:company_invoice_document', args=[invoice.pk]))
        payload = (b''.join(document.streaming_content)
                   if document.streaming else document.content)
        check('hisob hujjati yuklandi',
              document.status_code == 200 and zipfile.is_zipfile(BytesIO(payload)),
              document.status_code)
        check('fayl nomida hisob raqami bor',
              f'hisob-{invoice.number}.docx' in document.get('Content-Disposition', ''),
              document.get('Content-Disposition'))

        text = document_text(payload)
        # Hisob raqami bo'laklangan holda chiqadi (20208 000 9 ...)
        expected = ['__ci VoltMax MChJ', '305 000 111', '20208 000 9 00000111 222',
                    '__ci Taksi Park MChJ', '987 000 111', '20208 000 9 00999888 777',
                    '__ci avans', invoice.number]
        missing = [value for value in expected if value not in text]
        check('hujjatda ikkala tomon rekvizitlari va maqsad bor', not missing, missing)
        check('summa so\'z bilan hujjatda',
              'besh million' in text, 'besh million' in text)

        # ── 3. To'lovni qayd etish ──────────────────────────────
        paid_url = reverse('dashboard:company_invoice_paid', args=[invoice.pk])
        client.post(paid_url, {'payment_ref': '142', 'payment_date': '2026-08-25'})
        invoice.refresh_from_db()
        company.refresh_from_db()

        check('hisob to\'langan bo\'ldi',
              invoice.status == CompanyInvoice.Status.PAID, invoice.status)
        check('mablag\' hamyonga tushdi', company.balance == 5000000, company.balance)
        check('tranzaksiya yaratildi va hisobga bog\'landi',
              invoice.transaction is not None
              and invoice.transaction.type == Transaction.Type.TOPUP
              and invoice.transaction.amount == 5000000)
        check('tranzaksiya izohida topshiriqnoma raqami bor',
              '142' in (invoice.transaction.description or ''),
              invoice.transaction.description)
        check('o\'tkazma sanasi saqlandi',
              str(invoice.payment_date) == '2026-08-25', invoice.payment_date)

        # ── 4. Ikki marta to'lash mumkin emas ───────────────────
        client.post(paid_url, {'payment_ref': '143'})
        company.refresh_from_db()
        check('ikkinchi marta to\'lanmadi (balans o\'zgarmadi)',
              company.balance == 5000000, company.balance)
        check('qo\'shimcha tranzaksiya yaratilmadi',
              Transaction.objects.filter(user=company.billing_user).count() == 1)

        # ── 5. Bekor qilish ─────────────────────────────────────
        client.post(reverse('dashboard:company_invoice_cancel', args=[invoice.pk]))
        invoice.refresh_from_db()
        check('to\'langan hisob bekor qilinmadi',
              invoice.status == CompanyInvoice.Status.PAID, invoice.status)

        client.post(create_url, {'amount': '1 000 000'})
        second = CompanyInvoice.objects.filter(company=company).exclude(pk=invoice.pk).first()
        check('hisob raqami ketma-ket bordi',
              int(second.number.split('-')[1]) == int(invoice.number.split('-')[1]) + 1,
              f'{invoice.number} -> {second.number}')

        client.post(reverse('dashboard:company_invoice_cancel', args=[second.pk]))
        second.refresh_from_db()
        company.refresh_from_db()
        check('to\'lanmagan hisob bekor qilindi',
              second.status == CompanyInvoice.Status.CANCELLED, second.status)
        check('bekor qilish balansga tegmadi', company.balance == 5000000, company.balance)

        # ── 6. Mijoz sahifasida ko'rinishi ──────────────────────
        page = client.get(reverse('dashboard:company_detail', args=[company.pk]))
        body = page.content.decode('utf-8')
        check('mijoz sahifasi ochildi', page.status_code == 200, page.status_code)
        check('hisoblar ro\'yxatda ko\'rinadi',
              f'№{invoice.number}' in body and f'№{second.number}' in body)
        check('bekor qilingan hisobda "to\'landi" tugmasi yo\'q',
              f'invoice-{second.pk}-paid-modal' not in body)

        # To'lovni qayd etish oynasi: qaysi hisob, qancha summa va balans
        # qanday o'zgarishi tasdiqlashdan OLDIN ko'rinishi kerak
        third = CompanyInvoice.objects.filter(
            company=company, status=CompanyInvoice.Status.PENDING).first()
        if third is None:
            client.post(create_url, {'amount': '3 000 000'})
            third = CompanyInvoice.objects.filter(
                company=company, status=CompanyInvoice.Status.PENDING).first()
        page = client.get(reverse('dashboard:company_detail', args=[company.pk]))
        body = page.content.decode('utf-8').replace(' ', ' ')
        check('qayd etish oynasi ochiladigan tugma bor',
              f'invoice-{third.pk}-paid-modal' in body)
        check("oynada tasdiqlangandan keyingi balans ko'rsatilgan",
              format(company.balance + third.amount, ',').replace(',', ' ') in body,
              company.balance + third.amount)

        # Kutilayotgan summa: bittasi to'langan, bittasi bekor — demak 0
        client.post(create_url, {'amount': '2 000 000'})
        page = client.get(reverse('dashboard:company_detail', args=[company.pk]))
        check('kutilayotgan summa ko\'rsatildi',
              '2 000 000' in page.content.decode('utf-8').replace('\xa0', ' '))

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
