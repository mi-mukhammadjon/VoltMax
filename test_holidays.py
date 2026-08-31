# -*- coding: utf-8 -*-
"""Bayram kunlari: Google Calendar'dan olish va kalendarga uzatish.

Asosiy savollar:
  1. ICS fayli to'g'ri o'qiladimi — ko'chirilgan satr va qochirilgan
     belgilar bilan birga?
  2. Vaqti bor hodisalar (bayram emas) chetlab o'tiladimi?
  3. Qayta sinxronlash nusxa yaratmaydimi?
  4. Operator QO'LDA kiritgan kun Google yangilashida saqlanib qoladimi?
  5. Kalendar uchun JSON manzil ishlaydimi va faqat xodimga ochiqmi?
  6. Tarmoq xatosi sahifani buzmaydimi?

Tarmoqqa chiqilmaydi: ICS matni testda beriladi.
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import date  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.urls import reverse  # noqa: E402

from management.holidays import (  # noqa: E402
    HolidaySyncError, parse_ics, sync_holidays,
)
from management.models import Holiday, SiteSettings  # noqa: E402

failures = 0

# Google beradigan faylning qisqartirilgan nusxasi: uzun satr ko'chirilgan,
# vergul qochirilgan, oxirgi hodisa esa vaqtli (bayram emas)
SAMPLE_ICS = (
    'BEGIN:VCALENDAR\r\n'
    'BEGIN:VEVENT\r\n'
    'DTSTART;VALUE=DATE:20260101\r\n'
    'SUMMARY:Yangi yil\r\n'
    'END:VEVENT\r\n'
    'BEGIN:VEVENT\r\n'
    'DTSTART;VALUE=DATE:20260901\r\n'
    'SUMMARY:Mustaqillik kuni\\, O\'zbekiston Respublikasining davlat\r\n'
    '  bayrami\r\n'
    'END:VEVENT\r\n'
    'BEGIN:VEVENT\r\n'
    'DTSTART;VALUE=DATE:20261208\r\n'
    'SUMMARY:Konstitutsiya kuni\r\n'
    'END:VEVENT\r\n'
    'BEGIN:VEVENT\r\n'
    'DTSTART;TZID=Asia/Tashkent:20260315T100000\r\n'
    'SUMMARY:Uchrashuv\r\n'
    'END:VEVENT\r\n'
    'END:VCALENDAR\r\n'
)


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    Holiday.objects.filter(date__year=2026).delete()
    User.objects.filter(username__startswith='__hd').delete()


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved_url = settings_obj.holiday_ics_url
    saved_sync = settings_obj.holidays_synced_at
    admin = User.objects.create(username='__hd_admin__', is_staff=True, is_superuser=True)

    try:
        # ── 1. ICS o'qish ───────────────────────────────────────
        events = parse_ics(SAMPLE_ICS)
        days = dict(events)
        check('kun bo\'yicha hodisalar o\'qildi', len(events) == 3, len(events))
        check('vaqti bor hodisa chetlab o\'tildi',
              all(name != 'Uchrashuv' for _, name in events))
        check('ko\'chirilgan satr birlashtirildi',
              days.get(date(2026, 9, 1), '').endswith('davlat bayrami'),
              days.get(date(2026, 9, 1)))
        check('qochirilgan vergul tiklandi',
              days.get(date(2026, 9, 1), '').startswith('Mustaqillik kuni,'))

        # ── 2. Bazaga yozish ────────────────────────────────────
        added, updated, total = sync_holidays(text=SAMPLE_ICS)
        check('kunlar bazaga yozildi', (added, updated, total) == (3, 0, 3),
              (added, updated, total))
        check('manba Google deb belgilandi',
              Holiday.objects.filter(date=date(2026, 1, 1),
                                     source=Holiday.Source.GOOGLE).exists())

        # Qayta sinxronlash nusxa yaratmaydi
        added, updated, _ = sync_holidays(text=SAMPLE_ICS)
        check('takroriy sinxronlash nusxa yaratmadi',
              added == 0 and Holiday.objects.filter(date__year=2026).count() == 3,
              Holiday.objects.filter(date__year=2026).count())

        # Nom o'zgarsa yangilanadi
        renamed = SAMPLE_ICS.replace('SUMMARY:Yangi yil', 'SUMMARY:Yangi yil bayrami')
        _, updated, _ = sync_holidays(text=renamed)
        check('o\'zgargan nom yangilandi',
              updated == 1
              and Holiday.objects.get(date=date(2026, 1, 1)).name == 'Yangi yil bayrami')

        # ── 3. Qo'lda kiritilgan kun ustun turadi ───────────────
        Holiday.objects.filter(date=date(2026, 1, 1)).update(
            name='__hd ko\'chirilgan ish kuni', source=Holiday.Source.MANUAL)
        sync_holidays(text=SAMPLE_ICS)
        manual = Holiday.objects.get(date=date(2026, 1, 1))
        check('qo\'lda kiritilgan kunga tegilmadi',
              manual.name == '__hd ko\'chirilgan ish kuni'
              and manual.source == Holiday.Source.MANUAL, manual.name)

        # ── 4. Bo'sh kalendar xato beradi ───────────────────────
        try:
            sync_holidays(text='BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n')
            empty_raised = False
        except HolidaySyncError:
            empty_raised = True
        check('bo\'sh kalendar xato berdi', empty_raised)

        # Manzil bo'sh bo'lsa tarmoqqa chiqilmaydi
        settings_obj.holiday_ics_url = ''
        settings_obj.save(update_fields=['holiday_ics_url'])
        try:
            sync_holidays()
            blank_raised = False
        except HolidaySyncError:
            blank_raised = True
        check('manzilsiz sinxronlash tushunarli xato berdi', blank_raised)

        # ── 5. Kalendar uchun JSON ──────────────────────────────
        client = Client()
        url = reverse('dashboard:holidays_json')
        check('anonim foydalanuvchiga yopiq',
              client.get(url).status_code in (302, 403), client.get(url).status_code)

        client.force_login(admin)
        payload = client.get(url).json()
        check('JSON kunlari qaytdi',
              payload['days'].get('2026-12-08') == 'Konstitutsiya kuni',
              payload['days'].get('2026-12-08'))
        narrowed = client.get(url, {'from': '2026-09-01', 'to': '2026-09-30'}).json()
        check('oraliq bo\'yicha filtr ishladi',
              list(narrowed['days']) == ['2026-09-01'], list(narrowed['days']))

        # ── 6. Panel sahifasi va qo'lda qo'shish ────────────────
        # Kalendar nusxasi eskirmasligi uchun sahifa versiyani beradi
        home = client.get('/companies/').content.decode('utf-8')
        check('sahifa bayramlar versiyasini berdi',
              'data-holidays="' in home and 'data-holidays="0"' not in home,
              home[home.index('<body'):home.index('>', home.index('<body')) + 1])

        page = client.get(reverse('dashboard:settings_holiday'))
        body = page.content.decode('utf-8')
        check('bayramlar tabi ochildi', page.status_code == 200, page.status_code)
        check('kunlar ro\'yxatda ko\'rinadi', 'Konstitutsiya kuni' in body)

        client.post(reverse('dashboard:holiday_add'),
                    {'date': '2026-03-21', 'name': '__hd Navro\'z'})
        navruz = Holiday.objects.filter(date=date(2026, 3, 21)).first()
        check('qo\'lda kun qo\'shildi',
              navruz is not None and navruz.source == Holiday.Source.MANUAL)

        client.post(reverse('dashboard:holiday_add'), {'date': '', 'name': 'nomsiz'})
        check('sanasiz yozuv rad etildi',
              Holiday.objects.filter(name='nomsiz').count() == 0)

        client.post(reverse('dashboard:holiday_delete', args=[navruz.pk]))
        check('kun o\'chirildi',
              not Holiday.objects.filter(pk=navruz.pk).exists())

    finally:
        settings_obj.holiday_ics_url = saved_url
        settings_obj.holidays_synced_at = saved_sync
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
