"""Barcha davriy vazifalarni BITTA jarayonda ishga tushiradi.

Ishlatish:

    python manage.py run_workers
    python manage.py run_workers --only push,parking

Nima uchun kerak: davriy vazifalar to'rtta alohida buyruq edi va ularning
har biri uchun alohida server jarayoni kerak bo'lardi. Railway'da bu to'rtta
alohida servis degani — sozlash unutilsa vazifa jimgina ishlamay qoladi va
buni hech kim payqamaydi (parkovka hisoblanmaydi, push ketmaydi).

Bitta jarayonda ishlatishning yana bir sababi bor: bu vazifalar bir vaqtda
FAQAT BITTA nusxada ishlashi kerak. Bittasi ikkinchisiga xalaqit bermaydi —
har biri o'z oralig'ida, o'z oqimida (thread) ishlaydi va xatosi qolganlarini
to'xtatmaydi.

MUHIM: bu jarayon bitta nusxada ishlashi kerak (Railway'da replica = 1).
Veb-server ichiga qo'shib bo'lmaydi: har bir web worker mustaqil hisoblab,
foydalanuvchidan ortiqcha pul yechilardi.
"""

import logging
import threading
import time

from django.core.management.base import BaseCommand

logger = logging.getLogger('workers')


def _parking():
    from sessions_app.parking import bill_parking

    result = bill_parking()
    if result['charged']:
        return (f"parkovka: {result['minutes']} daq, {result['charged']} so'm "
                f"({result['sessions']} sessiya)")
    return ''


def _devices():
    from stations.maintenance import sync_issues_from_devices
    from stations.models import ChargerLog
    from stations.services import sync_all

    db = sync_all()
    issues = sync_issues_from_devices()
    ChargerLog.prune()

    if db['connectors'] or db['stations'] or issues['opened'] or issues['resolved']:
        return (f"qurilmalar: {db['connectors']} ulagich, {db['stations']} stansiya, "
                f"nosozlik +{issues['opened']}/-{issues['resolved']}")
    return ''


def _overdue():
    from django.core.management import call_command
    from io import StringIO

    out = StringIO()
    call_command('stop_overdue', quiet=True, stdout=out, stderr=out)
    return out.getvalue().strip()


def _bookings():
    """Muddati o'tgan bronlarni yopadi.

    Mijoz kelmasa ulagich qurilmada band bo'lib qolardi va boshqa hech
    kim undan foydalana olmasdi.
    """
    from bookings.reservations import expire_stale

    result = expire_stale()
    if result['closed']:
        return (f"bronlar: {result['closed']} ta yopildi, "
                f"{result['released']} ta ulagich bo'shatildi")
    return ''


def _cleanup():
    """Eskirgan yozuvlarni tozalaydi.

    Kuniga bir marta yetarli — shuning uchun oralig'i uzun. Tozalashsiz
    telemetriya bir yilda millionlab qatorga yetadi.
    """
    from management.retention import prune_all

    result = prune_all()
    total = sum(result.values())
    if total:
        parts = ', '.join(f'{name}: {count}' for name, count in result.items() if count)
        return f"tozalandi — {parts}"
    return ''


def _push():
    from management.push import deliver_pending

    result = deliver_pending()
    if result['sent'] or result['failed']:
        return f"push: {result['sent']} yuborildi, {result['failed']} xato"
    return ''


# (nom, funksiya, oraliq soniyada)
JOBS = [
    ('parking', _parking, 300),
    ('devices', _devices, 120),
    ('overdue', _overdue, 300),
    ('push', _push, 30),
    ('bookings', _bookings, 300),
    ('cleanup', _cleanup, 24 * 3600),
]


class Command(BaseCommand):
    help = 'Davriy vazifalarni bitta jarayonda ishga tushiradi'

    def add_arguments(self, parser):
        parser.add_argument(
            '--only', default='',
            help='Faqat sanab o\'tilganlari: parking,devices,overdue,push')
        parser.add_argument(
            '--once', action='store_true',
            help='Har vazifani bir marta bajaradi va chiqadi (tekshirish uchun)')

    def handle(self, *args, **options):
        chosen = {name.strip() for name in options['only'].split(',') if name.strip()}
        jobs = [j for j in JOBS if not chosen or j[0] in chosen]

        if not jobs:
            self.stderr.write(f"Noma'lum vazifa: {options['only']}")
            return

        if options['once']:
            for name, func, _interval in jobs:
                self._run(name, func)
            return

        self.stdout.write(self.style.SUCCESS(
            'Vazifalar ishga tushdi: '
            + ', '.join(f'{name} ({interval}s)' for name, _f, interval in jobs)
            + ". To'xtatish: Ctrl+C"))

        threads = []
        stop = threading.Event()
        for name, func, interval in jobs:
            thread = threading.Thread(
                target=self._loop, args=(name, func, interval, stop),
                name=name, daemon=True)
            thread.start()
            threads.append(thread)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop.set()
            self.stdout.write("\nTo'xtatildi.")

    def _loop(self, name, func, interval, stop):
        """Bitta vazifaning tsikli.

        Xato butun jarayonni to'xtatmaydi: bir vazifa yiqilsa qolganlari
        ishlayveradi, xato esa logga tushadi.
        """
        while not stop.is_set():
            self._run(name, func)
            stop.wait(interval)

    def _run(self, name, func):
        # Har tsikl sozlamalarni qaytadan o'qiydi: ishchi uzluksiz
        # aylanadi va so'rovdagidek "yangi boshlanish" yo'q
        from management.current import clear_cached

        clear_cached()
        try:
            message = func()
        except Exception as error:      # noqa: BLE001 — tsikl to'xtamasligi kerak
            logger.exception('%s vazifasi xato berdi: %s', name, error)
            self.stderr.write(f'{name}: {error}')
            return

        if message:
            self.stdout.write(message)
