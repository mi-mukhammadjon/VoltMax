"""Qurilma holatini davriy tekshirib turadigan buyruq.

Nima uchun kerak: chargerdan aloqa uzilishi HODISA emas — hech kim hech narsa
yubormaydi, shunchaki Heartbeat kelmay qoladi. Ya'ni "aloqa yo'q" holatini
faqat vaqtni tekshirib bilish mumkin. Panelda operator "Sinxronlash" tugmasini
bosgandagina bilinsa, tunda uzilgan charger ertalabgacha "onlayn" ko'rinardi.

Ishlatish:

    python manage.py sync_devices                       # bir marta
    python manage.py sync_devices --loop --interval 120 # doimiy jarayon

Xabar YUBORMAYDI — faqat holat va nosozlik yozuvlarini to'g'rilaydi.
Foydalanuvchiga bildirishnoma yuborish operatorning ataylab qilgan amali
bo'lib qoladi (panel > Profilaktika), chunki uni qaytarib bo'lmaydi.
"""

import time

from django.core.management.base import BaseCommand

from stations.maintenance import sync_issues_from_devices
from stations.models import ChargerLog
from stations.services import sync_all


class Command(BaseCommand):
    help = "Stansiya/ulagich holatini va nosozlik yozuvlarini qurilmalarga moslaydi"

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true',
                            help="To'xtamasdan davriy ishlaydi")
        parser.add_argument('--interval', type=int, default=120,
                            help='--loop rejimida tekshiruvlar orasidagi vaqt, soniyada')
        parser.add_argument('--quiet', action='store_true',
                            help="O'zgarish bo'lmagan chaqiruvlar haqida yozmaydi")

    def handle(self, *args, **options):
        if not options['loop']:
            self._once(options['quiet'])
            return

        interval = max(30, options['interval'])
        self.stdout.write(f'sync_devices: har {interval} soniyada tekshiriladi')
        while True:
            try:
                self._once(options['quiet'])
            except Exception as exc:  # noqa: BLE001 — jarayon to'xtab qolmasin
                self.stderr.write(self.style.ERROR(f'sync_devices xatosi: {exc}'))
            time.sleep(interval)

    def _once(self, quiet):
        db = sync_all()
        issues = sync_issues_from_devices()
        # Qurilma jurnali cheksiz o'smasin — eski yozuvlar tozalanadi
        pruned = ChargerLog.prune()
        if pruned and not quiet:
            self.stdout.write(f"jurnaldan {pruned} ta eski yozuv o'chirildi")

        changed = db['connectors'] or db['stations'] or issues['opened'] or issues['resolved']
        if not changed:
            if not quiet:
                self.stdout.write('mos — o\'zgarish yo\'q')
            return

        self.stdout.write(self.style.SUCCESS(
            f"to'g'rilandi: {db['connectors']} ulagich, {db['stations']} stansiya; "
            f"nosozlik: +{issues['opened']} / -{issues['resolved']}"
        ))
