# -*- coding: utf-8 -*-
"""Onlayn to'lov: Payme va Click integratsiyasi.

Ilgari `/api/wallet/topup/` balansni to'g'ridan-to'g'ri oshirardi — ya'ni
pulsiz to'ldirish mumkin edi. Endi balans faqat to'lov tizimi tasdiqlagach
oshadi.

Asosiy savollar:
  1. Havola olish buyurtma yaratadimi va balansga TEGMAYDImi?
  2. Payme oqimi to'liq ishlaydimi (tekshir → yarat → to'la → bekor qil)?
  3. Takroriy so'rovda pul IKKI MARTA qo'shilmaydimi (eng muhim talab)?
  4. Imzo/parol noto'g'ri bo'lsa rad etiladimi?
  5. Click ikki bosqichli oqimi va imzo tekshiruvi ishlaydimi?
  6. To'langan to'lov bekor qilinsa pul qaytarib olinadimi?

Tarmoqqa chiqilmaydi: to'lov tizimlari BIZGA murojaat qiladi, ya'ni
webhook'larni to'g'ridan-to'g'ri chaqirish kifoya.
"""
import base64
import hashlib
import json
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from management.models import PaymentProvider, SiteSettings  # noqa: E402
from wallet.models import PaymentOrder, Transaction, WalletBalance  # noqa: E402

failures = 0

PAYME_KEY = '__pm_secret_key'
CLICK_KEY = '__ck_secret_key'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    PaymentOrder.objects.filter(user__username__startswith='__py').delete()
    Transaction.objects.filter(user__username__startswith='__py').delete()
    User.objects.filter(username__startswith='__py').delete()
    PaymentProvider.objects.filter(code__in=['payme', 'click']).update(
        merchant_id='', secret_key='')


def api(user):
    client = Client()
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {RefreshToken.for_user(user).access_token}'
    return client


def payme_call(method, params, key=PAYME_KEY, request_id=1):
    """Payme JSON-RPC so'rovi."""
    auth = base64.b64encode(f'Paycom:{key}'.encode()).decode()
    return Client().post(
        '/api/payments/payme/',
        data=json.dumps({'jsonrpc': '2.0', 'id': request_id,
                         'method': method, 'params': params}),
        content_type='application/json',
        HTTP_AUTHORIZATION=f'Basic {auth}',
    ).json()


def click_sign(data, key, *, with_prepare):
    parts = [data['click_trans_id'], data['service_id'], key, data['merchant_trans_id']]
    if with_prepare:
        parts.append(data['merchant_prepare_id'])
    parts += [data['amount'], data['action'], data['sign_time']]
    return hashlib.md5(''.join(str(p) for p in parts).encode()).hexdigest()


