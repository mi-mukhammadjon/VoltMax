"""Pullik parkovka uchun davriy hisob-kitob buyrug'i.

Ishlatish:

    # Bir marta ishga tushirish (cron / Task Scheduler uchun)
    python manage.py bill_parking

    # Doimiy ishlaydigan jarayon (Procfile'ga alohida worker sifatida)
    python manage.py bill_parking --loop --interval 300

MUHIM: bu buyruq bir vaqtning o'zida FAQAT BITTA jarayonda ishlashi kerak.
Veb-serverning ichiga qo'shib qo'yilsa, har bir worker alohida hisoblab,
foydalanuvchidan ortiqcha pul yechilishi mumkin edi — shuning uchun u ataylab
alohida buyruq qilib ajratilgan. (Qulflar himoya beradi, lekin ortiqcha
yuklamaning keragi yo'q.)
"""

import time

from django.core.management.base import BaseCommand

from dashboard.templatetags.money import format_som
from sessions_app.parking import bill_parking


class Command(BaseCommand):
    help = "Parkovka rejimidagi sessiyalardan daqiqalik to'lovni yechadi"

    def add_arguments(self, parser):
        parser.add_argument(
            '--loop', action='store_true',
            help="To'xtamasdan davriy ishlaydi (alohida worker sifatida)",
        )
        parser.add_argument(
            '--interval', type=int, default=300,
            help='--loop rejimida chaqiruvlar orasidagi vaqt, soniyada (standarti 300)',
        )
        parser.add_argument(
            '--quiet', action='store_true',
            help="Hech narsa yechilmagan chaqiruvlar haqida yozmaydi",
        )

    def handle(self, *args, **options):
        interval = max(30, options['interval'])

        if not options['loop']:
            self._run_once(options['quiet'])
            return

        self.stdout.write(self.style.SUCCESS(
            f"Parkovka hisobi ishga tushdi — har {interval} soniyada tekshiriladi. "
            f"To'xtatish: Ctrl+C"
        ))
        try:
            while True:
                self._run_once(options['quiet'])
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("\nTo'xtatildi.")

    def _run_once(self, quiet):
        result = bill_parking()

        if not result['sessions']:
            if not quiet:
                self.stdout.write('Parkovka rejimida sessiya yo\'q')
            return

        message = (
            f"{result['sessions']} ta sessiya · {result['minutes']} daqiqa · "
            f"{format_som(result['charged'])} so'm yechildi"
        )
        self.stdout.write(self.style.SUCCESS(message))

        if result['unpaid']:
            self.stdout.write(self.style.WARNING(
                f"{format_som(result['unpaid'])} so'm yechilmadi — hamyonda mablag' yetmadi. "
                f"Bu summa sessiya tugaganda umumiy hisobdan olinadi."
            ))
