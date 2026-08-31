"""Yozilgan bildirishnomalarni telefonlarga yetkazadi.

Ishlatish:

    python manage.py send_push                    # bir marta
    python manage.py send_push --loop --interval 30

Nima uchun alohida jarayon: tashqi push xizmati sekin javob berishi yoki
umuman javob bermasligi mumkin. Xabar yozilishi shunga bog'liq bo'lsa,
zaryadni to'xtatish yoki nosozlikni qayd etish ham sekinlashardi. Shu sababli
xabar avval bazaga yoziladi, yuborish esa shu buyruq orqali.
"""

import time

from django.core.management.base import BaseCommand

from management.push import deliver_pending


class Command(BaseCommand):
    help = 'Yuborilmagan bildirishnomalarni telefonlarga yuboradi'

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true',
                            help="To'xtamasdan davriy ishlaydi")
        parser.add_argument('--interval', type=int, default=30,
                            help='--loop rejimida chaqiruvlar orasidagi vaqt (soniya)')
        parser.add_argument('--quiet', action='store_true',
                            help='Yuborilmagan chaqiruvlar haqida yozmaydi')

    def handle(self, *args, **options):
        interval = max(5, options['interval'])

        if not options['loop']:
            self._run_once(options['quiet'])
            return

        self.stdout.write(self.style.SUCCESS(
            f"Push yuborish ishga tushdi — har {interval} soniyada. To'xtatish: Ctrl+C"))
        try:
            while True:
                self._run_once(options['quiet'])
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("\nTo'xtatildi.")

    def _run_once(self, quiet=False):
        result = deliver_pending()
        if result['sent'] or result['failed']:
            self.stdout.write(self.style.SUCCESS(
                f"{result['sent']} ta yuborildi, {result['failed']} ta xato, "
                f"{result['no_device']} ta qurilmasiz, {result['skipped']} ta o'tkazib yuborildi"))
        elif not quiet:
            self.stdout.write('Yuboriladigan xabar yo‘q')
