"""Bank hisob raqamini o'qishga qulay ko'rinishda chiqarish.

    {{ company.bank_account|account }} -> 20208 000 5 00123612 001
    {{ company.inn|inn }}             -> 305 123 456
"""

from django import template

from dashboard.banking import format_account, format_inn

register = template.Library()


@register.filter(name='account')
def account(value):
    """Raqamni bo'laklarga ajratadi. Bo'sh bo'lsa chiziqcha."""
    return format_account(value) or '—'


@register.filter(name='inn')
def inn(value):
    """STIR — uch bo'lakda. Bo'sh bo'lsa chiziqcha."""
    return format_inn(value) or '—'
