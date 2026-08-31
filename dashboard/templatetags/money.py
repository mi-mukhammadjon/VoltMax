"""Pul summalarini yagona ko'rinishda chiqarish uchun shablon filtri.

Ilgari panel uch xil ko'rinishdan foydalanardi: `intcomma` (123,000),
xom son (123000) va `toLocaleString` natijasi. Endi hamma joyda bitta format:

    123 000.00

Ming ajratgichi — uzuluvchi bo'lmagan bo'shliq (U+00A0), shunda summa
qator oxirida ikkiga bo'linib ketmaydi. Kasr ajratgichi — nuqta.
"""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()

NBSP = ' '


@register.filter(name='som')
def som(value):
    """{{ amount|som }} -> 123 000.00

    Qiymatni o'qib bo'lmasa (None, bo'sh matn) — 0.00 qaytaradi, chunki
    pul maydonida bo'sh joy qolgani xato ko'rinadi.
    """
    if value in (None, ''):
        return '0.00'
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value

    formatted = f'{amount:,.2f}'          # 123,000.00
    return formatted.replace(',', NBSP)   # 123 000.00


def format_som(value) -> str:
    """Python kodidan (xabarlar, tranzaksiya tavsiflari, buyruq chiqishi)
    chaqirish uchun — shablon filtri bilan bir xil natija beradi."""
    return som(value)


@register.filter(name='num')
def num(value, places=2):
    """{{ value|num:2 }} -> 14.50 · {{ value|num:0 }} -> 400

    Nima uchun `floatformat` emas: loyiha `uz` lokalida ishlaydi va Django
    `floatformat` o'sha lokalning o'nlik ajratgichini qo'yadi — natijada
    kuchlanish "398,4" bo'lib, pul esa "398 400.00" bo'lib chiqardi.
    Bitta sahifada ikki xil ajratgich texnik ma'lumotda chalkashlik tug'diradi.

    Bu filtr pul filtri bilan bir xil qoidada ishlaydi: o'nlik — nuqta,
    minglik — uzuluvchi bo'lmagan bo'shliq.
    """
    if value in (None, ''):
        return '—'
    try:
        amount = Decimal(str(value))
        digits = int(places)
    except (InvalidOperation, TypeError, ValueError):
        return value

    formatted = f'{amount:,.{digits}f}'   # 1,234.50
    return formatted.replace(',', NBSP)   # 1 234.50
