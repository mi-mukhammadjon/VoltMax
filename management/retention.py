# -*- coding: utf-8 -*-
"""Eskirgan yozuvlarni tozalash.

To'rtta jadval cheksiz o'sadi va hech kim ularni o'chirmaydi:

  * `SessionMeterReading` — har sessiyada o'nlab telemetriya yozuvi;
  * `UserNotification` — o'qilgan xabarlar;
  * `ActivityLog` — amallar jurnali;
  * `SettingsChange` — sozlama o'zgarishlari.

Bir yildan keyin telemetriya millionlab qatorga yetadi: sessiya sahifasi
sekinlashadi, zaxira nusxa esa kattalashadi. Hozir tozalash arzon, keyin
qimmat bo'ladi.

Muddatlar har xil, chunki ularning qiymati ham har xil:

  * telemetriya sessiya grafigi uchun kerak — 180 kun;
  * xabarlar ilovada ko'rinadi — 180 kun, lekin O'QILGANLARI 30 kunda;
  * jurnallar tekshiruv uchun kerak — 365 kun (moliyaviy nizolar odatda
    shu muddat ichida ko'tariladi).

Faqat vaqt bo'yicha tozalash yetarli emas: hodisa ko'p bo'lgan davrda
jadval bir necha kunda ham to'lib ketishi mumkin. Shuning uchun eng
ko'p yozuv soni ham cheklanadi.
"""

from datetime import timedelta

from django.utils import timezone

# (nom, model yo'li, sana maydoni, kun, eng ko'p yozuv)
POLICIES = [
    ('telemetriya', 'sessions_app.SessionMeterReading', 'recorded_at', 180, 500_000),
    ('xabarlar', 'management.UserNotification', 'created_at', 180, 200_000),
    ('amallar', 'management.ActivityLog', 'created_at', 365, 200_000),
    ('sozlamalar', 'management.SettingsChange', 'changed_at', 365, 50_000),
    # Charger javob bermay qolgan masofadan boshlash so'rovlari.
    # `take()` ham eskisini tozalaydi, lekin faqat o'sha foydalanuvchi
    # qayta urinsa — umuman qaytmaganlari shu yerda yig'ishtiriladi.
    ('boshlash so'rovlari', 'sessions_app.RemoteStartIntent', 'created_at', 1, 10_000),
    # Kirish urinishlari: 90 kun tergov uchun yetarli, undan keyin bu
    # faqat shaxsiy ma'lumot (IP, brauzer) saqlab turish bo'lardi
    ('kirish urinishlari', 'management.LoginAttempt', 'created_at', 90, 100_000),
    # Foydalanuvchi nosozlik xabarlari: nosozlik yozuvi o'zi qoladi,
    # bu esa faqat kim va qachon xabar berganini bildiradi. Bir yildan
    # keyin u tergov uchun kerak emas, saqlab turish esa shaxsiy
    # ma'lumotni ushlab turish bo'lardi
    ('nosozlik xabarlari', 'stations.StationReport', 'created_at', 365, 100_000),
]

# O'qilgan xabar tezroq eskiradi: foydalanuvchi uni ko'rgan
READ_NOTIFICATION_DAYS = 30


def _model(path):
    from django.apps import apps

    app_label, name = path.split('.')
    return apps.get_model(app_label, name)


def prune_all(dry_run=False):
    """Barcha jadvallarni tozalaydi va {nom: o'chirilgan_soni} qaytaradi."""
    result = {}

    for name, path, field, days, limit in POLICIES:
        model = _model(path)
        cutoff = timezone.now() - timedelta(days=days)
        removed = 0

        old = model.objects.filter(**{f'{field}__lt': cutoff})
        removed += old.count() if dry_run else old.delete()[0]

        # Soni chegarasi: eng yangi `limit` ta yozuv qoladi
        total = model.objects.count() - (removed if dry_run else 0)
        if total > limit:
            keep_ids = list(model.objects.order_by(f'-{field}')
                            .values_list('id', flat=True)[:limit])
            extra = model.objects.exclude(id__in=keep_ids)
            removed += extra.count() if dry_run else extra.delete()[0]

        result[name] = removed

    # O'qilgan xabarlar alohida, qisqaroq muddat bilan
    from management.models import UserNotification

    read_cutoff = timezone.now() - timedelta(days=READ_NOTIFICATION_DAYS)
    read_old = UserNotification.objects.filter(
        read_at__isnull=False, read_at__lt=read_cutoff)
    result['xabarlar'] += read_old.count() if dry_run else read_old.delete()[0]

    return result
