# -*- coding: utf-8 -*-
"""Bank hisob raqamini yagona ko'rinishga keltirish.

O'zbekistonda hisob raqami 20 xonali bo'ladi va bo'laklarga bo'lib
yoziladi — har bo'lakning o'z ma'nosi bor:

    20208  000  5  00123612  001
      │     │   │     │       └── bank filiali kodi (3)
      │     │   │     └────────── mijoz hisobi (8)
      │     │   └──────────────── nazorat raqami (1)
      │     └──────────────────── valyuta kodi (3)
      └────────────────────────── balans hisobvarag'i (5)

Bo'laklarsiz 20 ta raqam ketma-ket yozilsa xato ko'rinmaydi — bitta raqam
tushib qolgani ham, ortiqchasi ham bilinmaydi. To'lov esa noto'g'ri hisobga
ketsa uni qaytarish oylab davom etadi.

Kelishuv (telefon raqamlaridagidek):
  • BAZADA — faqat raqamlar: `20208000500123612001`;
  • EKRANDA — `account` filtri: `20208 000 5 00123612 001`;
  • KIRITISHDA — maydon yozilgani sari bo'laklarga ajratadi (app.js).
"""

ACCOUNT_LENGTH = 20

# Bo'laklarning uzunligi: balans hisobvarag'i, valyuta, nazorat, hisob, filial
GROUPS = (5, 3, 1, 8, 3)


def digits_only(value) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def normalize_account(value) -> str:
    """Bazada saqlanadigan ko'rinish — faqat raqamlar."""
    return digits_only(value)


def format_account(value) -> str:
    """`20208000500123612001` -> `20208 000 5 00123612 001`.

    To'liqsiz raqam ham bo'laklanadi: yetishmagan joyi bo'sh qoladi va xato
    ko'zga tashlanadi. Raqamsiz qiymat o'z holicha qaytadi.
    """
    return _split(value, GROUPS)


# ── STIR (soliq to'lovchining identifikatsiya raqami) ────────────
# 9 xonali, uch bo'lakda yoziladi: `305 123 456`. Hisob raqamidagidek
# sabab: raqamlar ketma-ket bo'lsa xato ko'rinmaydi.
INN_LENGTH = 9
INN_GROUPS = (3, 3, 3)


def normalize_inn(value) -> str:
    """Bazada saqlanadigan ko'rinish — faqat raqamlar."""
    return digits_only(value)


def format_inn(value) -> str:
    """`305123456` -> `305 123 456`."""
    return _split(value, INN_GROUPS)


def _split(value, groups) -> str:
    """Raqamlarni berilgan uzunlikdagi bo'laklarga ajratadi.

    To'liqsiz qiymat ham bo'laklanadi — yetishmagan joyi bo'sh qoladi.
    Bo'laklarga sig'magani oxiriga qo'shiladi: hech narsa yo'qolmaydi va
    ortiqcha raqam ko'rinib turadi.
    """
    text = str(value or '').strip()
    digits = digits_only(text)
    if not digits:
        return text

    parts = []
    start = 0
    for size in groups:
        chunk = digits[start:start + size]
        if not chunk:
            break
        parts.append(chunk)
        start += size
    if start < len(digits):
        parts.append(digits[start:])
    return ' '.join(parts)
