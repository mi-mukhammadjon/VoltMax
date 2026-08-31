# -*- coding: utf-8 -*-
"""Tizim holatini TERMINALDA ko'rsatadi.

Nima uchun panel yetmaydi: serverga endigina joylashtirilganda panelga
kirishdan oldin ham "hammasi ulandimi" degan savol tug'iladi. Bu buyruq
deploy skriptidan ham chaqirilishi mumkin — muammo bo'lsa nolga teng
bo'lmagan kod qaytaradi va CI/deploy shu yerda to'xtaydi.

    python manage.py health
    python manage.py health --strict   # ogohlantirish ham xato hisoblanadi
"""
from django.core.management.base import BaseCommand

MARK = {'ok': '[+]', 'warn': '[!]', 'down': '[x]'}


class Command(BaseCommand):
    help = "Tizim holatini tekshiradi (vazifalar, push, to'lov, chargerlar)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--strict', action='store_true',
            help='Ogohlantirish ham xato deb hisoblansin')

    def handle(self, *args, **options):
        from management.health import collect

        report = collect()

        for check in report['checks']:
            line = f"{MARK.get(check['state'], '   ')} {check['title']:24s} {check['value']}"
            if check['hint']:
                line += f"  — {check['hint']}"
            style = (self.style.SUCCESS if check['state'] == 'ok'
                     else self.style.WARNING if check['state'] == 'warn'
                     else self.style.ERROR)
            self.stdout.write(style(line))

        self.stdout.write('')
        if report['overall'] == 'ok':
            self.stdout.write(self.style.SUCCESS('Hammasi ishlayapti'))
            return

        bad = len(report['down'])
        warn = len(report['warn'])
        summary = f"{bad} ta muammo, {warn} ta ogohlantirish"
        self.stdout.write(self.style.ERROR(summary) if bad
                          else self.style.WARNING(summary))

        # Deploy skripti to'xtashi uchun — chiqish kodi nolga teng emas
        if bad or (options['strict'] and warn):
            raise SystemExit(1)
