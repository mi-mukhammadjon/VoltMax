# -*- coding: utf-8 -*-
"""Bayram kunlarini Google Calendar'dan olish.

Google mamlakatlar bo'yicha ochiq bayram kalendarlarini ICS formatida
beradi — kalit ham, ro'yxatdan o'tish ham kerak emas. Fayl matnli va
tuzilishi oddiy, shuning uchun tashqi kutubxonasiz o'qiymiz: `icalendar`
paketini qo'shish bitta VEVENT turini o'qish uchun ortiqcha bog'liqlik
bo'lardi.

Brauzerdan to'g'ridan-to'g'ri olib bo'lmaydi (CORS), shuning uchun
ma'lumot serverda olinadi va bazada saqlanadi — panel esa uni o'z
manzilidan JSON ko'rinishida oladi.
"""

from datetime import date
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.utils import timezone

TIMEOUT = 15
USER_AGENT = 'VoltMax panel/1.0'


class HolidaySyncError(Exception):
    """Kalendarni olishda yuzaga kelgan, foydalanuvchiga ko'rsatiladigan xato."""


def fetch_ics(url: str) -> str:
    """ICS faylini yuklab, matn sifatida qaytaradi."""
    if not url:
        raise HolidaySyncError("Kalendar manzili ko'rsatilmagan")
    try:
        request = Request(url, headers={'User-Agent': USER_AGENT})
        with urlopen(request, timeout=TIMEOUT) as response:
            return response.read().decode('utf-8', errors='replace')
    except (URLError, OSError, ValueError) as error:
        raise HolidaySyncError(f'Kalendarni olib bo\'lmadi: {error}') from error


def _unfold(text: str):
    """ICS satrlari 75 belgidan uzun bo'lsa bo'shliq bilan ko'chiriladi.

    Ko'chirilgan satr oldingisining davomi — birlashtirilmasa bayram nomi
    yarmida kesilib qolardi.
    """
    current = ''
    for raw in text.replace('\r\n', '\n').split('\n'):
        if raw[:1] in (' ', '\t'):
            current += raw[1:]
            continue
        if current:
            yield current
        current = raw
    if current:
        yield current


def _unescape(value: str) -> str:
    return (value.replace('\\,', ',').replace('\\;', ';')
                 .replace('\\n', ' ').replace('\\N', ' ').strip())


def parse_ics(text: str):
    """ICS matnidan `(sana, nom)` juftliklarini ajratib oladi.

    Faqat kun bo'yicha (`VALUE=DATE`) hodisalar olinadi — bayram butun
    kunni egallaydi. Vaqti bor hodisalar bayram emas (uchrashuv, eslatma).
    """
    events = []
    inside = False
    start = None
    name = ''

    for line in _unfold(text):
        if line.startswith('BEGIN:VEVENT'):
            inside, start, name = True, None, ''
            continue
        if not inside:
            continue

        if line.startswith('END:VEVENT'):
            if start and name:
                events.append((start, name))
            inside = False
            continue

        key, _, value = line.partition(':')
        if key.startswith('DTSTART') and 'VALUE=DATE' in key:
            digits = value.strip()
            if len(digits) == 8 and digits.isdigit():
                start = date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        elif key.startswith('SUMMARY'):
            name = _unescape(value)[:150]

    return events


def sync_holidays(url=None, text=None):
    """Bayramlarni yangilaydi va `(qo'shildi, yangilandi, jami)` qaytaradi.

    `text` berilsa tarmoqqa chiqmaydi — bu testlar va qo'lda yuklangan
    fayl uchun kerak.

    Qo'lda kiritilgan kunlarga tegilmaydi: Google ro'yxati O'zbekistondagi
    ko'chirilgan ish kunlarini bilmaydi, operator ularni o'zi qo'shadi.
    """
    from .models import Holiday, SiteSettings

    settings_obj = SiteSettings.load()
    if text is None:
        text = fetch_ics(url or settings_obj.holiday_ics_url)

    events = parse_ics(text)
    if not events:
        raise HolidaySyncError('Kalendarda bayram kunlari topilmadi')

    now = timezone.now()
    added = updated = 0
    for day, name in events:
        existing = Holiday.objects.filter(date=day).first()
        if existing is None:
            Holiday.objects.create(
                date=day, name=name, source=Holiday.Source.GOOGLE, synced_at=now)
            added += 1
            continue
        if existing.source == Holiday.Source.MANUAL:
            # Operator kiritgan yozuv ustunroq — u qonuniy hujjatga tayanadi
            continue
        if existing.name != name:
            existing.name = name
            updated += 1
        existing.synced_at = now
        existing.save(update_fields=['name', 'synced_at'])

    settings_obj.holidays_synced_at = now
    settings_obj.save(update_fields=['holidays_synced_at'])
    return added, updated, len(events)
