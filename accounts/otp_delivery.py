# -*- coding: utf-8 -*-
"""Kirish kodini yetkazish — ikki kanal orqali.

Ilgari kod FAQAT Telegram Gateway orqali ketardi. Ikki muammo bor edi:

  * Telegrami yo'q odam ilovaga umuman kira olmasdi. Buni operator
    ko'rmaydi ham — odam shunchaki ilovani o'chiradi.
  * Bitta kanal — bitta nuqta. Hisobda mablag' tugasa yoki xizmat
    ishlamay qolsa, HECH KIM kira olmaydi.

Endi tartib shunday: avval Telegram (arzon va tez), u ishlamasa SMS.
Teskarisi emas: SMS har xabar uchun pul turadi, Telegram esa ko'pchilik
uchun bepul ishlaydi.

Qaysi kanal ishlaganini bilish MUHIM: "kod kelmadi" degan shikoyat
kelganda operator qayerga qarashni bilishi kerak. Shuning uchun natija
kodning o'zida saqlanadi (`OTPCode.sent_via`).
"""
import logging

logger = logging.getLogger('accounts.otp')

TELEGRAM = 'telegram'
SMS = 'sms'


class DeliveryError(Exception):
    """Hech qaysi kanal ishlamadi."""


def _try_telegram(phone, code):
    from accounts.telegram_gateway import TelegramGatewayError, send_verification_code

    try:
        send_verification_code('+' + phone, code)
        return None
    except TelegramGatewayError as error:
        return str(error)


def _try_sms(phone, code):
    from management import sms
    from management.models import SiteSettings

    if not sms.is_configured():
        return 'SMS shlyuzi sozlanmagan'

    settings_obj = SiteSettings.load()
    text = (settings_obj.sms_otp_text or '').strip() or DEFAULT_SMS_TEXT
    try:
        sms.send(phone, text.replace('{code}', code))
        return None
    except sms.SmsError as error:
        return str(error)


# Eskiz'da matn OLDINDAN tasdiqlanadi, shuning uchun standart matn
# sodda va o'zgarmas: tasdiqlangan shablondan chetga chiqilsa xabar
# "yuborildi" deb qaytadi-yu, abonentga yetib bormaydi.
DEFAULT_SMS_TEXT = 'VoltMax: kirish kodi {code}'


def deliver(phone: str, code: str):
    """Kodni yetkazadi. `(kanal, xatolar)` qaytaradi.

    `kanal` — ishlagan kanal nomi. Hech biri ishlamasa `DeliveryError`
    tashlanadi va ichida ikkala sabab bo'ladi: operator qaysi biri
    nima uchun ishlamaganini ko'rishi kerak.
    """
    problems = {}

    telegram_error = _try_telegram(phone, code)
    if telegram_error is None:
        return TELEGRAM, problems
    problems[TELEGRAM] = telegram_error

    sms_error = _try_sms(phone, code)
    if sms_error is None:
        logger.info('OTP SMS bilan yuborildi (Telegram: %s)', telegram_error)
        return SMS, problems
    problems[SMS] = sms_error

    raise DeliveryError('; '.join(f'{name}: {reason}'
                                  for name, reason in problems.items()))
