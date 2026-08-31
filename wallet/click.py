# -*- coding: utf-8 -*-
"""Click Merchant API — ikki bosqichli to'lov.

Payme'dan farqli o'laroq Click JSON-RPC emas, oddiy forma so'rovlarini
yuboradi va ikki qadamda ishlaydi:

    Prepare  (action=0) — buyurtmani tekshir, "tayyorman" de
    Complete (action=1) — to'lov o'tdi, pulni yozib qo'y

Har so'rov `sign_string` bilan imzolanadi (MD5). Imzo tekshirilmasa,
istalgan odam so'rov yuborib hamyon to'ldirishi mumkin bo'lardi — shuning
uchun bu birinchi tekshiruv.

Xato kodlari Click hujjatidan olingan: ular bo'yicha Click qaror qabul
qiladi, o'zboshimchalik bilan javob qaytarilsa to'lov "noaniq" bo'lib
osilib qoladi.
"""

import hashlib
import logging
import secrets

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger('wallet.click')

PROVIDER_CODE = 'click'

# Click xato kodlari
OK = 0
ERROR_SIGN = -1
ERROR_AMOUNT = -2
ERROR_ACTION = -3
ERROR_ALREADY_PAID = -4
ERROR_USER_NOT_FOUND = -5
ERROR_TX_NOT_FOUND = -6
ERROR_BAD_REQUEST = -8
ERROR_CANCELLED = -9

ACTION_PREPARE = '0'
ACTION_COMPLETE = '1'


def _provider():
    from management.models import PaymentProvider

    return PaymentProvider.objects.filter(code=PROVIDER_CODE, is_active=True).first()


def _reply(code, message, extra=None):
    payload = {'error': code, 'error_note': message}
    payload.update(extra or {})
    return JsonResponse(payload)


def _valid_sign(data, provider, *, with_prepare):
    """Imzoni tekshiradi.

    Prepare:  md5(click_trans_id + service_id + KALIT + merchant_trans_id +
                  amount + action + sign_time)
    Complete: o'rtaga `merchant_prepare_id` qo'shiladi.
    """
    if not provider or not provider.secret_key:
        return False

    parts = [
        data.get('click_trans_id', ''),
        data.get('service_id', ''),
        provider.secret_key,
        data.get('merchant_trans_id', ''),
    ]
    if with_prepare:
        parts.append(data.get('merchant_prepare_id', ''))
    parts += [data.get('amount', ''), data.get('action', ''), data.get('sign_time', '')]

    expected = hashlib.md5(''.join(str(p) for p in parts).encode('utf-8')).hexdigest()
    # Doimiy vaqtli solishtirish: oddiy `==` birinchi mos kelmagan belgida
    # to'xtaydi va javob vaqti to'g'ri imzo haqida ma'lumot berardi
    return secrets.compare_digest(expected, (data.get('sign_string') or '').lower())


def _find_order(data, provider=None):
    """Buyurtmani topadi.

    `provider` berilsa, buyurtma AYNAN shu to'lov tizimi uchun
    yaratilganligi ham tekshiriladi.
    """
    from .models import PaymentOrder

    raw = data.get('merchant_trans_id') or ''
    if not str(raw).isdigit():
        return None

    query = PaymentOrder.objects.filter(pk=int(raw))
    if provider is not None:
        query = query.filter(provider=provider)
    return query.select_related('provider', 'user').first()


def _amount_matches(data, order) -> bool:
    """Click summani so'mda, kasr bilan yuboradi ("15000.00")."""
    try:
        return abs(float(data.get('amount') or 0) - order.amount) < 0.01
    except (TypeError, ValueError):
        return False


