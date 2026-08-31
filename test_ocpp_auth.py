# -*- coding: utf-8 -*-
"""OCPP ulanishini himoya qilish va to'lov kalitlarini solishtirish.

Ilgari charger ulanishi uchun FAQAT `ocpp_id` ni bilish yetardi. U esa
maxfiy emas: qurilmaning ustida yozilgan, panelda ko'rinadi va odatda
ketma-ket (CP-001, CP-002) — ya'ni taxmin qilsa bo'ladi.

Oqibati pul qo'shish emas, undan yomonroq — pul YECHISH: soxta "charger"
ulanib, istalgan `idTag` bilan sessiya ochib-yopib, begona odamning
hamyonidan pul yechishi mumkin edi. Shu bilan birga stansiyalarni "nosoz"
deb belgilash va hisobotlarni buzish ham mumkin edi.

Asosiy savollar:
  1. Parolsiz ulanish rad etiladimi?
  2. Noto'g'ri parol rad etiladimi va bu YOZILADIMI?
  3. To'g'ri parol bilan ulanish ishlaydimi (himoya haddan tashqari
     qattiq emasmi)?
  4. Talab o'chirilganda eski qurilmalar ishlay oladimi?
  5. Panel parolsiz OCPP manzilini yaratishga yo'l qo'ymaydimi?
  6. To'lov kalitlari doimiy vaqtda solishtiriladimi va buyurtma
     boshqa to'lov tizimiga o'tib ketmaydimi?
"""
import base64
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from asgiref.sync import async_to_sync  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402

from management.models import PaymentProvider, SiteSettings  # noqa: E402
from ocpp_gateway.routing import websocket_urlpatterns  # noqa: E402
from stations.models import ChargerLog, Station  # noqa: E402
from wallet.models import PaymentOrder  # noqa: E402

failures = 0

CP = '__AUTH_CP__'
PASSWORD = 'juda-uzun-va-maxfiy-parol'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    PaymentOrder.objects.filter(user__username__startswith='__auth').delete()
    Station.objects.filter(name__startswith='__auth').delete()
    User.objects.filter(username__startswith='__auth').delete()


def application():
    return ProtocolTypeRouter({'websocket': URLRouter(websocket_urlpatterns)})


def basic(login, password):
    raw = base64.b64encode(f'{login}:{password}'.encode()).decode()
    return [(b'authorization', f'Basic {raw}'.encode())]


