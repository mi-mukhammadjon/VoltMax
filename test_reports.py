# -*- coding: utf-8 -*-
"""Foydalanuvchi yuboradigan nosozlik xabarlari.

Ilova ilgari «xabaringiz qabul qilindi» deb yozardi va hech qayerga
hech narsa yubormasdi. Endi yuboradi — va aynan shuning uchun bu yerda
sinov kerak: xabar qabul qilinishi yetarli emas, u NOTO'G'RI ish
qilmasligi ham kerak.

Asosiy savollar:
  1. Xabar stansiyani buzuq qilib qo'yadimi (qo'ymasligi kerak)?
  2. Qurilmaning o'z xabari foydalanuvchi matni bilan almashib
     ketadimi (ketmasligi kerak)?
  3. Bitta odam ro'yxatni to'ldirib tashlay oladimi?
  4. Ikki odamning xabari ikkita yozuv ochadimi?
  5. Tizimga kirmagan odam xabar bera oladimi?
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
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from stations import reports  # noqa: E402
from stations.models import Connector, MaintenanceIssue, Station, StationReport  # noqa: E402

failures = 0

PREFIX = '__rp'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    StationReport.objects.filter(station__name__startswith=PREFIX).delete()
    MaintenanceIssue.objects.filter(station__name__startswith=PREFIX).delete()
    Connector.objects.filter(station__name__startswith=PREFIX).delete()
    Station.objects.filter(name__startswith=PREFIX).delete()
    User.objects.filter(username__startswith=PREFIX).delete()


def api(user):
    client = Client()
    client.defaults['HTTP_AUTHORIZATION'] = (
        f'Bearer {RefreshToken.for_user(user).access_token}')
    return client


# Sinovda cheklov o'chiriladi: u bu yerda tekshirilmaydi va boshqa
# sinovlar bilan bitta hisobga tushib, tasodifiy yiqilishga olib kelardi
NO_THROTTLE = {'DEFAULT_THROTTLE_RATES': {
    'anon': None, 'user': None, 'otp': None,
    'promo': None, 'review': None, 'report': None,
}}


@override_settings(ALLOWED_HOSTS=['testserver'], DEBUG=True,
                   REST_FRAMEWORK={
                       'DEFAULT_AUTHENTICATION_CLASSES': [
                           'rest_framework_simplejwt.authentication.JWTAuthentication'],
                       'DEFAULT_PERMISSION_CLASSES': [
                           'rest_framework.permissions.IsAuthenticated'],
                       **NO_THROTTLE,
                   })
def main():
    _cleanup()

    station = Station.objects.create(
        name=f'{PREFIX} Stansiya', address='Sinov', latitude=41.3, longitude=69.2,
        charger_type='dc', power_kw=60)
    connector = Connector.objects.create(
        station=station, label='A1', status=Connector.Status.AVAILABLE,
        type='ccs2', power_kw=60)

    user = User.objects.create_user(f'{PREFIX}1', password='x')
    other = User.objects.create_user(f'{PREFIX}2', password='x')

    # ── 1. Xabar qabul qilinadi ──────────────────────────────────
    response = api(user).post(
        f'/api/stations/{station.pk}/report/',
        {'note': 'Ulagich ishlamayapti'}, content_type='application/json')
    check('xabar qabul qilindi', response.status_code == 201, response.status_code)
    check('yangi muammo sifatida belgilandi',
          response.json().get('alreadyKnown') is False, response.json())
    check('yozuv qoldi', StationReport.objects.filter(station=station).count() == 1)

    issue = MaintenanceIssue.objects.filter(station=station).first()
    check('nosozlik yozuvi ochildi', issue is not None)
    check('manbasi — foydalanuvchi',
          issue and issue.source == MaintenanceIssue.Source.USER,
          issue.source if issue else '')
    check('izoh sababga tushdi',
          issue and 'ishlamayapti' in issue.reason, issue.reason if issue else '')
    # Birinchi xabar «2 ta» bo'lib ko'rinsa, operator ikki kishi
    # shikoyat qilgan deb o'ylardi
    check('birinchi xabar bitta deb sanaldi',
          issue and '2 ta' not in issue.reason, issue.reason if issue else '')

    # ── 2. Stansiya BUZUQ bo'lib qolmadi ─────────────────────────
    # Eng muhim tekshiruv: aks holda bitta odam istalgan stansiyani
    # ilovada «ishlamaydi» qilib qo'ya olardi
    connector.refresh_from_db()
    station.refresh_from_db()
    check('ULAGICH holati o‘zgarmadi',
          connector.status == Connector.Status.AVAILABLE, connector.status)
    check('STANSIYA holati ham o‘zgarmadi',
          station.status == Station.Status.AVAILABLE, station.status)

    # ── 3. Bir odam qayta yubora olmaydi ─────────────────────────
    again = api(user).post(
        f'/api/stations/{station.pk}/report/', {}, content_type='application/json')
    check('takroriy xabar rad etildi', again.status_code == 429, again.status_code)
    check('ikkinchi yozuv yaratilmadi',
          StationReport.objects.filter(station=station).count() == 1)

    # ── 4. Boshqa odam — o'sha yozuvga ulanadi ───────────────────
    second = api(other).post(
        f'/api/stations/{station.pk}/report/',
        {'note': 'Men ham'}, content_type='application/json')
    check('boshqa odam xabar bera oldi', second.status_code == 201, second.status_code)
    check('u yangi muammo ochmadi',
          second.json().get('alreadyKnown') is True, second.json())
    check('nosozlik yozuvi bittaligicha qoldi',
          MaintenanceIssue.objects.filter(station=station).count() == 1)
    issue.refresh_from_db()
    check('operator nechta xabar kelganini ko‘radi',
          '2 ta' in issue.reason, issue.reason)

    # ── 5. Qurilmaning o'z xabari ustidan yozilmaydi ─────────────
    # Charger «Ulagichda qisqa tutashuv» desa, buni foydalanuvchining
    # «ishlamayapti» matni bilan almashtirish tashxisni yo'qotardi
    _cleanup()
    station = Station.objects.create(
        name=f'{PREFIX} Ikki', address='Sinov', latitude=41.3, longitude=69.2,
        charger_type='dc', power_kw=60)
    user = User.objects.create_user(f'{PREFIX}3', password='x')

    from stations import maintenance

    device_issue, _ = maintenance.open_issue(
        station=station, reason='Qisqa tutashuv', error_code='GroundFailure')
    api(user).post(f'/api/stations/{station.pk}/report/',
                   {'note': 'ishlamayapti'}, content_type='application/json')
    device_issue.refresh_from_db()
    check('qurilma tashxisi saqlanib qoldi',
          device_issue.reason == 'Qisqa tutashuv', device_issue.reason)
    check('manbasi ham qurilmaligicha qoldi',
          device_issue.source == MaintenanceIssue.Source.OCPP, device_issue.source)
    check('xabar o‘sha yozuvga ulandi',
          StationReport.objects.filter(issue=device_issue).count() == 1)

    # ── 6. Kirmagan odam ─────────────────────────────────────────
    anon = Client().post(f'/api/stations/{station.pk}/report/',
                         {}, content_type='application/json')
    check('kirmagan odam xabar bera olmadi', anon.status_code == 401, anon.status_code)

    # ── 7. Muddat o'tgach qayta yuborsa bo'ladi ──────────────────
    old = StationReport.objects.filter(station=station).first()
    old.created_at = timezone.now() - reports.COOLDOWN - timedelta(minutes=1)
    old.save(update_fields=['created_at'])
    later = api(user).post(f'/api/stations/{station.pk}/report/',
                           {}, content_type='application/json')
    check('muddat o‘tgach qayta yubordi', later.status_code == 201, later.status_code)

    # ── 8. Uzun izoh kesiladi ────────────────────────────────────
    user4 = User.objects.create_user(f'{PREFIX}4', password='x')
    api(user4).post(f'/api/stations/{station.pk}/report/',
                    {'note': 'x' * 5000}, content_type='application/json')
    longest = max(len(r.note) for r in StationReport.objects.filter(station=station))
    check('uzun izoh kesildi', longest <= reports.NOTE_LIMIT, longest)

    _cleanup()


if __name__ == '__main__':
    main()
    print('\n' + (f'*** {failures} TA XATO ***' if failures else 'HAMMASI OK'))
    raise SystemExit(1 if failures else 0)
