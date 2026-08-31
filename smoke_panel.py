# -*- coding: utf-8 -*-
"""Panelning har bir sahifasini haqiqiy so'rov bilan tekshiradi (smoke test).

Bajarish: venv/Scripts/python.exe _smoke_panel.py
Test ma'lumotlari yaratiladi va oxirida to'liq tozalanadi.
"""
import io
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import Group, User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402

from management.models import Banner, FaqItem, LegalPage, Offer, Partner  # noqa: E402
from stations.models import Station  # noqa: E402

GET_PAGES = [
    ('Bosh sahifa', '/'),
    ('Stansiyalar', '/stations/'),
    ('Qurilma holati', '/stations/health/'),
    ('Profilaktika', '/maintenance/'),
    ('RFID kartalar', '/rfid/'),
    ('RFID — tasdiqlanmagan', '/rfid/?status=pending'),
    ('Korporativ mijozlar', '/companies/'),
    ('Yangi korporativ mijoz', '/companies/new/'),
    ('Profilaktika — tuzatilganlar', '/maintenance/?state=resolved'),
    ('Yangi stansiya', '/stations/new/'),
    ('Sessiyalar', '/sessions/'),
    ('Mijozlar', '/users/'),
    ('Hamyonlar', '/wallets/'),
    ("To'lovlar", '/payments/'),
    ('Sharhlar', '/reviews/'),
    ('Sharhlar (filtr)', '/reviews/?rating=5'),
    ('Tushum hisoboti', '/reports/revenue/'),
    ('Tushum (7 kun)', '/reports/revenue/?days=7'),
    ('Foydalanish hisoboti', '/reports/usage/'),
    ('Aksiyalar', '/offers/'),
    ('Aksiyalar (amalda)', '/offers/?status=running'),
    ('Yangi aksiya', '/offers/new/'),
    ('Hamkorlar', '/partners/'),
    ('Yangi hamkor', '/partners/new/'),
    ('Menejerlar', '/managers/'),
    ('Yangi menejer', '/managers/new/'),
    ('Administratorlar', '/admins/'),
    ('Yangi administrator', '/admins/new/'),
    ('Rollar', '/roles/'),
    ('Yangi rol', '/roles/new/'),
    ('Bannerlar', '/content/banners/'),
    ('Yangi banner', '/content/banners/new/'),
    ('FAQ', '/content/faq/'),
    ('Yangi FAQ', '/content/faq/new/'),
    ('Sahifalar', '/content/pages/'),
    ('Sahifa tahrirlash', '/content/pages/privacy/'),
    ('Sozlamalar: umumiy', '/settings/general/'),
    ('Sozlamalar: to\'lov', '/settings/payment/'),
    ('Sozlamalar: bildirishnoma', '/settings/notification/'),
    ('Sozlamalar: xavfsizlik', '/settings/security/'),
    ('Sozlamalar: shartnoma', '/settings/contract/'),
    ('Sozlamalar: tashkilot', '/settings/org/'),
    ('Sozlamalar: sessiya', '/settings/session/'),
    ("Sozlamalar: to'lov tizimlari", '/settings/providers/'),
    ('Sozlamalar: bayramlar', '/settings/holiday/'),
    ('Profil', '/profile/'),
    ('OTP kodlar', '/otp/'),
    ('Amallar jurnali', '/activity/'),
]



def check_template_syntax():
    """Shablonlarni kompilyatsiya qilib ko'radi va ko'p qatorli `{# #}`
    izohlarini ushlaydi — Django'da bunday izoh MATN sifatida chiqib qoladi
    (bir qatorli sintaksis), ichidagi teglar esa xatoga olib keladi."""
    import os
    import re

    from django.template.loader import get_template

    base = 'dashboard/templates/dashboard'
    problems = []

    for root, _dirs, files in os.walk(base):
        for name in sorted(files):
            if not name.endswith('.html'):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, base).replace(os.sep, '/')

            text = io.open(path, encoding='utf-8').read()
            for number, line in enumerate(text.splitlines(), 1):
                if '{#' in line and '#}' not in line:
                    problems.append(f"{rel}:{number} — ko'p qatorli {{# #}} izoh")

            # `onsubmit="...confirm(&quot;...&quot;)"` ichidagi HAQIQIY qator
            # uzilishi JS satr literalini buzadi va tugma umuman ishlamay
            # qoladi — brauzerda jimgina, konsolda esa SyntaxError bo'lib.
            for chunk in re.findall(r'onsubmit="[^"]*"', text, re.S):
                if any(ch in chunk for ch in '\r\n'):
                    problems.append(f'{rel} — onsubmit ichida qator uzilishi')

            try:
                get_template(f'dashboard/{rel}')
            except Exception as exc:
                problems.append(f'{rel} — {exc}')


    print()
    print('-- Shablon sintaksisi --')
    if problems:
        for p in problems:
            print('XATO ', p)
    else:
        print('OK    barcha shablonlar toza')
    return problems


