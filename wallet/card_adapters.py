# -*- coding: utf-8 -*-
"""Provayderlarga xos qism: Payme, Click va sinov uchun soxta adapter.

Har adapter to'rtta metodni bajaradi va boshqa hech narsani bilmaydi:
kartaning bazadagi yozuvi, hamyon, buyurtma — bularning hammasi
`wallet/cards.py` da. Shunda yangi provayder qo'shish bitta sinf yozish
bilan cheklanadi.

KARTA RAQAMI faqat `register` ga kiradi va provayderga uzatiladi.
Adapter uni saqlamaydi, qaytarmaydi va logga yozmaydi.

MUHIM: bu yerdagi Payme va Click adapterlari HUJJAT BO'YICHA yozilgan
va haqiqiy kabinetda hali sinalmagan. Ular ulanganda javob maydonlari
biroz farq qilishi mumkin — shuning uchun har javob ehtiyotkorlik
bilan o'qiladi va tushunarsiz javob ochiq xato beradi, jimgina
"muvaffaqiyat" emas.
"""
import logging

import requests

from .cards import CardError

logger = logging.getLogger('wallet.cards')

TIMEOUT = 20


class BaseAdapter:
    def __init__(self, provider):
        self.provider = provider

    # Har biri `dict` qaytaradi: `token`, `verify_ref`, `external_id`
    def register(self, pan: str, expiry: str) -> dict:
        raise NotImplementedError

    def send_code(self, card) -> None:
        raise NotImplementedError

    def verify(self, card, code: str) -> dict:
        raise NotImplementedError

    def charge(self, card, order) -> dict:
        raise NotImplementedError

    def remove(self, card) -> None:
        raise NotImplementedError