async def connect(headers=None):
    communicator = WebsocketCommunicator(
        application(), f'/ws/ocpp/{CP}/', subprotocols=['ocpp1.6'],
        headers=headers or [])
    connected, _ = await communicator.connect(timeout=5)
    if connected:
        await communicator.disconnect()
    return connected


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {'require_ocpp_auth': settings_obj.require_ocpp_auth}
    try:
        settings_obj.require_ocpp_auth = True
        settings_obj.save()

        station = Station.objects.create(
            name='__auth Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='DC', power_kw=60, ocpp_id=CP, ocpp_password=PASSWORD)

        # ── 1. Parolsiz va noto'g'ri parol ──────────────────────
        check('parolsiz ulanish rad etildi', not async_to_sync(connect)())
        check("noto'g'ri parol rad etildi",
              not async_to_sync(connect)(basic(CP, 'yolgon-parol')))
        check("parolning bir qismi ham yetarli emas",
              not async_to_sync(connect)(basic(CP, PASSWORD[:-1])))
        check('boshqa login bilan rad etildi',
              not async_to_sync(connect)(basic('boshqa', PASSWORD)))

        # Urinishlar YOZILISHI kerak: aks holda kimdir manzilni topib parol
        # tanlayotganini bilishning iloji bo'lmasdi
        rejected = ChargerLog.objects.filter(station=station, action='Connect').count()
        check('rad etilgan urinishlar yozildi', rejected == 4, rejected)

        # ── 2. To'g'ri parol ────────────────────────────────────
        check("to'g'ri parol bilan ulandi",
              async_to_sync(connect)(basic(CP, PASSWORD)))
        check('login yuborilmasa ham ishladi',
              async_to_sync(connect)(basic('', PASSWORD)))

        # ── 3. Talab o'chirilganda ──────────────────────────────
        # Basic autentifikatsiyani qo'llab-quvvatlamaydigan eski qurilma
        # uchun yo'l qolishi kerak — lekin faqat parol umuman
        # qo'yilmagan stansiyada
        station.ocpp_password = ''
        station.save()
        check('parolsiz stansiya majburiy rejimda ulanmadi',
              not async_to_sync(connect)())

        settings_obj.require_ocpp_auth = False
        settings_obj.save()
        check("talab o'chirilgach parolsiz stansiya ulandi",
              async_to_sync(connect)())

        # Parol QO'YILGAN bo'lsa, talab o'chiq bo'lsa ham u tekshiriladi:
        # aks holda sozlamani o'chirish hamma parollarni bekor qilardi
        station.ocpp_password = PASSWORD
        station.save()
        check("parol qo'yilgan stansiya baribir tekshirildi",
              not async_to_sync(connect)())
        settings_obj.require_ocpp_auth = True
        settings_obj.save()

        # ── 4. Panel parolsiz manzil yaratmaydi ─────────────────
        admin = User.objects.filter(is_superuser=True).first()
        if admin is not None:
            panel = Client()
            panel.force_login(admin)
            form = {
                'name': '__auth Yangi', 'address': 'a', 'latitude': 41.0,
                'longitude': 69.0, 'charger_type': 'DC', 'power_kw': 60,
                'ocpp_id': '__AUTH_NEW__', 'rating': '',
                'discount_price_per_kwh': '', 'partner': '',
            }
            panel.post('/stations/new/', {**form, 'ocpp_password': ''})
            check('panel parolsiz OCPP manzilini yaratmadi',
                  not Station.objects.filter(name='__auth Yangi').exists())

            panel.post('/stations/new/', {**form, 'ocpp_password': 'yangi-parol'})
            created = Station.objects.filter(name='__auth Yangi').first()
            check('parol bilan yaratildi', created is not None)

            if created is not None:
                # Tahrirlashda bo'sh yuborilsa parol o'chib ketmasligi kerak:
                # aks holda oddiy tahrir chargerni uzib qo'yardi
                panel.post(f'/stations/{created.id}/edit/',
                           {**form, 'ocpp_password': ''})
                created.refresh_from_db()
                check("bo'sh yuborilgach parol saqlanib qoldi",
                      created.ocpp_password == 'yangi-parol')
                check('parol panelda to\'liq ko\'rsatilmadi',
                      'yangi-parol' not in
                      panel.get(f'/stations/{created.id}/edit/').content.decode('utf-8'))

        # ── 5. To'lov kalitlari ─────────────────────────────────
        from wallet import click, payme

        provider, _ = PaymentProvider.objects.get_or_create(
            code='payme', defaults={'name': 'Payme'})
        provider.secret_key = 'sinov-kalit-777'
        provider.is_active = True
        provider.save()

        class FakeRequest:
            def __init__(self, header):
                self.headers = {'Authorization': header} if header else {}

        token = base64.b64encode(b'Paycom:sinov-kalit-777').decode()
        check("to'g'ri kalit qabul qilindi",
              payme._authorized(FakeRequest(f'Basic {token}'), provider))
        wrong = base64.b64encode(b'Paycom:boshqa-kalit').decode()
        check("noto'g'ri kalit rad etildi",
              not payme._authorized(FakeRequest(f'Basic {wrong}'), provider))
        check('kalitsiz so\'rov rad etildi',
              not payme._authorized(FakeRequest(''), provider))

        # Buyurtma BOSHQA to'lov tizimiga o'tib ketmasligi kerak
        driver = User.objects.create(username='__auth_driver__')
        click_provider, _ = PaymentProvider.objects.get_or_create(
            code='click', defaults={'name': 'Click'})
        order = PaymentOrder.objects.create(
            user=driver, provider=click_provider, amount=50000)

        found = payme._find_order({'account': {'order_id': str(order.pk)}}, provider)
        check("Click buyurtmasi Payme so'roviga berilmadi", found is None)
        found = payme._find_order({'account': {'order_id': str(order.pk)}},
                                  click_provider)
        check("o'z tizimining buyurtmasi topildi",
              found is not None and found.pk == order.pk)

        found = click._find_order({'merchant_trans_id': str(order.pk)}, provider)
        check("Payme buyurtmasi Click so'roviga berilmadi", found is None)

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        Station.objects.filter(name__startswith='__auth').delete()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
