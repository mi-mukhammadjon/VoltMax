"""Lokal diskdagi yuklangan fayllarni Cloudflare R2 ga ko'chiradi.

Ishlatish (R2 kredensiallari .env da bo'lishi shart):

    python manage.py migrate_media_to_r2 --dry-run   # nima ko'chishini ko'rish
    python manage.py migrate_media_to_r2             # haqiqiy ko'chirish

Buyruq bazadagi FAYL MAYDONLARINI bo'ylab o'tadi (stansiya rasmi, banner) —
shunday qilib `media/` ichidagi ortiqcha/eskirgan fayllar ko'chirilmaydi.
Fayl nomlari o'zgarmaydi, shuning uchun bazani yangilash ham shart emas.
"""

import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError

from management.models import Banner
from stations.models import Station

# (model, fayl maydoni nomi)
MEDIA_FIELDS = [
    (Station, 'photo'),
    (Banner, 'image'),
]


class Command(BaseCommand):
    help = "Lokal media fayllarni R2 ga ko'chiradi"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Hech narsa yozmaydi, faqat ro'yxatni ko'rsatadi")
        parser.add_argument('--overwrite', action='store_true',
                            help="R2 da mavjud fayl ustiga qayta yozadi")

    def handle(self, *args, **options):
        if not settings.USE_R2:
            raise CommandError(
                "R2 sozlanmagan. .env da R2_BUCKET, R2_ACCOUNT_ID, "
                "R2_ACCESS_KEY_ID va R2_SECRET_ACCESS_KEY ni to'ldiring."
            )

        remote = storages['default']
        dry = options['dry_run']
        moved = skipped = missing = 0

        for model, field_name in MEDIA_FIELDS:
            label = model._meta.verbose_name
            for obj in model.objects.exclude(**{field_name: ''}).exclude(**{f'{field_name}__isnull': True}):
                file_field = getattr(obj, field_name)
                name = file_field.name
                local_path = os.path.join(settings.MEDIA_ROOT, name)

                if not os.path.exists(local_path):
                    self.stdout.write(self.style.WARNING(f'  yo\'q: {name} ({label})'))
                    missing += 1
                    continue

                if remote.exists(name) and not options['overwrite']:
                    skipped += 1
                    continue

                if dry:
                    self.stdout.write(f'  ko\'chiriladi: {name} ({label})')
                    moved += 1
                    continue

                with open(local_path, 'rb') as handle:
                    # Nomni saqlab qolamiz — bazadagi yo'l o'zgarmasin
                    if remote.exists(name):
                        remote.delete(name)
                    remote.save(name, ContentFile(handle.read()))

                self.stdout.write(self.style.SUCCESS(f'  ko\'chirildi: {name}'))
                moved += 1

        summary = f"{moved} ta fayl {'ko\'chiriladi' if dry else 'ko\'chirildi'}"
        if skipped:
            summary += f", {skipped} tasi allaqachon R2 da bor"
        if missing:
            summary += f", {missing} tasi diskda topilmadi"
        self.stdout.write(self.style.SUCCESS('\n' + summary))

        if dry:
            self.stdout.write("Haqiqiy ko'chirish uchun --dry-run siz qayta ishga tushiring.")