class PaymeCardAdapter(BaseAdapter):
    """Payme Subscribe API.

    Oqim: `cards.create` → `cards.get_verify_code` → `cards.verify`,
    keyin har to'lov uchun `receipts.create` + `receipts.pay`.

    Kalit `X-Auth: <merchant_id>` sarlavhasida, to'lov bosqichida esa
    `<merchant_id>:<secret_key>` ko'rinishida.
    """

    BASE_URL = 'https://checkout.paycom.uz/api'

    def _call(self, method: str, params: dict, *, with_key=False) -> dict:
        auth = self.provider.merchant_id
        if with_key:
            auth = f'{self.provider.merchant_id}:{self.provider.secret_key}'

        try:
            response = requests.post(
                self.provider.endpoint_url or self.BASE_URL,
                json={'method': method, 'params': params},
                headers={'X-Auth': auth},
                timeout=TIMEOUT,
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise CardError('To‘lov tizimiga ulanib bo‘lmadi') from error

        if 'error' in payload:
            message = (payload['error'] or {}).get('message') or 'noma’lum xato'
            if isinstance(message, dict):
                message = message.get('uz') or message.get('ru') or 'xato'
            error = CardError(str(message))
            # `-31300` oilasi — karta bilan bog'liq muammo: qayta
            # urinish yordam bermaydi
            code = (payload['error'] or {}).get('code')
            error.card_dead = code in (-31300, -31301, -31302)
            raise error

        return payload.get('result') or {}

    def register(self, pan, expiry):
        digits = ''.join(ch for ch in expiry if ch.isdigit())
        result = self._call('cards.create', {
            'card': {'number': pan, 'expire': digits},
            'save': True,
        })
        card = result.get('card') or {}
        return {'token': card.get('token', ''), 'verify_ref': ''}

    def send_code(self, card):
        self._call('cards.get_verify_code', {'token': card.token})

    def verify(self, card, code):
        result = self._call('cards.verify', {'token': card.token, 'code': code})
        return {'token': (result.get('card') or {}).get('token', card.token)}

    def charge(self, card, order):
        receipt = self._call('receipts.create', {
            # Payme tiyinda ishlaydi
            'amount': order.amount_tiyin,
            'account': {'order_id': str(order.pk)},
        }, with_key=True)

        receipt_id = (receipt.get('receipt') or {}).get('_id')
        if not receipt_id:
            raise CardError('To‘lov tizimi javobi tushunarsiz')

        self._call('receipts.pay', {'id': receipt_id, 'token': card.token},
                   with_key=True)
        return {'external_id': receipt_id}

    def remove(self, card):
        self._call('cards.remove', {'token': card.token})


class ClickCardAdapter(BaseAdapter):
    """Click Card Token API.

    Oqim: `card_token/request` → `card_token/verify` → `card_token/payment`.
    Imzo `merchant_user_id` va maxfiy kalit bilan hisoblanadi.
    """

    BASE_URL = 'https://api.click.uz/v2/merchant'

    def _headers(self):
        import hashlib
        import time

        stamp = str(int(time.time()))
        digest = hashlib.sha1(
            f'{stamp}{self.provider.secret_key}'.encode('utf-8')).hexdigest()
        merchant_user = ''
        for part in (self.provider.note or '').split():
            if part.startswith('merchant_user_id='):
                merchant_user = part.split('=', 1)[1]
        return {
            'Accept': 'application/json',
            'Auth': f'{merchant_user}:{digest}:{stamp}',
        }

    def _call(self, path: str, payload: dict, method='post') -> dict:
        url = f'{(self.provider.endpoint_url or self.BASE_URL).rstrip("/")}/{path}'
        try:
            request = requests.post if method == 'post' else requests.delete
            response = request(url, json=payload, headers=self._headers(),
                               timeout=TIMEOUT)
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            raise CardError('To‘lov tizimiga ulanib bo‘lmadi') from error

        code = data.get('error_code')
        if code not in (0, None):
            error = CardError(data.get('error_note') or 'To‘lov rad etildi')
            # Click'da manfiy kodlar karta muammosini bildiradi
            error.card_dead = code in (-5017, -5018)
            raise error
        return data

    def register(self, pan, expiry):
        digits = ''.join(ch for ch in expiry if ch.isdigit())
        data = self._call('card_token/request', {
            'service_id': int(self.provider.merchant_id or 0),
            'card_number': pan,
            'expire_date': digits,
            'temporary': 0,
        })
        return {'token': data.get('card_token', ''), 'verify_ref': ''}

    def send_code(self, card):
        # Click kodni `card_token/request` bosqichida yuboradi —
        # alohida so'rov yo'q
        return None

    def verify(self, card, code):
        data = self._call('card_token/verify', {
            'service_id': int(self.provider.merchant_id or 0),
            'card_token': card.token,
            'sms_code': code,
        })
        return {'token': data.get('card_token', card.token)}

    def charge(self, card, order):
        data = self._call('card_token/payment', {
            'service_id': int(self.provider.merchant_id or 0),
            'card_token': card.token,
            # Click so'mda ishlaydi
            'amount': order.amount,
            'transaction_parameter': str(order.pk),
        })
        return {'external_id': str(data.get('payment_id') or '')}

    def remove(self, card):
        self._call(
            f'card_token/{self.provider.merchant_id}/{card.token}', {},
            method='delete')


class FakeCardAdapter(BaseAdapter):
    """Sinov uchun: tarmoqqa chiqmaydi.

    Shartnoma va sinov kabineti bo'lmaganda ham butun oqimni yozish va
    tekshirish kerak. Bu adapter aynan shuning uchun — u sinovlarda va
    ishlab chiqish muhitida ishlatiladi.

    Ishlab chiqarishda U ISHLAMAYDI: kodi ro'yxatga faqat `DEBUG`
    rejimida qo'shiladi. Aks holda sozlashda adashib qo'yilsa, tizim
    "to'lov o'tdi" deb ko'rsatib, aslida pul yechilmasdi.
    """

    CODE = '000000'

    def register(self, pan, expiry):
        # Muddat haqiqiy adapterlardagi kabi tozalanadi: soxta adapter
        # ulardan boshqacha ishlasa, sinovlar yolg'on ishonch berardi
        digits = ''.join(ch for ch in expiry if ch.isdigit())
        return {'token': f'fake-{pan[-4:]}-{digits}', 'verify_ref': 'fake'}

    def send_code(self, card):
        return None

    def verify(self, card, code):
        if code != self.CODE:
            raise CardError('Kod noto‘g‘ri')
        return {'token': card.token}

    def charge(self, card, order):
        # `9999` bilan tugagan karta har doim rad etiladi — sinovlarda
        # xato yo'lini ham tekshirish kerak
        if card.masked_pan.endswith('9999'):
            error = CardError('Mablag‘ yetarli emas')
            error.card_dead = False
            raise error
        return {'external_id': f'fake-{order.pk}'}

    def remove(self, card):
        return None


def _build_adapters():
    from django.conf import settings

    table = {
        'payme': PaymeCardAdapter,
        'click': ClickCardAdapter,
    }
    if settings.DEBUG:
        table['fake'] = FakeCardAdapter
    return table


ADAPTERS = _build_adapters()
