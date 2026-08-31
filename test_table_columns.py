# -*- coding: utf-8 -*-
"""Panel jadvallarining ustunlar mosligini tekshiradi.

Uch xil nomuvofiqlik bo'ladi va uchalasi ham ko'zga tashlanmaydi — jadval
shunchaki qiyshayib chiqadi:

  1. `<thead>` dagi `<th>` soni qator `<td>` sonidan farq qiladi;
  2. bo'sh holat qatoridagi `colspan` ustunlar soniga teng emas;
  3. bir jadvalning qatorlari o'zaro har xil ustunga ega.

Skript har bir sahifani HAQIQIY so'rov bilan ochadi va ichidagi barcha
jadvalni tekshiradi. Shablonda ustun qo'shilib, `colspan` unutilsa —
shu yerda darhol ko'rinadi.
"""
import os
import re

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402

from accounts.models import Company, RfidCard  # noqa: E402
from management.models import Banner, FaqItem, Offer, Partner  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import MaintenanceIssue, Station  # noqa: E402
from wallet.models import Transaction  # noqa: E402

TABLE_RE = re.compile(r'<table[^>]*>(.*?)</table>', re.S)
THEAD_RE = re.compile(r'<thead[^>]*>(.*?)</thead>', re.S)
TBODY_RE = re.compile(r'<tbody[^>]*>(.*?)</tbody>', re.S)
ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
CELL_RE = re.compile(r'<(t[hd])\b([^>]*)>', re.S)
COLSPAN_RE = re.compile(r'colspan="(\d+)"')


def cells_in(row_html):
    """Qatordagi ustunlar soni — `colspan` hisobga olinadi."""
    total = 0
    for _tag, attrs in CELL_RE.findall(row_html):
        span = COLSPAN_RE.search(attrs)
        total += int(span.group(1)) if span else 1
    return total


def check_tables(label, html):
    """Bitta sahifadagi barcha jadvalni tekshiradi. Muammolar ro'yxati qaytadi."""
    problems = []

    for index, table in enumerate(TABLE_RE.findall(html), 1):
        head = THEAD_RE.search(table)
        body = TBODY_RE.search(table)
        if not head or not body:
            continue

        head_rows = ROW_RE.findall(head.group(1))
        if not head_rows:
            continue
        expected = cells_in(head_rows[-1])

        for number, row in enumerate(ROW_RE.findall(body.group(1)), 1):
            actual = cells_in(row)
            if actual != expected:
                where = f'{label} · {index}-jadval · {number}-qator'
                problems.append(f'{where}: sarlavhada {expected}, qatorda {actual}')

    return problems


SCRIPT_RE = re.compile(r'<(script|style)[^>]*>.*?</\1>', re.S)
COMMA_DECIMAL_RE = re.compile(r'\b\d+,\d+\b')


def check_decimals(label, html):
    """Sahifada vergulli o'nlik son qolmaganini tekshiradi.

    Loyiha `uz` lokalida ishlaydi va Django xom `float` qiymatni o'sha
    lokalning ajratgichi bilan chiqaradi: "398,4". Pul esa nuqta bilan
    ("398 400.00"). Bitta sahifada ikki xil ajratgich texnik ma'lumotda
    chalkashlik tug'diradi, shuning uchun standart — HAMMA joyda nuqta
    (`money` filtrlari: `som` va `num`).
    """
    clean = SCRIPT_RE.sub('', html)
    hits = sorted(set(COMMA_DECIMAL_RE.findall(clean)))
    if hits:
        return [f"{label}: vergulli o'nlik son — {hits[:5]} (|num yoki |som qo'ying)"]
    return []


