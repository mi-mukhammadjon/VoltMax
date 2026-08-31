# -*- coding: utf-8 -*-
"""Payme Merchant API — to'lov tizimi bizga murojaat qiladigan endpoint.

Payme bilan suhbat teskari yo'nalishda: biz emas, U bizni chaqiradi.
Foydalanuvchi ilovada summa tanlaydi, biz unga havola beramiz, u Payme
ilovasida to'laydi — Payme esa bizning serverga JSON-RPC so'rovlarini
yuboradi:

    CheckPerformTransaction — bunday buyurtma bormi, summa to'g'rimi?
    CreateTransaction       — tranzaksiya ochamiz
    PerformTransaction      — pulni yozib qo'y (mana shu paytda hamyon to'ladi)
    CancelTransaction       — bekor qil (to'langanidan keyin ham bo'lishi mumkin)
    CheckTransaction        — holati qanday?
    GetStatement            — davr bo'yicha ro'yxat (solishtirish uchun)

Ikki narsa muhim:
  * IDEMPOTENTLIK — Payme bir so'rovni bir necha marta yuborishi mumkin
    (tarmoq uzilsa qayta uradi). Shuning uchun `mark_paid` qulf ostida
    ishlaydi va ikkinchi marta pul qo'shmaydi.
  * XATO KODLARI — Payme ularga qarab qaror qabul qiladi. O'zboshimchalik
    bilan 500 qaytarilsa, u to'lovni "noaniq" deb qoldiradi va foydalanuvchi
    puli osilib qoladi.

Summa TIYINDA yuboriladi (1 so'm = 100 tiyin).
"""

import base64
import json
import logging

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

logger = logging.getLogger('wallet.payme')

PROVIDER_CODE = 'payme'

# Payme hujjatidagi xato kodlari
ERROR_AUTH = -32504
ERROR_PARSE = -32700
ERROR_METHOD = -32601
ERROR_AMOUNT = -31001
ERROR_ORDER = -31050            # buyurtma topilmadi / yaroqsiz
ERROR_TX_NOT_FOUND = -31003
ERROR_CANNOT_PERFORM = -31008
ERROR_CANNOT_CANCEL = -31007

# Payme tranzaksiya holatlari
STATE_WAITING = 1
STATE_PAID = 2
STATE_CANCELLED = -1
STATE_REFUNDED = -2


def _provider():
    from management.models import PaymentProvider

    return PaymentProvider.objects.filter(code=PROVIDER_CODE, is_active=True).first()


def _error(request_id, code, message, data=None):
    payload = {'code': code, 'message': {'uz': message, 'ru': message, 'en': message}}
    if data:
        payload['data'] = data
    return JsonResponse({'jsonrpc': '2.0', 'id': request_id, 'error': payload})


def _ok(request_id, result):
    return JsonResponse({'jsonrpc': '2.0', 'id': request_id, 'result': result})


def _authorized(request, provider) -> bool:
    """`Authorization: Basic base64(Paycom:<KALIT>)` tekshiriladi.

    Kalit panelda saqlanadi (Sozlamalar > To'lov tizimlari). U bo'lmasa
    endpoint hech kimni qabul qilmaydi — ochiq qoldirilgan endpoint har
    kimga hamyon to'ldirish imkonini berardi.
    """
    if not provider or not provider.secret_key:
        return False

    header = request.headers.get('Authorization', '')
    if not header.startswith('Basic '):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode('utf-8')
    except (ValueError, UnicodeDecodeError):
        return False

    login, _, key = decoded.partition(':')
    return login == 'Paycom' and key == provider.secret_key


def _find_order(params):
    """So'rovdagi `account` bo'yicha buyurtmani topadi."""
    from .models import PaymentOrder

    account = params.get('account') or {}
    raw = account.get('order_id') or account.get('order') or ''
    if not str(raw).isdigit():
        return None
    return PaymentOrder.objects.filter(pk=int(raw)).select_related(
        'provider', 'user').first()


def _order_state(order):
    if order.state == order.State.PAID:
        return STATE_PAID
    if order.state == order.State.CANCELLED:
        return STATE_CANCELLED
    if order.state == order.State.REFUNDED:
        return STATE_REFUNDED
    return STATE_WAITING


def _now_ms():
    return int(timezone.now().timestamp() * 1000)


@csrf_exempt
def merchant(request):
    """POST /api/payments/payme/ — barcha JSON-RPC metodlari shu yerda."""
    if request.method != 'POST':
        return _error(None, ERROR_METHOD, 'Faqat POST')

    provider = _provider()
    if not _authorized(request, provider):
        return _error(None, ERROR_AUTH, 'Ruxsat berilmadi')

    try:
        body = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return _error(None, ERROR_PARSE, "So'rovni o'qib bo'lmadi")

    request_id = body.get('id')
    method = body.get('method')
    params = body.get('params') or {}

    handler = {
        'CheckPerformTransaction': _check_perform,
        'CreateTransaction': _create,
        'PerformTransaction': _perform,
        'CancelTransaction': _cancel,
        'CheckTransaction': _check,
        'GetStatement': _statement,
    }.get(method)

    if handler is None:
        return _error(request_id, ERROR_METHOD, f'Metod topilmadi: {method}')

    try:
        return handler(request_id, params, provider)
    except Exception as error:      # noqa: BLE001 — javob HAR DOIM qaytishi kerak
        logger.exception('Payme %s xatosi: %s', method, error)
        return _error(request_id, ERROR_CANNOT_PERFORM, 'Ichki xato')


