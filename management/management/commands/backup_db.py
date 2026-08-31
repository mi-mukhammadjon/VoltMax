"""Bazaning zaxira nusxasini oladi.

Nima uchun kerak: bazada pul harakati bor — hamyon qoldiqlari,
to'lovlar, hisob-kitoblar. Railway'ning o'z zaxirasi bor, lekin u
platformaga bog'liq: hisob yopilsa yoki xizmat ko'chirilsa, nusxa ham
yo'qoladi. Bu buyruq bazadan MUSTAQIL nusxa beradi.

Ishlatish:

    python manage.py backup_db                 # backups/ papkasiga
    python manage.py backup_db --out /tmp      # boshqa joyga
    python manage.py backup_db --keep 14       # 14 kunlik nusxalar qoladi
    python manage.py backup_db --local         # R2 ga yuklamasdan

Fayl formati baza turiga qarab tanlanadi: PostgreSQL uchun `pg_dump`
(agar mavjud bo'lsa), SQLite uchun faylning o'zi ko'chiriladi.

Kundalik nusxa endi `run_workers` ichida ham olinadi — bu buyruq qo'lda
chaqirish va boshqa papkaga saqlash uchun qoladi. Mantiqning o'zi
`management/backup.py` da: ikkala yo'l bir xil kodni ishlatsin.

MUHIM: nusxa faqat OLINSA yetarli emas — uni tiklab ko'rish kerak.
Tiklash sinab ko'rilmagan nusxa nusxa emas.
"""

from django.core.management.base import BaseCommand

from management.backup import BackupError, run


class Command(BaseCommand):
    help = "Bazaning zaxira nusxasini oladi"

    def add_arguments(self, parser):
        parser.add_argument('--out', default='backups',
                            help='Nusxa saqlanadigan papka')
        parser.add_argument('--keep', type=int, default=7,
                            help='Necha kunlik nusxalar saqlansin')
        parser.add_argument('--local', action='store_true',
                            help='Faqat lokal papkaga, R2 ga yuklamasdan')

    def handle(self, *args, **options):
        try:
            result = run(out=options['out'], keep=options['keep'],
                         to_remote=not options['local'])
        except BackupError as error:
            self.stderr.write(self.style.ERROR(str(error)))
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS(
            f"{result['path']} — {result['size_mb']} MB"))

        if result['remote']:
            self.stdout.write(f"R2 ga yuklandi: {result['remote']}")
        elif not options['local']:
            self.stdout.write(self.style.WARNING(
                'R2 sozlanmagan — nusxa faqat shu serverning diskida. '
                "Railway'da disk har deploy'da tozalanadi."))

        removed = result['pruned_local'] + result['pruned_remote']
        if removed:
            self.stdout.write(f"{removed} ta eski nusxa o'chirildi")
