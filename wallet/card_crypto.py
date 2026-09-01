# -*- coding: utf-8 -*-
"""Karta tokenini shifrlab saqlash.

Provayder bergan token — PUL YECHISH huquqi. U qo'lga tushsa,
hujumchi bizning merchant hisobimiz orqali foydalanuvchining kartasidan
pul yecha oladi. Boshqa maxfiy qiymatlardan farqi shunda: to'lov
kaliti bitta va uni almashtirsa bo'ladi, kartalar esa minglab va
ularning har biri alohida odamning puli.

Shuning uchun ular bazada OCHIQ saqlanmaydi. Baza nusxasi oshkor
bo'lsa (zaxira fayli, o'g'irlangan disk, xato sozlangan huquq) tokenlar
o'qib bo'lmaydigan holda qoladi.

KALIT `SECRET_KEY` dan olinadi. Bu mukammal yechim emas — ikkalasi bir
joyda bo'lsa himoya ham birga yo'qoladi. Lekin u eng ko'p uchraydigan
holatni yopadi: baza nusxasi kalitsiz tarqalishi. To'liq ajratish uchun
alohida kalit boshqaruvi kerak va u alohida ish.
"""
import base64
import hashlib

from django.conf import settings


def _key() -> bytes:
    """`SECRET_KEY` dan Fernet uchun kalit hosil qiladi.

    To'g'ridan-to'g'ri ishlatib bo'lmaydi: Fernet aynan 32 bayt,
    base64 bilan kodlangan kalit kutadi.
    """
    digest = hashlib.sha256(f'card-token:{settings.SECRET_KEY}'.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet():
    from cryptography.fernet import Fernet

    return Fernet(_key())


def encrypt(token: str) -> str:
    if not token:
        return ''
    return _fernet().encrypt(token.encode('utf-8')).decode('ascii')


def decrypt(blob: str) -> str:
    """Shifrni ochadi. Ochib bo'lmasa bo'sh satr.

    Xato TASHLANMAYDI: `SECRET_KEY` almashtirilgan bo'lsa eski tokenlar
    o'qilmaydi va bu kutilgan holat. Butun sahifa qulashi o'rniga karta
    "ishlamaydi" deb ko'rsatilgani ma'qul — foydalanuvchi uni qaytadan
    biriktiradi.
    """
    if not blob:
        return ''
    try:
        return _fernet().decrypt(blob.encode('ascii')).decode('utf-8')
    except Exception:       # noqa: BLE001 — buzuq yoki begona shifr
        return ''


def mask_pan(pan: str) -> str:
    """Karta raqamining ko'rsatiladigan ko'rinishi: `**** 1234`.

    To'liq raqam HECH QAYERDA saqlanmaydi — bu funksiya faqat
    foydalanuvchi o'z kartasini tanib olishi uchun.
    """
    digits = ''.join(ch for ch in str(pan or '') if ch.isdigit())
    return f'**** {digits[-4:]}' if len(digits) >= 4 else '****'


def brand_of(pan: str) -> str:
    """Karta turi — birinchi raqamlar bo'yicha.

    O'zbekistonda `8600` — Uzcard, `9860` — Humo. Qolganlari
    xalqaro tizimlar.
    """
    digits = ''.join(ch for ch in str(pan or '') if ch.isdigit())
    if digits.startswith('8600'):
        return 'uzcard'
    if digits.startswith('9860'):
        return 'humo'
    if digits.startswith('4'):
        return 'visa'
    if digits.startswith('5'):
        return 'mastercard'
    return 'other'