def check_stylesheet():
    """CSS faylining butunligini tekshiradi.

    Uslublar skript bilan qo'shib borilgani uchun qavs muvozanati buzilishi
    mumkin — bunda brauzer fayl oxirigacha o'qimay tashlab yuboradi va
    sahifa "dizaynsiz" ochiladi. Xato ko'zga tashlanmaydi, shuning uchun
    tekshiruv avtomatik.
    """
    path = 'dashboard/static/dashboard/style.css'
    text = open(path, encoding='utf-8').read()
    problems = []

    if text.count('{') != text.count('}'):
        problems.append(
            f"style.css: qavslar mos emas — {text.count('{')} ta {{ va {text.count('}')} ta }}")

    # Sahifa bo'limlari bir-biriga yopishib qolmasligi uchun mustaqil
    # bloklarda pastki oraliq bo'lishi shart
    for selector in ('.device-state {', '.bulk-bar {'):
        if selector in text:
            body = text.split(selector)[1].split('}')[0]
            if 'margin-bottom' not in body:
                problems.append(f'{selector.strip(" {")}: margin-bottom yo\'q')

    # `<td>` ga `display:flex` berilsa katakcha jadval tuzilishidan chiqadi
    # va `colspan` e'tibordan qoladi — bo'sh holat butun jadval o'rniga
    # bitta ustun kengligida ko'rinadi.
    if 'td.empty {' not in text:
        problems.append("style.css: `td.empty` qoidasi yo'q (colspan buziladi)")
    else:
        body = text.split('td.empty {')[1].split('}')[0]
        if 'display: table-cell' not in body:
            problems.append('td.empty: `display: table-cell` yo\'q — colspan ishlamaydi')

    # Shablonda ishlatilgan HAR BIR input turi uslublangan bo'lishi kerak.
    # CSS'da turlar ro'yxat bilan sanab o'tilgan, shuning uchun yangi tur
    # (masalan `date`) qo'shilsa u uslubsiz — brauzerning o'z ko'rinishida —
    # chiqib qoladi va boshqa maydonlardan farq qilib turadi.
    styled_free = {'hidden', 'checkbox', 'radio', 'file', 'submit', 'button', 'image'}
    used = set()
    for root, _dirs, files in os.walk(TEMPLATE_BASE):
        for name in files:
            if name.endswith('.html'):
                source = open(os.path.join(root, name), encoding='utf-8').read()
                used.update(re.findall(r'<input[^>]*\stype="([a-z-]+)"', source))
    for kind in sorted(used - styled_free):
        if f'input[type={kind}]' not in text:
            problems.append(
                f'style.css: `input[type={kind}]` uslublanmagan — '
                "maydon boshqalardan farq qilib ko'rinadi")

    return problems


TEMPLATE_BASE = 'dashboard/templates/dashboard'
TH_RE = re.compile(r'<th[\s>]')
EMPTY_CELL_RE = re.compile(r'<td[^>]*colspan="(\d+)"')


def scan_templates():
    """Shablonlardagi bo'sh holat qatorlarini tekshiradi.

    Sahifani ochib tekshirish yetarli emas: jadvalda ma'lumot bo'lsa
    `{% empty %}` tarmog'i umuman chiqmaydi. Shu sabab shablon matnining
    o'zi o'qiladi — bo'sh holat qatori bormi va `colspan` butun jadvalni
    qamrab olganmi.
    """
    import os

    problems = []
    for root, _dirs, files in os.walk(TEMPLATE_BASE):
        for name in sorted(files):
            if not name.endswith('.html'):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, TEMPLATE_BASE).replace(os.sep, '/')
            text = open(path, encoding='utf-8').read()

            for index, table in enumerate(TABLE_RE.findall(text), 1):
                head = THEAD_RE.search(table)
                if not head:
                    continue
                expected = len(TH_RE.findall(head.group(1)))
                spans = EMPTY_CELL_RE.findall(table)
                where = f'{rel} · {index}-jadval'

                if not spans:
                    problems.append(f"{where}: bo'sh holat qatori yo'q ({expected} ustun)")
                    continue
                for span in spans:
                    if int(span) != expected:
                        problems.append(
                            f'{where}: colspan={span}, lekin {expected} ta ustun bor')
    return problems


