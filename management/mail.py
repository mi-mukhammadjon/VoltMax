# -*- coding: utf-8 -*-
"""Elektron pochta — sozlamalari PANELDA turadi.

Nima uchun muhit o'zgaruvchisi emas: pochta sozlamasi vaqti-vaqti bilan
o'zgaradi (parol almashadi, provayder ko'chadi) va buning uchun serverga
kirish talab qilinmasligi kerak. To'lov kalitlari va OTP shlyuzi
allaqachon shu qoidada.

Uch joyda ishlatiladi:

  * korporativ hujjatlar — hisob-faktura, dalolatnoma, shartnoma;
  * administratorga ogohlantirish — tizimda muammo chiqqanda;
  * xodim parolini tiklash.

Har uchala holatda ham yuborish MUVAFFAQIYATSIZ bo'lishi mumkin va bu
asosiy ishni to'xtatmasligi kerak: hisob-faktura pochta ishlamagani
uchun yaratilmay qolmasin.
"""
import logging
from email.utils import parseaddr

logger = logging.getLogger('management.mail')

DEFAULT_TIMEOUT = 20


class MailError(Exception):
    """Xat yuborilmadi. Sabab matni operatorga ko'rsatiladi."""


def _settings():
    from management.models import SiteSettings

    return SiteSettings.load()


def is_configured(settings_obj=None) -> bool:
    settings_obj = settings_obj or _settings()
    return bool(settings_obj.mail_enabled
                and settings_obj.mail_host
                and settings_obj.mail_from)


def valid_address(value) -> bool:
    """Manzil yuborishga yaroqlimi — juda sodda tekshiruv.

    To'liq tekshirish ma'nosiz: manzil haqiqatan ishlashini faqat xat
    yuborib bilish mumkin.
    """
    _name, address = parseaddr(value or '')
    return '@' in address and '.' in address.split('@')[-1]


def _connection(settings_obj):
    """Sozlamadagi qiymatlar bilan SMTP ulanishi."""
    from django.core.mail import get_connection

    return get_connection(
        backend='django.core.mail.backends.smtp.EmailBackend',
        host=settings_obj.mail_host,
        port=settings_obj.mail_port or 587,
        username=settings_obj.mail_user or None,
        password=settings_obj.mail_password or None,
        use_tls=settings_obj.mail_use_tls,
        use_ssl=not settings_obj.mail_use_tls and settings_obj.mail_port == 465,
        timeout=DEFAULT_TIMEOUT,
    )


def send(to, subject, body, attachments=None, settings_obj=None):
    """Xat yuboradi. Muvaffaqiyatsizlikda `MailError` tashlaydi.

    `attachments` — `(fayl_nomi, baytlar, tur)` uchliklari ro'yxati.
    """
    from django.core.mail import EmailMessage

    settings_obj = settings_obj or _settings()
    if not is_configured(settings_obj):
        raise MailError('Pochta sozlanmagan (Sozlamalar > Bildirishnoma)')

    recipients = [address for address in (to if isinstance(to, (list, tuple)) else [to])
                  if valid_address(address)]
    if not recipients:
        raise MailError(f"Yaroqli pochta manzili yo'q: {to}")

    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings_obj.mail_from,
        to=recipients,
        connection=_connection(settings_obj),
    )
    for name, content, mimetype in (attachments or []):
        message.attach(name, content, mimetype)

    try:
        sent = message.send(fail_silently=False)
    except Exception as error:      # noqa: BLE001 — SMTP xatolari xilma-xil
        raise MailError(f"Xat yuborib bo'lmadi: {error}") from error

    if not sent:
        raise MailError('Pochta serveri xatni qabul qilmadi')

    logger.info('Xat yuborildi: %s — %s', ', '.join(recipients), subject)
    return sent


def try_send(to, subject, body, attachments=None):
    """Yuboradi, lekin XATO TASHLAMAYDI. `(yuborildimi, sabab)`.

    Asosiy ish pochtaga bog'liq bo'lmasligi kerak: hisob-faktura
    pochta ishlamagani uchun yaratilmay qolmasin.
    """
    try:
        send(to, subject, body, attachments)
        return True, ''
    except MailError as error:
        logger.warning('Xat yuborilmadi (%s): %s', to, error)
        return False, str(error)
