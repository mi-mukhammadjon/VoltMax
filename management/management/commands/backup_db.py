"""Bazaning zaxira nusxasini oladi.

Nima uchun kerak: bazada pul harakati bor — hamyon qoldiqlari,
to'lovlar, hisob-kitoblar. Railway'ning o'z zaxirasi bor, lekin u
platformaga bog'liq: hisob yopilsa yoki xizmat ko'chirilsa, nusxa ham
yo'qoladi. Bu buyruq bazadan MUSTAQIL nusxa beradi.

Ishlatish:

    python manage.py backup_db                 # backups/ papkasiga
    python manage.py backup_db --out /tmp      # boshqa joyga
    python manage.py backup_db --keep 14       # 14 kunlik nusxalar qoladi

Fayl formati baza turiga qarab tanlanadi: PostgreSQL uchun `pg_dump`
(agar mavjud bo'lsa), SQLite uchun faylning o'zi ko'chiriladi.

MUHIM: nusxa faqat OLINSA yetarli emas — uni tiklab ko'rish kerak.
Tiklash sinab ko'rilmagan nusxa nusxa emas.
"""

import gzip
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Bazaning zaxira nusxasini oladi"

    def add_arguments(self, parser):
        parser.add_argument('--out', default='backups',
                            help='Nusxa saqlanadigan papka')
        parser.add_argument('--keep', type=int, default=7,
                            help='Necha kunlik nusxalar saqlansin')

    def handle(self, *args, **options):
        folder = Path(options['out'])
        folder.mkdir(parents=True, exist_ok=True)

        config = settings.DATABASES['default']
        stamp = timezone.localtime().strftime('%Y%m%d-%H%M')

        if 'postgresql' in config['ENGINE']:
            path = self._dump_postgres(config, folder, stamp)
        else:
            path = self._copy_sqlite(config, folder, stamp)

        if path is None:
            return

        size = path.stat().st_size / 1024 / 1024
        self.stdout.write(self.style.SUCCESS(f'{path} — {size:.1f} MB'))
        self._prune(folder, options['keep'])

    def _dump_postgres(self, config, folder, stamp):
        path = folder / f'voltmax-{stamp}.sql.gz'
        command = [
            'pg_dump',
            '--host', config.get('HOST') or 'localhost',
            '--port', str(config.get('PORT') or 5432),
            '--username', config.get('USER') or 'postgres',
            '--no-password', '--clean', '--if-exists',
            config.get('NAME') or 'postgres',
        ]
        env = {'PGPASSWORD': config.get('PASSWORD') or ''}

        try:
            with gzip.open(path, 'wb') as target:
                process = subprocess.run(command, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, env=env, check=True)
                target.write(process.stdout)
        except FileNotFoundError:
            self.stderr.write(
                "pg_dump topilmadi. Railway'da zaxira platformaning o'zida "
                "olinadi; lokal nusxa uchun PostgreSQL client o'rnating.")
            path.unlink(missing_ok=True)
            return None
        except subprocess.CalledProcessError as error:
            self.stderr.write(f'pg_dump xatosi: {error.stderr.decode()[:200]}')
            path.unlink(missing_ok=True)
            return None
        return path

    def _copy_sqlite(self, config, folder, stamp):
        source = Path(config['NAME'])
        if not source.exists():
            self.stderr.write(f'Baza fayli topilmadi: {source}')
            return None

        path = folder / f'voltmax-{stamp}.sqlite3.gz'
        with open(source, 'rb') as src, gzip.open(path, 'wb') as dst:
            shutil.copyfileobj(src, dst)
        return path

    def _prune(self, folder, keep_days):
        """Eski nusxalarni o'chiradi — disk to'lib qolmasin."""
        cutoff = timezone.now() - timedelta(days=keep_days)
        removed = 0
        for item in folder.glob('voltmax-*'):
            changed = timezone.datetime.fromtimestamp(
                item.stat().st_mtime, tz=timezone.get_current_timezone())
            if changed < cutoff:
                item.unlink()
                removed += 1
        if removed:
            self.stdout.write(f"{removed} ta eski nusxa o'chirildi")