def main():
    # Har bir sahifada kamida bitta qator bo'lishi uchun test ma'lumotlari
    admin, _ = User.objects.get_or_create(
        username='__tc_admin__', defaults={'is_staff': True, 'is_superuser': True})
    admin.is_staff = admin.is_superuser = True
    admin.save()

    pages = [
        ('Bosh sahifa', '/'),
        ('Stansiyalar', '/stations/'),
        ('Qurilma holati', '/stations/health/'),
        ('Profilaktika', '/maintenance/'),
        ('Profilaktika (bo\'sh)', '/maintenance/?station=99999999'),
        ('RFID kartalar', '/rfid/'),
        ('RFID (bo\'sh)', '/rfid/?q=__yoq__'),
        ('Korporativ', '/companies/'),
        ('Korporativ (bo\'sh)', '/companies/?q=__yoq__'),
        ('Sessiyalar', '/sessions/'),
        ('Mijozlar', '/users/'),
        ('Hamyonlar', '/wallets/'),
        ("To'lovlar", '/payments/'),
        ('Sharhlar', '/reviews/'),
        ('Tushum hisoboti', '/reports/revenue/'),
        ('Foydalanish hisoboti', '/reports/usage/'),
        ('Aksiyalar', '/offers/'),
        ('Hamkorlar', '/partners/'),
        ('Menejerlar', '/managers/'),
        ('Administratorlar', '/admins/'),
        ('Rollar', '/roles/'),
        ('Bannerlar', '/content/banners/'),
        ('FAQ', '/content/faq/'),
        ('Sahifalar', '/content/pages/'),
        ('OTP kodlar', '/otp/'),
        ('Amallar jurnali', '/activity/'),
        ('Hamkorlar hisob-kitobi', '/payouts/'),
        ('Sozlamalar: shartnoma', '/settings/contract/'),
        ("Sozlamalar: to'lov tizimlari", '/settings/providers/'),
        ('Sozlamalar: bildirishnoma', '/settings/notification/'),
        ('Sozlamalar: bayramlar', '/settings/holiday/'),
    ]

    # Detal sahifalari — mavjud yozuvlar bo'yicha
    station = Station.objects.first()
    if station:
        pages.append(('Stansiya detali', f'/stations/{station.id}/'))
    session = ChargingSession.objects.first()
    if session:
        pages.append(('Sessiya detali', f'/sessions/{session.id}/'))
        pages.append(('Mijoz detali', f'/users/{session.user_id}/'))

    from wallet.models import WalletBalance
    wallet = WalletBalance.objects.first()
    if wallet:
        pages.append(('Hamyon detali', f'/wallets/{wallet.id}/'))
    card = RfidCard.objects.first()
    if card:
        pages.append(('Karta detali', f'/rfid/{card.id}/'))
    company = Company.objects.first()
    if company:
        pages.append(('Kompaniya detali', f'/companies/{company.id}/'))
    partner = Partner.objects.first()
    if partner:
        pages.append(('Hamkor detali', f'/partners/{partner.id}/'))
    offer = Offer.objects.first()
    if offer:
        pages.append(('Aksiya detali', f'/offers/{offer.id}/'))

    # Avval shablonlarning O'ZI tekshiriladi: jadvalda ma'lumot bo'lsa
    # `{% empty %}` tarmog'i umuman chiqmaydi va xato ko'rinmay qoladi.
    problems = scan_templates() + check_stylesheet()
    checked = 0

    with override_settings(ALLOWED_HOSTS=['testserver']):
        client = Client()
        client.force_login(admin)

        for label, url in pages:
            response = client.get(url)
            if response.status_code != 200:
                problems.append(f'{label} ({url}): status {response.status_code}')
                continue
            html = response.content.decode()
            found = check_tables(label, html) + check_decimals(label, html)
            tables = len([t for t in TABLE_RE.findall(html) if THEAD_RE.search(t)])
            checked += tables
            problems.extend(found)
            mark = 'XATO' if found else 'OK  '
            print(f'{mark}  {label:24s} {tables} ta jadval  {url}')

    User.objects.filter(username='__tc_admin__').delete()

    print(f'\nJami {checked} ta jadval tekshirildi')
    if problems:
        for p in problems:
            print('XATO ', p)
        print(f'\n*** {len(problems)} TA XATO ***')
        return 1
    print('HAMMASI OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