def balance(user):
    wallet = WalletBalance.objects.filter(user=user).first()
    return wallet.amount if wallet else 0


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f) for f in ('min_topup', 'max_topup')}
    try:
        settings_obj.min_topup = 5000
        settings_obj.max_topup = 1000000
        settings_obj.save()

        PaymentProvider.objects.update_or_create(
            code='payme', defaults={'name': 'Payme', 'is_active': True,
                                    'merchant_id': '__pm_merchant',
                                    'secret_key': PAYME_KEY})
        PaymentProvider.objects.update_or_create(
            code='click', defaults={'name': 'Click', 'is_active': True,
                                    'merchant_id': '12345',
                                    'secret_key': CLICK_KEY,
                                    'note': 'merchant_id=999'})

        driver = User.objects.create(username='__py_driver__')
        WalletBalance.objects.create(user=driver, amount=0)

        # ── 1. Havola olish ─────────────────────────────────────
        rows = api(driver).get('/api/wallet/providers/').json()
        check('sozlangan tizimlar ro\'yxati qaytdi',
              {r['code'] for r in rows['results']} >= {'payme', 'click'}, rows)

        response = api(driver).post('/api/wallet/topup/',
                                    {'amount': 50000, 'provider': 'payme'},
                                    content_type='application/json')
        check('havola qaytdi', response.status_code == 201, response.status_code)
        data = response.json()
        order = PaymentOrder.objects.get(pk=data['orderId'])
        check('buyurtma yaratildi', order.amount == 50000 and order.is_open)
        check('BALANS OSHMADI (pul hali kelmagan)', balance(driver) == 0, balance(driver))

        decoded = base64.b64decode(data['checkoutUrl'].rsplit('/', 1)[1]).decode()
        check('havolada merchant, buyurtma va tiyin bor',
              '__pm_merchant' in decoded and f'ac.order_id={order.pk}' in decoded
              and 'a=5000000' in decoded, decoded)

        small = api(driver).post('/api/wallet/topup/', {'amount': 1000, 'provider': 'payme'},
                                 content_type='application/json')
        check('chegaradan kam summa rad etildi', small.status_code == 400, small.status_code)

        # ── 2. Payme oqimi ──────────────────────────────────────
        check('noto\'g\'ri parol rad etildi',
              payme_call('CheckPerformTransaction',
                         {'account': {'order_id': order.pk}, 'amount': 5000000},
                         key='boshqa-kalit').get('error', {}).get('code') == -32504)

        allow = payme_call('CheckPerformTransaction',
                           {'account': {'order_id': order.pk}, 'amount': 5000000})
        check('tekshiruvdan o\'tdi', allow.get('result') == {'allow': True}, allow)

        wrong = payme_call('CheckPerformTransaction',
                           {'account': {'order_id': order.pk}, 'amount': 100})
        check('noto\'g\'ri summa rad etildi',
              wrong.get('error', {}).get('code') == -31001, wrong)

        missing = payme_call('CheckPerformTransaction',
                             {'account': {'order_id': 99999999}, 'amount': 5000000})
        check('yo\'q buyurtma rad etildi',
              missing.get('error', {}).get('code') == -31050, missing)

        created = payme_call('CreateTransaction',
                             {'id': '__pm_tx_1', 'time': 1700000000000,
                              'account': {'order_id': order.pk}, 'amount': 5000000})
        check('tranzaksiya ochildi', created['result']['state'] == 1, created)

        again = payme_call('CreateTransaction',
                           {'id': '__pm_tx_1', 'time': 1700000000000,
                            'account': {'order_id': order.pk}, 'amount': 5000000})
        check('takroriy ochish yangi tranzaksiya yaratmadi',
              again['result']['transaction'] == created['result']['transaction'], again)

        performed = payme_call('PerformTransaction', {'id': '__pm_tx_1'})
        order.refresh_from_db()
        check('to\'lov yakunlandi', performed['result']['state'] == 2, performed)
        check('BALANS OSHDI', balance(driver) == 50000, balance(driver))
        check('tranzaksiya yozildi',
              order.transaction is not None and order.transaction.amount == 50000)

        # Eng muhim talab: takroriy so'rovda pul ikki marta qo'shilmaydi
        payme_call('PerformTransaction', {'id': '__pm_tx_1'})
        payme_call('PerformTransaction', {'id': '__pm_tx_1'})
        check('TAKRORIY SO\'ROVDA PUL IKKI MARTA QO\'SHILMADI',
              balance(driver) == 50000
              and Transaction.objects.filter(user=driver).count() == 1,
              balance(driver))

        status = payme_call('CheckTransaction', {'id': '__pm_tx_1'})
        check('holat so\'ralganda to\'langan deb qaytdi',
              status['result']['state'] == 2, status)

        statement = payme_call('GetStatement', {'from': 0, 'to': 9999999999999})
        check('davr ro\'yxatida ko\'rindi',
              any(t['id'] == '__pm_tx_1' for t in statement['result']['transactions']))

        # ── 3. To'langan to'lovni bekor qilish ──────────────────
        cancelled = payme_call('CancelTransaction', {'id': '__pm_tx_1', 'reason': 5})
        order.refresh_from_db()
        check('bekor qilindi', cancelled['result']['state'] == -2, cancelled)
        check('pul hamyondan qaytarib olindi', balance(driver) == 0, balance(driver))
        check('takroriy bekor qilish balansni buzmadi',
              payme_call('CancelTransaction', {'id': '__pm_tx_1'})['result']['state'] == -2
              and balance(driver) == 0)

        # ── 4. Click oqimi ──────────────────────────────────────
        response = api(driver).post('/api/wallet/topup/',
                                    {'amount': 30000, 'provider': 'click'},
                                    content_type='application/json')
        click_order = PaymentOrder.objects.get(pk=response.json()['orderId'])
        check('click havolasida xizmat va buyurtma bor',
              f'transaction_param={click_order.pk}' in response.json()['checkoutUrl']
              and 'service_id=12345' in response.json()['checkoutUrl'],
              response.json()['checkoutUrl'])

        payload = {
            'click_trans_id': '__ck_1', 'service_id': '12345',
            'merchant_trans_id': str(click_order.pk), 'amount': '30000.00',
            'action': '0', 'sign_time': '2026-08-31 10:00:00',
        }
        bad = Client().post('/api/payments/click/prepare/',
                            {**payload, 'sign_string': 'yolgon'}).json()
        check('imzosi buzilgan so\'rov rad etildi', bad['error'] == -1, bad)
        check('imzo tekshiruvidan o\'tmagan so\'rov holatni o\'zgartirmadi',
              PaymentOrder.objects.get(pk=click_order.pk).state == PaymentOrder.State.CREATED)

        payload['sign_string'] = click_sign(payload, CLICK_KEY, with_prepare=False)
        prepared = Client().post('/api/payments/click/prepare/', payload).json()
        check('prepare bosqichi o\'tdi', prepared['error'] == 0, prepared)

        complete_payload = {
            'click_trans_id': '__ck_1', 'service_id': '12345',
            'merchant_trans_id': str(click_order.pk),
            'merchant_prepare_id': str(prepared['merchant_prepare_id']),
            'amount': '30000.00', 'action': '1', 'sign_time': '2026-08-31 10:01:00',
            'error': '0',
        }
        complete_payload['sign_string'] = click_sign(complete_payload, CLICK_KEY,
                                                     with_prepare=True)
        completed = Client().post('/api/payments/click/complete/', complete_payload).json()
        check('complete bosqichi o\'tdi', completed['error'] == 0, completed)
        check('click orqali balans oshdi', balance(driver) == 30000, balance(driver))

        repeat = Client().post('/api/payments/click/complete/', complete_payload).json()
        check('click takroriy so\'rovda pul qo\'shilmadi',
              repeat['error'] == -4 and balance(driver) == 30000, repeat)

        # ── 5. Sozlanmagan tizim ────────────────────────────────
        PaymentProvider.objects.filter(code='payme').update(secret_key='', merchant_id='')
        blocked = api(driver).post('/api/wallet/topup/',
                                   {'amount': 50000, 'provider': 'payme'},
                                   content_type='application/json')
        check('sozlanmagan tizim orqali to\'lov boshlanmadi',
              blocked.status_code == 503, blocked.status_code)
        rows = api(driver).get('/api/wallet/providers/').json()
        check('sozlanmagan tizim ro\'yxatda ko\'rinmadi',
              'payme' not in {r['code'] for r in rows['results']}, rows)

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
