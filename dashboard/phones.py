# -*- coding: utf-8 -*-
"""Telefon raqamlarini yagona ko'rinishga keltirish.

Panelda raqam uch xil yozilardi: `+998901234567`, `90 123 45 67`,
`+998 90 123-45-67`. Bu qidiruvni ham buzardi (bir xil raqam ikki xil
yozilsa topilmasdi), hujjatlarda ham xunuk ko'rinardi.

Kelishuv:
  • BAZADA — kanonik ko'rinish: `+998950995510` (faqat `+` va raqamlar).
    Qidiruv shu ko'rinishda ishlaydi va nusxalar paydo bo'lmaydi.
  • EKRANDA — `phone` filtri: `+998 (95) 099-55-10`.
  • KIRITISHDA — maydonning o'zi yozilgani sari shu ko'rinishga soladi
    (app.js), lekin serverga baribir kanonik holda keladi.

O'zbekiston raqami 9 xonali bo'ladi va 998 kodi bilan yuritiladi. Boshqa
davlat raqami kiritilsa u shunchaki raqamlar ko'rinishida saqlanadi —
formatlash faqat 998 uchun qo'llanadi.
"""

UZ_CODE = '998'
UZ_LENGTH = 9      # operator kodi (2) + raqam (7)


def digits_only(value) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def normalize_phone(value) -> str:
    """Kiritilgan raqamni bazada saqlanadigan ko'rinishga keltiradi.

    `90 099 55 10`, `+998 (90) 099-55-10`, `998900995510` — hammasi
    `+998900995510` bo'ladi.
    """
    digits = digits_only(value)
    if not digits:
        return ''

    # 9 xonali raqam — mamlakat kodisiz kiritilgan
    if len(digits) == UZ_LENGTH:
        digits = UZ_CODE + digits
    # 8 bilan boshlangan eski yozuv: 8 90 ... → 998 90 ...
    elif len(digits) == UZ_LENGTH + 1 and digits.startswith('8'):
        digits = UZ_CODE + digits[1:]

    return '+' + digits


def format_phone(value) -> str:
    """`+998950995510` -> `+998 (95) 099-55-10`.

    O'zbekiston raqami bo'lmasa qiymat o'zgarishsiz qaytadi: chet el
    raqamini noto'g'ri bo'laklarga bo'lish uni o'qishni qiyinlashtirardi.
    """
    text = str(value or '').strip()
    if not text:
        return ''

    digits = digits_only(text)
    # Raqamsiz qiymat — xodimning logini (`admin`), o'zgartirilmaydi
    if not digits:
        return text

    if len(digits) == UZ_LENGTH:
        digits = UZ_CODE + digits

    # Boshqa har qanday qiymat — chet el raqami yoki umuman raqam emas
    # (panelga kiradigan xodimning logini) — o'z holicha qoladi
    if not digits.startswith(UZ_CODE) or len(digits) > len(UZ_CODE) + UZ_LENGTH:
        return text

    return _group(digits[len(UZ_CODE):])


def _group(body: str) -> str:
    """Raqam tanasini `(95) 099-55-10` ko'rinishida bo'laklarga ajratadi.

    Bazada to'liqsiz raqam ham uchraydi (ilgari maydon hech narsani
    tekshirmasdi). Bunday raqam ham SHU ko'rinishda chiqadi — yetishmagan
    joyi bo'sh qoladi va xato ko'zga tashlanadi. Raqam o'ylab topilmaydi:
    bor raqamlar o'z o'rnida turadi.
    """
    parts = [body[:2], body[2:5], body[5:7], body[7:9]]
    out = f'+{UZ_CODE}'
    if parts[0]:
        out += f' ({parts[0]})'
    if parts[1]:
        out += f' {parts[1]}'
    if parts[2]:
        out += f'-{parts[2]}'
    if parts[3]:
        out += f'-{parts[3]}'
    return out
