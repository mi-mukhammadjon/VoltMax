# -*- coding: utf-8 -*-
"""Sozlamalar bo'limi: bo'limlar, jurnal, to'lov tizimlari va qidiruv.

Asosiy savollar:
  1. Har bo'lim ALOHIDA saqlanadimi — bir bo'limni saqlash boshqasining
     qiymatini o'zgartirib yubormaydimi?
  2. Har o'zgarish jurnalga tushadimi (kim, qachon, eski → yangi)?
  3. Xavfli sozlamalarda tasdiq so'raladimi va ta'sir ko'lami aytiladimi?
  4. To'lov tizimlarini qo'shish/tahrirlash/o'chirish ishlaydimi va maxfiy
     kalit oshkor bo'lmaydimi?
  5. Qidiruv sozlama qaysi tabda ekanini topadimi?
  6. Yangi sozlamalar (minimal balans, sessiya cheklovi, ish vaqti) saqlanadimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.urls import reverse  # noqa: E402

from management.models import (  # noqa: E402
    PaymentProvider, SettingsChange, SiteSettings,
)

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    PaymentProvider.objects.filter(code__startswith='__st').delete()
    SettingsChange.objects.filter(section__startswith='__st').delete()
    User.objects.filter(username__startswith='__st').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {
        field: getattr(settings_obj, field)
        for field in ('app_name', 'support_telegram', 'default_price_per_kwh',
                      'min_topup', 'max_topup', 'min_balance_to_start',
                      'max_session_minutes', 'work_all_day', 'maintenance_mode')
    }
    admin = User.objects.create(username='__st_admin__', is_staff=True, is_superuser=True)
    try:
        client = Client()
        general = reverse('dashboard:settings_general')
        check('anonim foydalanuvchiga yopiq',
              client.get(general).status_code in (302, 403))

        client.force_login(admin)

        # ── 1. Tablar va bo'limlar ──────────────────────────────
        body = client.get(general).content.decode('utf-8')
        for tab in ('/settings/org/', '/settings/providers/', '/settings/session/'):
            check(f'{tab} tabi ro\'yxatda', tab in body)
        check('bo\'limlar alohida formada',
              body.count('name="section"') >= 2, body.count('name="section"'))
        check('qidiruv maydoni bor', 'settings_search' in body or '/settings/search/' in body)

        # ── 1b. Sozlamalar HAR SAFAR bazadan o'qiladi ───────────
        # Ilgari yozuv xotirada 5 daqiqa saqlanardi. Xotira jarayonga
        # tegishli: server bir nechta jarayonda ishlaganda saqlash faqat
        # o'z nusxasini yangilardi, qolganlari esa eski qiymatni ko'rsatib
        # turardi — "saqladim, lekin o'zgarmadi" shundan kelib chiqardi.
        SiteSettings.objects.filter(pk=1).update(app_name='__st boshqa jarayon')
        check("boshqa jarayondagi o'zgarish darhol ko'rindi",
              SiteSettings.load().app_name == '__st boshqa jarayon',
              SiteSettings.load().app_name)
        page = client.get(general).content.decode('utf-8')
        check('sahifada ham yangi qiymat', '__st boshqa jarayon' in page)

        # Tekshiruvdan o'tmagan forma umumiy obyektni ifloslantirmasligi kerak
        dirty = SiteSettings.load()
        dirty.app_name = 'saqlanmagan tahrir'
        check("saqlanmagan tahrir boshqa so'rovga o'tmadi",
              SiteSettings.load().app_name == '__st boshqa jarayon',
              SiteSettings.load().app_name)

        # ── 2. Bo'limni saqlash boshqasiga tegmaydi ─────────────
        before_mode = settings_obj.maintenance_mode
        client.post(general, {'section': 'app', 'app_name': '__st VoltMax',
                              'support_telegram': '@voltmax'})
        settings_obj.refresh_from_db()
        check('ilova bo\'limi saqlandi',
              settings_obj.app_name == '__st VoltMax', settings_obj.app_name)
        check('boshqa bo\'limdagi qiymat o\'zgarmadi',
              settings_obj.maintenance_mode == before_mode)

        # Noma'lum bo'lim hech narsani o'zgartirmaydi
        client.post(general, {'section': 'yoq-bunday', 'app_name': 'boshqa'})
        settings_obj.refresh_from_db()
        check('noma\'lum bo\'lim e\'tiborsiz qoldirildi',
              settings_obj.app_name == '__st VoltMax')

        # ── 3. Jurnal ───────────────────────────────────────────
        row = SettingsChange.objects.filter(field='app_name').first()
        check('o\'zgarish jurnalga tushdi', row is not None)
        check('jurnalda eski va yangi qiymat bor',
              row.new_value == '__st VoltMax' and row.old_value != row.new_value,
              f'{row.old_value} -> {row.new_value}')
        check('jurnalda kim o\'zgartirgani bor',
              row.changed_by_id == admin.id, row.changed_by)
        check('jurnal sahifada ko\'rinadi',
              '__st VoltMax' in client.get(general).content.decode('utf-8'))

        # O'zgarishsiz saqlash jurnalni to'ldirmaydi
        before = SettingsChange.objects.count()
        client.post(general, {'section': 'app', 'app_name': '__st VoltMax',
                              'support_telegram': '@voltmax'})
        check('o\'zgarishsiz saqlash jurnalga yozmadi',
              SettingsChange.objects.count() == before)

        # ── 4. Xavfli sozlamalar ────────────────────────────────
        body = client.get(general).content.decode('utf-8')
        check('texnik rejimda tasdiq so\'raladi', 'data-confirm' in body)
        security = client.get(reverse('dashboard:settings_security')).content.decode('utf-8')
        check('qat\'iy rejimda ham tasdiq bor', 'data-confirm' in security)

        # ── 5. Yangi sozlamalar ─────────────────────────────────
        client.post(reverse('dashboard:settings_payment'), {
            'section': 'topup', 'min_topup': '5 000', 'max_topup': '3 000 000',
            'min_balance_to_start': '2 000',
        })
        settings_obj.refresh_from_db()
        check('minimal balans saqlandi',
              settings_obj.min_balance_to_start == 2000, settings_obj.min_balance_to_start)

        # Chegaralar mantiqan tekshiriladi
        client.post(reverse('dashboard:settings_payment'), {
            'section': 'topup', 'min_topup': '100 000', 'max_topup': '1 000',
            'min_balance_to_start': '0',
        })
        settings_obj.refresh_from_db()
        check('teskari chegaralar rad etildi',
              settings_obj.min_topup == 5000, settings_obj.min_topup)

        client.post(reverse('dashboard:settings_session'), {
            'section': 'session', 'max_session_minutes': '240',
            'work_start': '08:00', 'work_end': '22:00',
        })
        settings_obj.refresh_from_db()
        check('sessiya cheklovi saqlandi',
              settings_obj.max_session_minutes == 240, settings_obj.max_session_minutes)
        check('ish vaqti tugmachasi o\'chirildi', settings_obj.work_all_day is False)

        # ── 6. To'lov tizimlari ─────────────────────────────────
        providers_url = reverse('dashboard:settings_providers')
        client.post(reverse('dashboard:provider_new'), {
            'name': '__st Uzum', 'code': '__st_uzum', 'merchant_id': 'M-123',
            'secret_key': 'juda-maxfiy-kalit', 'is_active': 'on', 'order': '0',
        })
        provider = PaymentProvider.objects.filter(code='__st_uzum').first()
        check('to\'lov tizimi qo\'shildi', provider is not None)
        check('sozlangan deb belgilandi', provider.is_configured)

        page = client.get(providers_url).content.decode('utf-8')
        check('ro\'yxatda ko\'rinadi', '__st Uzum' in page)
        check('maxfiy kalit oshkor qilinmadi', 'juda-maxfiy-kalit' not in page)
        check('kalitning oxiri ko\'rsatildi', 'alit'[-4:] in page or '••••' in page)

        # Kalitsiz saqlash eskisini o'chirmasligi kerak
        client.post(reverse('dashboard:provider_edit', args=[provider.pk]), {
            'name': '__st Uzum Bank', 'code': '__st_uzum', 'merchant_id': 'M-456',
            'secret_key': '', 'is_active': 'on', 'order': '0',
        })
        provider.refresh_from_db()
        check('nomi yangilandi', provider.name == '__st Uzum Bank', provider.name)
        check('bo\'sh kalit eskisini o\'chirmadi',
              provider.secret_key == 'juda-maxfiy-kalit', provider.secret_key[:6])

        client.post(reverse('dashboard:provider_toggle', args=[provider.pk]))
        provider.refresh_from_db()
        check('tizim o\'chirildi', provider.is_active is False)
        check('o\'chirish jurnalga tushdi',
              SettingsChange.objects.filter(section='providers').exists())

        client.post(reverse('dashboard:provider_delete', args=[provider.pk]))
        check('tizim ro\'yxatdan olib tashlandi',
              not PaymentProvider.objects.filter(code='__st_uzum').exists())

        # ── 6b. Bir qatordagi amallar bir-biridan farq qilsin ───
        # Ilgari "to'xtatish" va "o'chirish" tugmalari bir xil atalgan edi:
        # biri tizimni vaqtincha o'chiradi, ikkinchisi ro'yxatdan butunlay
        # olib tashlaydi — bosishdan oldin farqni bilish kerak
        import re as _re

        client.post(reverse('dashboard:provider_new'), {
            'name': '__st Tekshiruv', 'code': '__st_check', 'is_active': 'on',
            'order': '0',
        })
        page = client.get(providers_url).content.decode('utf-8')
        row = page[page.index('<tbody>'):page.index('</tbody>')].split('</tr>')[0]
        labels = _re.findall(r'<button[^>]*>\s*([^<]+?)\s*</button>', row)
        check('qatordagi tugmalar nomi takrorlanmadi',
              len(labels) == len(set(labels)), labels)
        PaymentProvider.objects.filter(code='__st_check').delete()

        # Push holati ko'rsatkichda aytiladi, alohida ogohlantirish blokida emas:
        # sozlamalar sahifasida u tizim xatosidek ko'rinardi
        notif = client.get(reverse('dashboard:settings_notification')).content.decode('utf-8')
        check('push holati ogohlantirish bloki sifatida chiqmadi',
              'Push manzillari' not in notif)
        check("push ko'rsatkichi bor", "Ro'yxatdagi qurilmalar" in notif)

        # ── 7. Har tab faqat O'Z kartochkasini ko'rsatadi ───────
        # Tab bo'laklari alohida fayllarga ajratilganda bir kartochka
        # ikkita faylga tushib qolgan edi va sahifada ikki marta chiqardi
        holiday_page = client.get(reverse('dashboard:settings_holiday')).content.decode('utf-8')
        contract_page = client.get(reverse('dashboard:settings_contract')).content.decode('utf-8')
        check('bayramlar izohi bir marta chiqdi',
              holiday_page.count('Bayramlar qayerdan olinadi') == 1,
              holiday_page.count('Bayramlar qayerdan olinadi'))
        check('shartnoma izohi bir marta chiqdi',
              contract_page.count('Shablon qanday ishlaydi') == 1,
              contract_page.count('Shablon qanday ishlaydi'))
        check('begona tabning izohi chiqmadi',
              'Shablon qanday ishlaydi' not in holiday_page
              and 'Bayramlar qayerdan olinadi' not in contract_page)

        # ── 8. Qidiruv ──────────────────────────────────────────
        found = client.get(reverse('dashboard:settings_search'),
                           {'q': 'parkovka'}).content.decode('utf-8')
        check('qidiruv sozlamani topdi', 'Parkovka' in found or 'parkovka' in found)
        # Tab nomida apostrof bor — HTML'da u `&#x27;` bo'lib chiqadi,
        # shuning uchun bo'lim nomi bo'yicha tekshiramiz
        check('qidiruv qaysi tabda ekanini aytdi', 'Tariflar' in found, 'Tariflar' in found)

        empty = client.get(reverse('dashboard:settings_search'),
                           {'q': 'yoqbundaysozlama'}).content.decode('utf-8')
        check('topilmagan holat matni bor', 'topilmadi' in empty)

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
