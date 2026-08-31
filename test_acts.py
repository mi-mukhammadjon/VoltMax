# -*- coding: utf-8 -*-
"""Korporativ oylik hujjatlar: bajarilgan ishlar va solishtirma dalolatnoma.

Bir oyda yuzlab sessiya bo'ladi — ularni qo'lda yig'ish xatoga olib keladi,
xato esa nizoga aylanadi. Shuning uchun hujjat bazadagi ma'lumotdan
yig'iladi va bu yerda aynan HISOB tekshiriladi.

Asosiy savollar:
  1. Dalolatnomaga faqat SHU DAVRdagi tugagan sessiyalar kiradimi?
  2. Energiya va parkovka alohida ko'rsatiladimi, jami to'g'rimi?
  3. Solishtirmada davr boshi/oxiri qoldig'i va aylanma to'g'rimi?
  4. Ketayotgan sessiya hujjatga kirmaydimi (uning summasi hali noma'lum)?
  5. Sahifa faqat xodimga ochiqmi va fayl nomi to'g'rimi?
"""
import os
import zipfile
from io import BytesIO

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import date, timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import Company  # noqa: E402
from dashboard.acts import (  # noqa: E402
    balance_at, month_range, period_sessions,
)
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Station  # noqa: E402
from wallet.models import Transaction, WalletBalance  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def document_text(payload):
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return archive.read('word/document.xml').decode('utf-8')


def _cleanup():
    ChargingSession.objects.filter(station__name__startswith='__ac').delete()
    Transaction.objects.filter(user__username__startswith='company-__ac').delete()
    Station.objects.filter(name__startswith='__ac').delete()
    Company.objects.filter(name__startswith='__ac').delete()
    User.objects.filter(username__startswith='__ac').delete()
    User.objects.filter(username__startswith='company-__ac').delete()