@csrf_exempt
def prepare(request):
    """POST /api/payments/click/prepare/ — buyurtmani tekshiradi."""
    data = request.POST or request.GET
    provider = _provider()

    if not _valid_sign(data, provider, with_prepare=False):
        return _reply(ERROR_SIGN, 'SIGN CHECK FAILED')
    if data.get('action') != ACTION_PREPARE:
        return _reply(ERROR_ACTION, 'Action not found')

    order = _find_order(data, provider)
    if order is None:
        return _reply(ERROR_USER_NOT_FOUND, 'Order not found')
    if not _amount_matches(data, order):
        return _reply(ERROR_AMOUNT, 'Incorrect parameter amount')

    from .models import PaymentOrder

    if order.state == PaymentOrder.State.PAID:
        return _reply(ERROR_ALREADY_PAID, 'Already paid')
    if not order.is_open:
        return _reply(ERROR_CANCELLED, 'Transaction cancelled')

    order.external_id = str(data.get('click_trans_id') or '')[:64]
    order.prepare_id = str(order.pk)
    order.state = PaymentOrder.State.WAITING
    order.save(update_fields=['external_id', 'prepare_id', 'state', 'updated_at'])

    return _reply(OK, 'Success', {
        'click_trans_id': data.get('click_trans_id'),
        'merchant_trans_id': str(order.pk),
        'merchant_prepare_id': order.pk,
    })


@csrf_exempt
def complete(request):
    """POST /api/payments/click/complete/ — to'lovni yakunlaydi."""
    data = request.POST or request.GET
    provider = _provider()

    if not _valid_sign(data, provider, with_prepare=True):
        return _reply(ERROR_SIGN, 'SIGN CHECK FAILED')
    if data.get('action') != ACTION_COMPLETE:
        return _reply(ERROR_ACTION, 'Action not found')

    order = _find_order(data, provider)
    if order is None:
        return _reply(ERROR_USER_NOT_FOUND, 'Order not found')
    if str(order.prepare_id) != str(data.get('merchant_prepare_id') or ''):
        return _reply(ERROR_TX_NOT_FOUND, 'Transaction not found')
    if not _amount_matches(data, order):
        return _reply(ERROR_AMOUNT, 'Incorrect parameter amount')

    from .models import PaymentOrder

    # Click to'lov bekor qilinganini manfiy `error` bilan xabar qiladi
    try:
        incoming_error = int(data.get('error') or 0)
    except (TypeError, ValueError):
        incoming_error = 0

    if incoming_error < 0:
        order.cancel(reason=incoming_error)
        return _reply(ERROR_CANCELLED, 'Transaction cancelled', {
            'click_trans_id': data.get('click_trans_id'),
            'merchant_trans_id': str(order.pk),
            'merchant_confirm_id': order.pk,
        })

    if order.state == PaymentOrder.State.PAID:
        # Takroriy so'rov — Click tarmoq uzilganda qayta uradi
        return _reply(ERROR_ALREADY_PAID, 'Already paid')
    if not order.is_open:
        return _reply(ERROR_CANCELLED, 'Transaction cancelled')

    order.mark_paid(external_id=str(data.get('click_trans_id') or ''))
    return _reply(OK, 'Success', {
        'click_trans_id': data.get('click_trans_id'),
        'merchant_trans_id': str(order.pk),
        'merchant_confirm_id': order.pk,
    })


def checkout_url(order):
    """Ilova ochadigan havola.

    `service_id` — Click bergan xizmat raqami (Merchant ID maydonida),
    `merchant_id` esa hisob raqami. Ular ikkita alohida son bo'lgani uchun
    izohda `merchant_id=<raqam>` ko'rinishida saqlanadi.
    """
    provider = order.provider
    base = provider.endpoint_url or 'https://my.click.uz/services/pay'
    merchant_id = ''
    for part in (provider.note or '').split():
        if part.startswith('merchant_id='):
            merchant_id = part.split('=', 1)[1]

    return (f'{base}?service_id={provider.merchant_id}'
            f'&merchant_id={merchant_id}'
            f'&amount={order.amount}'
            f'&transaction_param={order.pk}')
