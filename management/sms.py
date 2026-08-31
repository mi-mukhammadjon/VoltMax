# -*- coding: utf-8 -*-
"""SMS yuborish — hozircha Eskiz.uz orqali.

Nima uchun kerak: kirish kodlari faqat Telegram orqali ketardi.
Telegrami yo'q odam ilovaga UMUMAN kira olmasdi — ro'yxatdan ham
o'tolmasdi. Buni operator ko'rmaydi ham: odam shunchaki ilovani
o'chiradi.

Bundan tashqari bitta kanal — bitta nuqta: Telegram Gateway hisobida
mablag' tugasa yoki xizmat ishlamay qolsa, hech kim kira olmaydi.

Shuning uchun kod ikki kanal bilan ketadi (`accounts/otp_delivery.py`):
avval Telegram (arzon), ishlamasa SMS.

TOKEN HAQIDA: Eskiz login/parolni bir marta so'raydi va JWT beradi,
u taxminan 30 kun yashaydi. Token bazada saqlanadi — har SMS uchun
qaytadan kirish sekin va keraksiz. Muddati tugasa avtomatik yangilanadi.

MUHIM: Eskiz'da ishlab chiqarish rejimida matn shabloni OLDINDAN
tasdiqlanishi kerak. Tasdiqlanmagan matn "yuborildi" deb qaytadi-yu,
abonentga yetib bormaydi — shuning uchun yuborilgan matn o'zgartirilsa
Eskiz kabinetida ham yangilash kerak.
"""
import logging

import requests

logger = logging.getLogger('management.sms')

BASE_URL = 'https://notify.eskiz.uz/api'
REQUEST_TIMEOUT = 15

# Token shu muddatdan keyin yangilanadi (Eskiz 30 kun beradi, biz
# chetiga bormaymiz)
TOKEN_TTL_DAYS = 25


class SmsError(Exception):
    """SMS yuborilmadi. Sabab matni operatorga ko'rsatiladi."""


def _settings():
    from management.models import SiteSettings

    return SiteSettings.load()


def is_configured(settings_obj=None) -> bool:
    settings_obj = settings_obj or _settings()
    return bool(settings_obj.sms_enabled
                and settings_obj.sms_login
                and settings_obj.sms_password)


def normalize(phone: str) -> str:
    """Eskiz raqamni `998901234567` ko'rinishida kutadi — `+` siz."""
    return ''.join(ch for ch in str(phone or '') if ch.isdigit())


# ── Token ────────────────────────────────────────────────────────
def _login(settings_obj) -> str:
    """Login/parol bilan yangi token oladi."""
    try:
        response = requests.post(
            f'{BASE_URL}/auth/login',
            data={'email': settings_obj.sms_login,
                  'password': settings_obj.sms_password},
            timeout=REQUEST_TIMEOUT,
        )
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise SmsError(f"SMS xizmatiga ulanib bo'lmadi: {error}") from error

    token = (payload.get('data') or {}).get('token')
    if not token:
        message = payload.get('message') or payload.get('error') or "noma'lum xato"
        raise SmsError(f'SMS xizmati kirishni rad etdi: {message}')
    return token


def get_token(force_new=False) -> str:
    """Amaldagi tokenni qaytaradi, kerak bo'lsa yangilaydi."""
    from datetime import timedelta

    from django.utils import timezone

    settings_obj = _settings()
    if not settings_obj.sms_login or not settings_obj.sms_password:
        raise SmsError('SMS shlyuzi sozlanmagan (Sozlamalar > Xavfsizlik)')

    fresh_enough = (
        settings_obj.sms_token
        and settings_obj.sms_token_at
        and timezone.now() - settings_obj.sms_token_at < timedelta(days=TOKEN_TTL_DAYS)
    )
    if fresh_enough and not force_new:
        return settings_obj.sms_token

    token = _login(settings_obj)
    settings_obj.sms_token = token
    settings_obj.sms_token_at = timezone.now()
    settings_obj.save(update_fields=['sms_token', 'sms_token_at'])
    return token


# ── Yuborish ─────────────────────────────────────────────────────
def _post_message(token, phone, text, sender):
    return requests.post(
        f'{BASE_URL}/message/sms/send',
        headers={'Authorization': f'Bearer {token}'},
        data={'mobile_phone': phone, 'message': text, 'from': sender},
        timeout=REQUEST_TIMEOUT,
    )


def send(phone: str, text: str) -> dict:
    """Bitta SMS yuboradi. Muvaffaqiyatsizlikda `SmsError` tashlaydi."""
    settings_obj = _settings()
    if not is_configured(settings_obj):
        raise SmsError('SMS shlyuzi yoqilmagan yoki sozlanmagan')

    number = normalize(phone)
    if len(number) < 9:
        raise SmsError(f"Telefon raqami noto'g'ri: {phone}")

    sender = settings_obj.sms_sender or '4546'

    try:
        response = _post_message(get_token(), number, text, sender)
        # Token muddati tugagan bo'lsa bir marta qayta urinamiz: bu eng
        # ko'p uchraydigan xato va foydalanuvchi buni sezmasligi kerak
        if response.status_code in (401, 403):
            response = _post_message(get_token(force_new=True), number, text, sender)
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise SmsError(f"SMS yuborib bo'lmadi: {error}") from error

    status = str(payload.get('status') or '').lower()
    if response.status_code >= 400 or status in ('error', 'failed'):
        message = payload.get('message') or payload.get('error') or response.text[:120]
        raise SmsError(f'SMS xizmati rad etdi: {message}')

    logger.info('SMS yuborildi: %s', number)
    return payload


def balance():
    """Hisobdagi qoldiq. Xizmat javob bermasa `None`.

    Tizim holati sahifasida ko'rsatiladi: mablag' tugasa SMS jimgina
    ketmay qo'yadi va buni faqat foydalanuvchi kira olmaganda bilib
    qolardik.
    """
    try:
        response = requests.get(
            f'{BASE_URL}/user/get-limit',
            headers={'Authorization': f'Bearer {get_token()}'},
            timeout=REQUEST_TIMEOUT,
        )
        payload = response.json()
    except (SmsError, requests.RequestException, ValueError):
        return None

    data = payload.get('data') or {}
    # Eskiz javobida maydon nomi hisob turiga qarab farq qiladi
    for key in ('balance', 'limit', 'amount'):
        if key in data:
            try:
                return int(float(data[key]))
            except (TypeError, ValueError):
                return None
    return None