def _check_perform(request_id, params, provider):
    """Bunday buyurtma bormi va summa to'g'rimi."""
    order = _find_order(params)
    if order is None or not order.is_open:
        return _error(request_id, ERROR_ORDER, 'Buyurtma topilmadi',
                      data='order_id')
    if int(params.get('amount') or 0) != order.amount_tiyin:
        return _error(request_id, ERROR_AMOUNT, "Summa mos kelmadi")
    return _ok(request_id, {'allow': True})


def _create(request_id, params, provider):
    """Tranzaksiya ochadi. Takroriy so'rovda o'sha javob qaytadi."""
    from .models import PaymentOrder

    tx_id = str(params.get('id') or '')
    existing = PaymentOrder.objects.filter(external_id=tx_id).first()
    if existing:
        # Payme so'rovni takrorlashi mumkin — yangi tranzaksiya ochilmaydi
        if existing.state != PaymentOrder.State.WAITING:
            return _error(request_id, ERROR_CANNOT_PERFORM,
                          'Tranzaksiya holati mos emas')
        return _ok(request_id, {
            'create_time': existing.create_time,
            'transaction': str(existing.pk),
            'state': STATE_WAITING,
        })

    order = _find_order(params)
    if order is None or not order.is_open:
        return _error(request_id, ERROR_ORDER, 'Buyurtma topilmadi', data='order_id')
    if int(params.get('amount') or 0) != order.amount_tiyin:
        return _error(request_id, ERROR_AMOUNT, 'Summa mos kelmadi')

    order.external_id = tx_id[:64]
    order.state = PaymentOrder.State.WAITING
    order.create_time = int(params.get('time') or _now_ms())
    order.save(update_fields=['external_id', 'state', 'create_time', 'updated_at'])

    return _ok(request_id, {
        'create_time': order.create_time,
        'transaction': str(order.pk),
        'state': STATE_WAITING,
    })


def _perform(request_id, params, provider):
    """Pulni hamyonga qo'shadi. Takroriy so'rovda summa ikki marta qo'shilmaydi."""
    from .models import PaymentOrder

    order = PaymentOrder.objects.filter(external_id=str(params.get('id') or '')).first()
    if order is None:
        return _error(request_id, ERROR_TX_NOT_FOUND, 'Tranzaksiya topilmadi')

    if order.state == PaymentOrder.State.PAID:
        return _ok(request_id, {
            'transaction': str(order.pk),
            'perform_time': order.perform_time,
            'state': STATE_PAID,
        })

    if order.state != PaymentOrder.State.WAITING:
        return _error(request_id, ERROR_CANNOT_PERFORM, 'Tranzaksiya bekor qilingan')

    order.mark_paid(perform_time=_now_ms())
    return _ok(request_id, {
        'transaction': str(order.pk),
        'perform_time': order.perform_time,
        'state': STATE_PAID,
    })


def _cancel(request_id, params, provider):
    """Bekor qiladi. To'langan bo'lsa mablag' hamyondan qaytarib olinadi."""
    from .models import PaymentOrder

    order = PaymentOrder.objects.filter(external_id=str(params.get('id') or '')).first()
    if order is None:
        return _error(request_id, ERROR_TX_NOT_FOUND, 'Tranzaksiya topilmadi')

    if order.state in (PaymentOrder.State.CANCELLED, PaymentOrder.State.REFUNDED):
        return _ok(request_id, {
            'transaction': str(order.pk),
            'cancel_time': order.cancel_time,
            'state': _order_state(order),
        })

    order.cancel(reason=params.get('reason'), cancel_time=_now_ms())
    return _ok(request_id, {
        'transaction': str(order.pk),
        'cancel_time': order.cancel_time,
        'state': _order_state(order),
    })


def _check(request_id, params, provider):
    from .models import PaymentOrder

    order = PaymentOrder.objects.filter(external_id=str(params.get('id') or '')).first()
    if order is None:
        return _error(request_id, ERROR_TX_NOT_FOUND, 'Tranzaksiya topilmadi')

    return _ok(request_id, {
        'create_time': order.create_time,
        'perform_time': order.perform_time,
        'cancel_time': order.cancel_time,
        'transaction': str(order.pk),
        'state': _order_state(order),
        'reason': order.cancel_reason,
    })


def _statement(request_id, params, provider):
    """Davr bo'yicha to'lovlar — Payme buni solishtirish uchun so'raydi."""
    from .models import PaymentOrder

    start = int(params.get('from') or 0)
    end = int(params.get('to') or 0)
    rows = PaymentOrder.objects.filter(
        provider=provider, create_time__gte=start, create_time__lte=end,
    ).exclude(external_id='')

    return _ok(request_id, {'transactions': [
        {
            'id': row.external_id,
            'time': row.create_time,
            'amount': row.amount_tiyin,
            'account': {'order_id': str(row.pk)},
            'create_time': row.create_time,
            'perform_time': row.perform_time,
            'cancel_time': row.cancel_time,
            'transaction': str(row.pk),
            'state': _order_state(row),
            'reason': row.cancel_reason,
        }
        for row in rows
    ]})


def checkout_url(order):
    """Ilova ochadigan havola.

    Payme parametrlarni base64 ichida kutadi:
    `m=<merchant>;ac.order_id=<id>;a=<tiyin>`.
    """
    provider = order.provider
    raw = f'm={provider.merchant_id};ac.order_id={order.pk};a={order.amount_tiyin}'
    encoded = base64.b64encode(raw.encode('utf-8')).decode('ascii')
    base = provider.endpoint_url or 'https://checkout.paycom.uz'
    return f'{base.rstrip("/")}/{encoded}'
