# -*- coding: utf-8 -*-
"""Zaxira nusxa olish — buyruq ham, davriy vazifa ham shu yerdan chaqiradi.

Ilgari `backup_db` buyrug'i bor edi-yu, uni hech kim chaqirmasdi: davriy
vazifalar ro'yxatida yo'q edi. Ya'ni nusxa faqat kimdir esga olsa
olinardi. Bazada esa pul harakati bor — hamyon qoldiqlari, to'lovlar,
korporativ hisob-kitoblar. Bir marta yo'qotilsa tiklab bo'lmaydi.

Ikki muhim narsa:

  1. Nusxa R2 ga YUKLANADI (sozlangan bo'lsa). Railway'da serverning
     diski har deploy'da tozalanadi — lokal papkadagi nusxa o'sha yerda
     qolib ketardi va aynan kerak bo'lgan paytda topilmasdi.
  2. Nusxa olingani `JobStatus` ga yoziladi, ya'ni Tizim holati
     sahifasida ko'rinadi. Olinmayotgan zaxira — olinmagan zaxira.

MUHIM: nusxa faqat olinsa yetarli emas — uni tiklab ko'rish kerak.
Tiklash sinab ko'rilmagan nusxa nusxa emas.
"""
import gzip
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

# R2 dagi papka: media fayllar bilan aralashib ketmasin
REMOTE_PREFIX = 'backups/'


class BackupError(Exception):
    pass


def _stamp():
    return timezone.localtime().strftime('%Y%m%d-%H%M')


def dump_postgres(config, folder):
    path = folder / f'voltmax-{_stamp()}.sql.gz'
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
    except FileNotFoundError as error:
        path.unlink(missing_ok=True)
        raise BackupError(
            "pg_dump topilmadi — PostgreSQL client o'rnatilmagan") from error
    except subprocess.CalledProcessError as error:
        path.unlink(missing_ok=True)
        raise BackupError(f'pg_dump xatosi: {error.stderr.decode()[:200]}') from error
    return path


def copy_sqlite(config, folder):
    source = Path(config['NAME'])
    if not source.exists():
        raise BackupError(f'Baza fayli topilmadi: {source}')

    path = folder / f'voltmax-{_stamp()}.sqlite3.gz'
    with open(source, 'rb') as src, gzip.open(path, 'wb') as dst:
        shutil.copyfileobj(src, dst)
    return path


def upload(path):
    """Nusxani R2 ga yuklaydi. Sozlanmagan bo'lsa `None` qaytaradi.

    Xato yutilmaydi: yuklanmagan nusxa Railway'da keyingi deploy'gacha
    yashaydi, xolos — buni operator bilishi kerak.
    """
    if not getattr(settings, 'USE_R2', False):
        return None

    from django.core.files import File
    from django.core.files.storage import default_storage

    with open(path, 'rb') as handle:
        return default_storage.save(REMOTE_PREFIX + path.name, File(handle))


def prune_local(folder, keep_days):
    """Eski lokal nusxalarni o'chiradi — disk to'lib qolmasin."""
    cutoff = timezone.now() - timedelta(days=keep_days)
    removed = 0
    for item in folder.glob('voltmax-*'):
        changed = timezone.datetime.fromtimestamp(
            item.stat().st_mtime, tz=timezone.get_current_timezone())
        if changed < cutoff:
            item.unlink()
            removed += 1
    return removed


def prune_remote(keep_days):
    """R2 dagi eski nusxalarni o'chiradi.

    Sana FAYL NOMIDAN olinadi (`voltmax-YYYYMMDD-HHMM`): saqlash
    xizmatidan har fayl uchun vaqt so'rash sekin va ba'zi xizmatlarda
    umuman qo'llab-quvvatlanmaydi.
    """
    if not getattr(settings, 'USE_R2', False):
        return 0

    from datetime import datetime

    from django.core.files.storage import default_storage

    try:
        _dirs, files = default_storage.listdir(REMOTE_PREFIX.rstrip('/'))
    except Exception:       # noqa: BLE001 — tozalash asosiy ishni to'xtatmasin
        return 0

    cutoff = (timezone.localtime() - timedelta(days=keep_days)).date()
    removed = 0
    for name in files:
        try:
            day = datetime.strptime(name.split('-')[1], '%Y%m%d').date()
        except (IndexError, ValueError):
            continue
        if day < cutoff:
            try:
                default_storage.delete(REMOTE_PREFIX + name)
                removed += 1
            except Exception:       # noqa: BLE001
                continue
    return removed


def run(out='backups', keep=7, to_remote=True):
    """Nusxa oladi va natijani lug'at bilan qaytaradi."""
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)

    config = settings.DATABASES['default']
    if 'postgresql' in config['ENGINE']:
        path = dump_postgres(config, folder)
    else:
        path = copy_sqlite(config, folder)

    remote = upload(path) if to_remote else None
    return {
        'path': path,
        'size_mb': round(path.stat().st_size / 1024 / 1024, 1),
        'remote': remote,
        'pruned_local': prune_local(folder, keep),
        'pruned_remote': prune_remote(keep) if to_remote else 0,
    }
