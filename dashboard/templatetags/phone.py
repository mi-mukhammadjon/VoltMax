"""Telefon raqamini yagona ko'rinishda chiqarish uchun shablon filtri.

Bazada raqam kanonik holda turadi (`+998950995510`), ekranda esa o'qishga
qulay bo'lgani ko'rinadi:

    {{ company.contact_phone|phone }} -> +998 (95) 099-55-10
"""

from django import template

from dashboard.phones import format_phone

register = template.Library()


@register.filter(name='phone')
def phone(value):
    """Raqamni formatlaydi.

    Mobil foydalanuvchining logini — raqamning o'zi (`998901234567`),
    shuning uchun filtr login maydonlariga ham qo'llanadi. Raqam bo'lmagan
    qiymat (xodim logini, masalan `admin`) o'zgarishsiz qaytadi, bo'sh
    qiymat esa chiziqcha bo'ladi — bo'sh katakcha "ma'lumot yo'q" ekanini
    bildirmaydi.
    """
    formatted = format_phone(value)
    return formatted or '—'
