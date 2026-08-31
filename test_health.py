# -*- coding: utf-8 -*-
"""Tizim holati — «ishlayaptimi?» degan savolga javob to'g'rimi.

Davriy vazifalar faqat logga yozardi. Ya'ni ishchi servis serverda
umuman ishga tushmagan bo'lsa ham panel «hammasi joyida» ko'rinishida
turaverardi. Jimgina ishlamaslik eng yomon holat.

Bu sinovning o'zi ham muhim: holat sahifasi NOTO'G'RI «hammasi joyida»
desa, u umuman bo'lmaganidan ham yomon — operator unga ishonib qoladi.

Asosiy savollar:
  1. Hech qachon ishlamagan vazifa «ishlamayapti» deb ko'rsatiladimi?
  2. Kechikkan vazifa aniqlanadimi va kechikmagani tinch qoldiriladimi?
  3. Ketma-ket xato «ishlamayapti» degan xulosaga olib keladimi?
  4. Vazifa yiqilsa xato YOZILADIMI (ilgari faqat logga tushardi)?
  5. Holat yozuvining o'zi vazifani to'xtatib qo'ymaydimi?
  6. Bitta tekshiruv yiqilsa ham sahifa ochiladimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from management import health  # noqa: E402
from management.jobs import JobStatus  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    JobStatus.objects.all().delete()
    User.objects.filter(username__startswith='__hl').delete()


def job(name):
    """Tekshiruvlar ichidan bitta vazifani topadi."""
    for item in health.check_jobs():
        if item['key'] == f'job:{name}':
            return item
    return None


def age(name, seconds):
    """Vazifaning oxirgi ishlash vaqtini orqaga suradi."""
    JobStatus.objects.filter(name=name).update(
        last_run_at=timezone.now() - timedelta(seconds=seconds))


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    saved = list(JobStatus.objects.values(
        'name', 'last_run_at', 'last_ok_at', 'last_summary', 'last_error',
        'fail_streak', 'runs'))
    _cleanup()

    try:
        # ── 1. Hech qachon ishlamagan ───────────────────────────
        # Aynan shu holat serverda ishchi servis yoqilmaganda bo'ladi
        row = job('push')
        check('yozuvsiz vazifa "ishlamayapti" deb ko\'rsatildi',
              row and row['state'] == 'down', row and row['state'])
        check('sabab aytildi (run_workers)',
              row and 'run_workers' in row['hint'], row and row['hint'])

        report = health.collect()
        check('umumiy xulosa ham "down"', report['overall'] == 'down',
              report['overall'])

        # ── 2. Yangi ishlagan vazifa ────────────────────────────
        JobStatus.record('push', summary='push: 3 yuborildi')
        row = job('push')
        check('endigina ishlagan vazifa joyida', row['state'] == 'ok', row['state'])
        check('natijasi ko\'rsatildi', 'yuborildi' in row['hint'], row['hint'])

        # ── 3. Kechikish ────────────────────────────────────────
        # `push` har 30 soniyada ishlaydi, chegara — uch baravar
        age('push', 60)
        check('bir oz kechikish xato emas', job('push')['state'] == 'ok',
              job('push')['state'])
        age('push', 200)
        check('uzoq kechikish aniqlandi', job('push')['state'] == 'down',
              job('push')['state'])

        # Kunlik vazifa uchun o'sha 200 soniya mutlaqo normal — chegara
        # har vazifaning O'Z oralig'idan hisoblanadi
        JobStatus.record('cleanup')
        age('cleanup', 200)
        check('kunlik vazifa uchun bir xil kechikish normal',
              job('cleanup')['state'] == 'ok', job('cleanup')['state'])

        # ── 4. Xato yoziladi ────────────────────────────────────
        JobStatus.record('parking', error='ValueError: sinov')
        row = JobStatus.objects.get(name='parking')
        check('xato bazaga yozildi', row.last_error == 'ValueError: sinov',
              row.last_error)
        check('bitta xato "ogohlantirish"', job('parking')['state'] == 'warn',
              job('parking')['state'])

        JobStatus.record('parking', error='ValueError: sinov')
        JobStatus.record('parking', error='ValueError: sinov')
        check('ketma-ket uchta xato "ishlamayapti"',
              job('parking')['state'] == 'down', job('parking')['state'])

        JobStatus.record('parking', summary='parkovka: 5 daq')
        row = JobStatus.objects.get(name='parking')
        check('muvaffaqiyatdan keyin hisob tozalandi', row.fail_streak == 0,
              row.fail_streak)
        check('xato matni ham o\'chdi', row.last_error == '', row.last_error)
        check('sanoq yuritildi', row.runs == 4, row.runs)

        # ── 5. Kuzatuv asosiy ishni to'xtatmaydi ────────────────
        # Yozuv juda uzun matn bilan chaqiriladi: model maydoni 255 belgi,
        # kesilmasa xato bo'lardi va VAZIFA to'xtardi
        result = JobStatus.record('devices', summary='x' * 900)
        check('juda uzun matn xato bermadi', result is not None)
        check('matn kesildi',
              len(JobStatus.objects.get(name='devices').last_summary) == 255,
              len(JobStatus.objects.get(name='devices').last_summary))

        # ── 6. Bitta tekshiruv yiqilsa ham sahifa ochiladi ──────
        original = health.check_payments

        def broken():
            raise RuntimeError('sinov uchun')

        health.check_payments = broken
        try:
            report = health.collect()
            check('yiqilgan tekshiruv sahifani buzmadi',
                  any(c['hint'].startswith('RuntimeError') for c in report['checks']),
                  [c['title'] for c in report['checks']][:3])
        finally:
            health.check_payments = original

        # ── 7. Panel sahifalari ─────────────────────────────────
        staff = User.objects.create_user(username='__hl_manager__',
                                         password='sinov-parol', is_staff=True)
        panel = Client()
        panel.force_login(staff)

        page = panel.get('/system/')
        check('holat sahifasi menejerga ochiq', page.status_code == 200,
              page.status_code)
        body = page.content.decode('utf-8')
        check('vazifalar sahifada ko\'rindi', 'parking' in body)

        # Muammo bo'lganda bosh sahifada ogohlantirish chiqadi
        JobStatus.objects.filter(name='push').update(
            last_run_at=timezone.now() - timedelta(hours=5))
        home = panel.get('/').content.decode('utf-8')
        check('bosh sahifada ogohlantirish chiqdi', 'health-banner' in home)

        # Hammasi joyida bo'lsa banner KO'RINMASLIGI kerak — aks holda u
        # fon shovqiniga aylanadi va haqiqiy muammo ham sezilmay qoladi
        original_collect = health.collect
        health.collect = lambda: {'checks': [], 'overall': 'ok', 'down': [],
                                  'warn': [], 'checked_at': timezone.now()}
        try:
            clean = panel.get('/').content.decode('utf-8')
            check('hammasi joyida bo\'lsa banner yo\'q',
                  'health-banner' not in clean)
        finally:
            health.collect = original_collect

        staff.delete()

    finally:
        _cleanup()
        for row in saved:
            JobStatus.objects.create(**row)

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
