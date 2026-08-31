"""Telegram Gateway (https://gateway.telegram.org) — OTP kodlarini SMS o'rniga
Telegram orqali yuborish. Bot yaratish yoki foydalanuvchi botni "Start" bosishi shart
emas — Telegram bu raqamni to'g'ridan-to'g'ri o'z tizimi orqali topib yuboradi."""

import requests
import urllib3.util.connection as urllib3_cn
from django.conf import settings

# Ushbu muhitda gatewayapi.telegram.org'ning IPv6 manziliga ulanish jim tarzda
# osilib qolib, ~20s dan keyingina IPv4'ga qaytadi (har bir so'rovni sekinlashtiradi).
# urllib3'ni faqat IPv4 ishlatishga majburlab, shu kutishni butunlay yo'q qilamiz.
urllib3_cn.HAS_IPV6 = False

BASE_URL = 'https://gatewayapi.telegram.org'
REQUEST_TIMEOUT = 10


class TelegramGatewayError(Exception):
    pass


def get_token() -> str:
    """Ishlatiladigan token: avval panel, keyin server sozlamasi.

    Panel ustun turadi, chunki uni almashtirish uchun serverga kirish
    kerak emas — to'lov kalitlari bilan bir xil qoida.
    """
    from management.models import SiteSettings

    try:
        panel_token = SiteSettings.load().otp_gateway_token
    except Exception:       # noqa: BLE001 — migratsiyalardan oldin ham ishlasin
        panel_token = ''
    return panel_token or settings.TELEGRAM_GATEWAY_TOKEN


def _call(method: str, **params) -> dict:
    token = get_token()
    if not token:
        raise TelegramGatewayError(
            "OTP shlyuzi kaliti sozlanmagan (Sozlamalar > Xavfsizlik)")

    try:
        resp = requests.post(
            f'{BASE_URL}/{method}',
            headers={'Authorization': f'Bearer {token}'},
            json=params,
            timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise TelegramGatewayError(f"Telegram Gateway'ga ulanib bo'lmadi: {exc}") from exc

    if not data.get('ok'):
        raise TelegramGatewayError(data.get('error') or "Noma'lum xatolik")
    return data['result']


def send_verification_code(phone: str, code: str) -> dict:
    """Tayyor (o'zimiz generatsiya qilgan) kodni berilgan telefon raqamiga yuboradi.
    `phone` E.164 formatda bo'lishi kerak (masalan +998901234567).

    Avval checkSendAbility chaqiriladi — muvaffaqiyatli bo'lsa, shu request_id orqali
    keyingi yuborish bepul hisoblanadi (Telegram Gateway'ning tavsiya etilgan oqimi)."""
    request_id = None
    try:
        ability = _call('checkSendAbility', phone_number=phone)
        request_id = ability.get('request_id')
    except TelegramGatewayError:
        pass  # bepul yuborish imkoni yo'q — baribir pullik yuborishga urinamiz

    params = {'phone_number': phone, 'code': code, 'ttl': 300}
    if request_id:
        params['request_id'] = request_id
    return _call('sendVerificationMessage', **params)
