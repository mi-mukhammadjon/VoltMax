"""Chegaradan oshib ketgan sessiyalarni majburiy to'xtatadi.

Ishlatish:

    python manage.py stop_overdue                    # bir marta
    python manage.py stop_overdue --loop --interval 300

Nima uchun kerak: haydovchi zaryadni to'xtatishni unutsa, sessiya kun bo'yi
ketaveradi. Parkovka haqi esa har daqiqada o'sadi — natijada foydalanuvchiga
katta hisob chiqadi, u nizoga aylanadi va odatda qaytarib beriladi. Chegara
"Sozlamalar > Sessiya" da belgilanadi; 0 bo'lsa cheklov yo'q va buyruq hech
narsa qilmaydi.

Buyruq bir vaqtda FAQAT BITTA jarayonda ishlashi kerak (`bill_parking`
kabi) — aks holda bir sessiyaga bir necha to'xtatish buyrug'i ketardi.
"""

import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from management.models import NotificationTemplate, SiteSettings, UserNotification
from sessions_app.services import force_stop_session
from stations.rules import overdue_sessions


class Command(BaseCommand):
    help = "Vaqt chegarasidan oshgan sessiyalarni to'xtatadi"

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true',
                            help="To'xtamasdan davriy ishlaydi")
        parser.add_argument('--interval', type=int, default=300,
                            help='--loop rejimida chaqiruvlar orasidagi vaqt (soniya)')
        parser.add_argument('--quiet', action='store_true',
                            help='Hech narsa topilmagan chaqiruvlar haqida yozmaydi')

    def handle(self, *args, **options):
        interval = max(30, options['interval'])

        if not options['loop']:
            self._run_once(options['quiet'])
            return

        limit = SiteSettings.load().max_session_minutes
        self.stdout.write(self.style.SUCCESS(
            f"Sessiya nazorati ishga tushdi — chegara {limit or 'yo‘q'} daq, "
            f"har {interval} soniyada tekshiriladi. To'xtatish: Ctrl+C"
        ))
        try:
            while True:
                self._run_once(options['quiet'])
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("\nTo'xtatildi.")

    def _run_once(self, quiet=False):
        stopped = 0
        for session in overdue_sessions():
            if self._stop(session):
                stopped += 1

        if stopped:
            self.stdout.write(self.style.SUCCESS(f'{stopped} ta sessiya to‘xtatildi'))
        elif not quiet:
            self.stdout.write('Chegaradan oshgan sessiya yo‘q')

    def _stop(self, session):
        """Bitta sessiyani to'xtatadi va foydalanuvchini xabardor qiladi.

        To'xtatish `force_stop_session` orqali: u chargerga buyruq yuboradi,
        hisobni yopadi va ulagich/stansiya holatini yangilaydi. Bu yerda
        qaytadan yozilsa ikki xil yopish yo'li paydo bo'lardi.
        """
        result = force_stop_session(session, actor='avtomatik')
        if not result.stopped:
            return False
        if result.warning:
            self.stderr.write(f'{session.pk}: {result.warning}')

        session.refresh_from_db()
        if not session.stop_reason:
            session.stop_reason = 'Vaqt chegarasi (avtomatik)'
            session.save(update_fields=['stop_reason'])

        self._notify(session)
        return True

    def _notify(self, session):
        """Foydalanuvchiga sabab bilan xabar yozadi.

        Matn panelda tahrirlanadi (Sozlamalar > Bildirishnoma). Shablon
        o'chirilgan bo'lsa xabar yozilmaydi.
        """
        if session.user_id is None:
            return

        template = NotificationTemplate.for_event(
            NotificationTemplate.Event.SESSION_TIMEOUT)
        if template is None:
            return

        limit = SiteSettings.load().max_session_minutes
        title, body = template.render({
            'stansiya': session.station.name if session.station else '',
            'daqiqa': str(limit),
        })
        UserNotification.objects.create(
            user_id=session.user_id, kind=UserNotification.Kind.SYSTEM,
            title=title[:150], body=body[:400],
            station=session.station,
        )