def make_session(company, station, connector, when, *, kwh, energy, parking=0,
                 minutes=0, status=ChargingSession.Status.COMPLETED):
    session = ChargingSession.objects.create(
        user=company.billing_user, station=station, connector=connector,
        power_kw=60, price_per_kwh=1200, connector_label='A', start_percent=20,
        status=status,
        final_kwh_charged=kwh, final_cost=energy + parking,
        final_parking_cost=parking, final_parking_minutes=minutes,
    )
    ChargingSession.objects.filter(pk=session.pk).update(stopped_at=when)
    session.refresh_from_db()
    return session


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    admin = User.objects.create(username='__ac_admin__', is_staff=True, is_superuser=True)
    try:
        company = Company.objects.create(
            billing_user=User.objects.create(username='company-__ac_taxi__'),
            name='__ac Taksi', legal_name='__ac Taksi MChJ', inn='305111222',
            bank_account='20208000900111222333', director='Karimov K.K.',
        )
        WalletBalance.objects.create(user=company.billing_user, amount=0)

        station = Station.objects.create(
            name='__ac Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='dc', power_kw=60)
        connector = Connector.objects.create(station=station, label='A',
                                             type='ccs2', power_kw=60)

        # Davr: joriy oyning boshidan
        today = timezone.localdate()
        year, month = today.year, today.month
        start, end = month_range(year, month)
        inside = timezone.make_aware(
            timezone.datetime.combine(start + timedelta(days=1),
                                      timezone.datetime.min.time()))
        before = timezone.make_aware(
            timezone.datetime.combine(start - timedelta(days=3),
                                      timezone.datetime.min.time()))

        make_session(company, station, connector, inside, kwh=20.5, energy=24600)
        make_session(company, station, connector, inside + timedelta(days=2),
                     kwh=10.0, energy=12000, parking=2500, minutes=5)
        # Oldingi oydagi sessiya — bu davrga kirmasligi kerak
        make_session(company, station, connector, before, kwh=99.0, energy=118800)
        # Ketayotgan sessiya — yakuniy summasi hali noma'lum
        make_session(company, station, connector, inside, kwh=5.0, energy=6000,
                     status=ChargingSession.Status.CHARGING)

        rows = list(period_sessions(company, start, end))
        check('davr sessiyalari ajratildi', len(rows) == 2, len(rows))
        check('oldingi oy sessiyasi kirmadi',
              all(abs((s.kwh_charged or 0) - 99.0) > 0.01 for s in rows))
        check('ketayotgan sessiya kirmadi',
              all(s.status != ChargingSession.Status.CHARGING for s in rows))

        # ── Hamyon harakatlari ──────────────────────────────────
        topup = Transaction.objects.create(
            user=company.billing_user, type=Transaction.Type.TOPUP,
            amount=100000, description='__ac to\'ldirish')
        Transaction.objects.filter(pk=topup.pk).update(created_at=inside)
        charge = Transaction.objects.create(
            user=company.billing_user, type=Transaction.Type.CHARGE_PAYMENT,
            amount=39100, description='__ac zaryadlash')
        Transaction.objects.filter(pk=charge.pk).update(created_at=inside)

        wallet = WalletBalance.objects.get(user=company.billing_user)
        wallet.amount = 60900
        wallet.save(update_fields=['amount'])

        check('davr boshiga qoldiq hisoblandi',
              balance_at(company, start) == 0, balance_at(company, start))

        client = Client()
        url = reverse('dashboard:company_documents', args=[company.pk, year, month])
        check('anonim foydalanuvchi kirita olmadi',
              client.get(url).status_code in (302, 403))

        client.force_login(admin)

        # ── Bajarilgan ishlar dalolatnomasi ─────────────────────
        response = client.get(url)
        payload = (b''.join(response.streaming_content)
                   if response.streaming else response.content)
        check('dalolatnoma yuklandi',
              response.status_code == 200 and zipfile.is_zipfile(BytesIO(payload)),
              response.status_code)
        check('fayl nomi davr bilan',
              f'dalolatnoma-ac-taksi-{year}-{month:02d}.docx'
              in response.get('Content-Disposition', ''),
              response.get('Content-Disposition'))

        text = document_text(payload)
        check('sarlavha bor', 'BAJARILGAN ISHLAR DALOLATNOMASI' in text)
        check('ikkala tomon rekvizitlari bor',
              '__ac Taksi MChJ' in text and '305 111 222' in text)
        # 20.5 + 10.0 = 30.50 kVt·soat, energiya 24 600 + 12 000 = 36 600
        check('energiya miqdori to\'g\'ri', '30.50' in text, '30.50' in text)
        check('energiya summasi to\'g\'ri', '36 600' in text.replace('\xa0', ' '))
        check('parkovka alohida qator bo\'ldi',
              'parkovka' in text.lower() and '2 500' in text.replace('\xa0', ' '))
        check('jami to\'g\'ri (energiya + parkovka)',
              '39 100' in text.replace('\xa0', ' '))
        check('jami so\'z bilan yozildi',
              "o'ttiz to'qqiz ming bir yuz" in text, "o'ttiz to'qqiz ming" in text)
        check('sessiyalar soni aytildi', '2 ta zaryadlash' in text)

        # ── Solishtirma dalolatnoma ─────────────────────────────
        response = client.get(url, {'kind': 'reconciliation'})
        payload = (b''.join(response.streaming_content)
                   if response.streaming else response.content)
        check('solishtirma yuklandi', response.status_code == 200)
        check('fayl nomi solishtirma',
              'solishtirma-' in response.get('Content-Disposition', ''))

        text = document_text(payload)
        check('solishtirma sarlavhasi', 'SOLISHTIRMA DALOLATNOMA' in text)
        plain = text.replace('\xa0', ' ')
        check('davr boshiga qoldiq bor', 'Davr boshiga qoldiq' in text)
        check('kirim ko\'rsatildi', '100 000' in plain)
        check('chiqim ko\'rsatildi', '39 100' in plain)
        check('davr oxiriga qoldiq to\'g\'ri', '60 900' in plain)

        # ── Noto'g'ri davr ──────────────────────────────────────
        bad = client.get(reverse('dashboard:company_documents',
                                 args=[company.pk, year, 13]))
        check('noto\'g\'ri oy rad etildi', bad.status_code in (302, 404), bad.status_code)

        page = client.get(reverse('dashboard:company_detail',
                                  args=[company.pk])).content.decode('utf-8')
        check('sahifada oylik hujjatlar bo\'limi bor',
              'Oylik hujjatlar' in page and 'Solishtirma' in page)
        check('oxirgi olti oy taklif qilindi',
              page.count('Bajarilgan ishlar') == 6, page.count('Bajarilgan ishlar'))

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