def main():
    created = []
    admin, _ = User.objects.get_or_create(
        username='__smoke_admin__', defaults={'is_staff': True, 'is_superuser': True}
    )
    admin.is_staff = admin.is_superuser = True
    admin.save()
    created.append(admin)

    manager, _ = User.objects.get_or_create(
        username='__smoke_manager__', defaults={'is_staff': True, 'is_superuser': False}
    )
    manager.is_staff, manager.is_superuser = True, False
    manager.save()
    created.append(manager)

    role, _ = Group.objects.get_or_create(name='__smoke_role__')
    partner, _ = Partner.objects.get_or_create(name='__smoke_partner__', defaults={'commission_percent': 10})
    offer, _ = Offer.objects.get_or_create(title='__smoke_offer__', defaults={'discount_value': 15})
    banner, _ = Banner.objects.get_or_create(title='__smoke_banner__')
    faq, _ = FaqItem.objects.get_or_create(question='__smoke_faq__', defaults={'answer': 'javob'})

    station = Station.objects.first()

    detail_pages = [
        ('Hamkor detali', f'/partners/{partner.id}/'),
        ('Hamkor tahrirlash', f'/partners/{partner.id}/edit/'),
        ('Aksiya detali', f'/offers/{offer.id}/'),
        ('Aksiya tahrirlash', f'/offers/{offer.id}/edit/'),
        ('Menejer detali', f'/managers/{manager.id}/'),
        ('Menejer tahrirlash', f'/managers/{manager.id}/edit/'),
        ('Administrator detali', f'/admins/{admin.id}/'),
        ('Rol tahrirlash', f'/roles/{role.id}/edit/'),
        ('Banner tahrirlash', f'/content/banners/{banner.id}/edit/'),
        ('FAQ tahrirlash', f'/content/faq/{faq.id}/edit/'),
    ]
    if station:
        detail_pages.append(('Stansiya detali', f'/stations/{station.id}/'))

    with override_settings(ALLOWED_HOSTS=['testserver']):
        client = Client()
        client.force_login(admin)

        failures = []
        for label, url in GET_PAGES + detail_pages:
            response = client.get(url)
            ok = response.status_code == 200
            print(f'{"OK " if ok else "XATO"}  {response.status_code}  {label:26s} {url}')
            if not ok:
                failures.append((label, url, response.status_code))

        failures.extend(check_template_syntax())

        # Yozish amallari ham ishlashini tekshiramiz
        print('\n-- POST tekshiruvlari --')
        writes = [
            # Sozlamalar bo'limlarga bo'lingan — qaysi bo'lim saqlanayotgani
            # `section` bilan aytiladi
            ('Sozlamalarni saqlash', '/settings/general/',
             {'section': 'app', 'app_name': 'VoltMax', 'support_phone': '+998900000000'}),
            ('Hamkor saqlash', f'/partners/{partner.id}/edit/', {
                'name': '__smoke_partner__', 'commission_percent': '12', 'is_active': 'on',
            }),
            ('Rol saqlash', f'/roles/{role.id}/edit/', {'name': '__smoke_role__'}),
        ]
        for label, url, data in writes:
            response = client.post(url, data)
            ok = response.status_code in (200, 302)
            print(f'{"OK " if ok else "XATO"}  {response.status_code}  {label}')
            if not ok:
                failures.append((label, url, response.status_code))

    # Tozalash
    for obj in (offer, banner, faq, partner, role):
        obj.delete()
    LegalPage.objects.filter(body='').delete()
    for user in created:
        user.delete()

    print('\n' + ('BARCHASI OK' if not failures else f'{len(failures)} TA XATO: {failures}'))


if __name__ == '__main__':
    main()
