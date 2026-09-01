# -*- coding: utf-8 -*-
"""Foydalanuvchi avatarini har joyda bir xil ko'rsatish.

Avatar bir necha sahifada kerak: yuqori panelda, mijozlar ro'yxatida,
xodimlar ro'yxatida, mijoz sahifasida. Har joyda alohida yozilsa ular
asta-sekin bir-biridan farq qila boshlaydi — biri doira, biri kvadrat,
biri bosh harfsiz.

Rasm yo'q bo'lsa bosh harflar ko'rsatiladi: bo'sh doira ma'nosiz
bo'lardi, ism esa har doim bor.
"""
from django import template

register = template.Library()

# Ruxsat etilgan o'lchamlar — CSS da shu nomlar bilan
SIZES = {'xs', 'sm', 'md', 'lg'}


@register.inclusion_tag('dashboard/_avatar.html')
def avatar(user, size='sm'):
    """{% avatar row.user 'md' %}

    N+1 so'rovga e'tibor bering: ro'yxatlarda `select_related('profile')`
    qilinmasa, har qator uchun alohida so'rov ketadi.
    """
    from accounts.models import avatar_url_for, initials_for

    return {
        'url': avatar_url_for(user),
        'initials': initials_for(user),
        'size': size if size in SIZES else 'sm',
    }
