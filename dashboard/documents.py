# -*- coding: utf-8 -*-
"""Korporativ hujjatlarni yig'ish va pochta bilan yuborish.

Ilgari operator hujjatni yuklab olib, qo'lda pochtaga biriktirib
yuborardi. Oy oxirida o'nlab mijoz uchun bu bir necha soatlik ish edi va
bittasini unutib qo'yish oson.

Hujjat har safar QAYTADAN yig'iladi — mijoz rekvizitlari, tariflar va
kartalar ro'yxati o'zgarib turadi. Saqlab qo'yilgan fayl eskirgan
ma'lumot bilan chiqib ketardi.
"""
import re

from django.utils import timezone

DOCX_MIME = ('application/vnd.openxmlformats-officedocument'
             '.wordprocessingml.document')


def slug_for(name):
    """Fayl nomi uchun xavfsiz qism.

    Kirill va maxsus belgilar ba'zi pochta mijozlarida biriktirmani
    ochib bo'lmas holga keltiradi.
    """
    return re.sub(r'[^A-Za-z0-9]+', '-', name or '').strip('-').lower() or 'mijoz'


def build_contract(company):
    from .contracts import build_company_contract

    document = build_company_contract(company)
    name = f'shartnoma-{slug_for(company.name)}-{timezone.now():%Y%m%d}.docx'
    return name, document.getvalue()


def build_invoice(invoice):
    from .invoices import build_invoice_document

    document = build_invoice_document(invoice)
    return f'hisob-{invoice.number}.docx', document.getvalue()


def build_monthly(company, year, month, kind='act'):
    from .acts import build_act, build_reconciliation

    builder = build_reconciliation if kind == 'reconciliation' else build_act
    document = builder(company, year, month)
    prefix = 'solishtirma' if kind == 'reconciliation' else 'dalolatnoma'
    name = f'{prefix}-{slug_for(company.name)}-{year}-{month:02d}.docx'
    return name, document.getvalue()


def email_document(company, subject, body, filename, content):
    """Hujjatni mijozga yuboradi. `(yuborildimi, sabab)`.

    Xato TASHLANMAYDI: hujjat baribir yaratilgan va operator uni
    yuklab olib qo'lda yubora oladi. Pochta ishlamagani butun ishni
    to'xtatib qo'ymasligi kerak.
    """
    from management.mail import try_send

    if not company.contact_email:
        return False, f'{company.name} uchun pochta manzili kiritilmagan'

    return try_send(company.contact_email, subject, body,
                    attachments=[(filename, content, DOCX_MIME)])
