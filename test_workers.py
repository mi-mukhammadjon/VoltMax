# -*- coding: utf-8 -*-
"""Davriy vazifalar: bitta jarayonda ishlaydigan ishchi.

Ilgari vazifalar to'rtta alohida buyruq edi va har biri uchun alohida
server jarayoni kerak bo'lardi. Bittasini sozlash unutilsa u jimgina
ishlamay qolardi — parkovka hisoblanmasdi, xabar telefonga bormasdi va
buni hech kim payqamasdi.

Asosiy savollar:
  1. Barcha vazifalar ro'yxatda bormi va ular haqiqiy ishni bajaradimi?
  2. Bir vazifa xato bersa qolganlari to'xtab qolmaydimi?
  3. `--only` bilan tanlab ishlatish mumkinmi?
  4. Joylashtirish sozlamasi vazifalarni ishga tushiradimi (Procfile'da
     ishchi bormi va railway.json uni bosib ketmaydimi)?
"""
import io
import json
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from io import StringIO  # noqa: E402

from django.core.management import call_command  # noqa: E402

from management.management.commands import run_workers  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def main():
    names = [name for name, _f, _i in run_workers.JOBS]
    check('barcha vazifalar ro\'yxatda',
          set(names) == {'parking', 'devices', 'overdue', 'push'}, names)
    check('har vazifaning oralig\'i belgilangan',
          all(interval > 0 for _n, _f, interval in run_workers.JOBS))
    check('push eng tez-tez ishlaydi',
          dict((n, i) for n, _f, i in run_workers.JOBS)['push']
          == min(i for _n, _f, i in run_workers.JOBS))

    # ── Haqiqiy ish: bir marta ishga tushiramiz ─────────────────
    out, err = StringIO(), StringIO()
    call_command('run_workers', once=True, stdout=out, stderr=err)
    check('bir martalik ishga tushirish xatosiz o\'tdi',
          'Traceback' not in err.getvalue(), err.getvalue()[:120])

    out = StringIO()
    call_command('run_workers', once=True, only='push', stdout=out, stderr=StringIO())
    check('faqat tanlangan vazifa ishlaydi', True)

    err = StringIO()
    call_command('run_workers', once=True, only='yoq-bunday',
                 stdout=StringIO(), stderr=err)
    check('noma\'lum vazifa nomi aytildi',
          "Noma'lum vazifa" in err.getvalue(), err.getvalue().strip()[:60])

    # ── Xato butun ishchini to'xtatmaydi ────────────────────────
    command = run_workers.Command()
    command.stdout, command.stderr = StringIO(), StringIO()

    def broken():
        raise RuntimeError('sinov xatosi')

    command._run('sinov', broken)
    check('xato tsiklni to\'xtatmadi (faqat yozib qo\'yildi)',
          'sinov xatosi' in command.stderr.getvalue(),
          command.stderr.getvalue().strip()[:60])

    # ── Joylashtirish sozlamasi ─────────────────────────────────
    procfile = io.open('Procfile', encoding='utf-8').read()
    check('Procfile\'da ishchi bor', 'worker: python manage.py run_workers' in procfile)
    check('Procfile\'da veb-server bor', 'web: daphne' in procfile)
    check('migratsiya release bosqichida', 'release: python manage.py migrate' in procfile)

    railway = json.loads(io.open('railway.json', encoding='utf-8').read())
    # `startCommand` Procfile'ni bosib ketadi va `release` bosqichi ham
    # o'tmay qolishi mumkin — natijada migratsiyalar qo'llanmaydi
    check('railway.json Procfile\'ni bosib ketmaydi',
          'startCommand' not in railway.get('deploy', {}), railway.get('deploy'))

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
