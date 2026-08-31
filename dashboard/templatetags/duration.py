"""Sekundlarni o'qiladigan davomiylikka aylantiruvchi shablon filtri.

Django'ning `timesince` filtri faqat sana bilan ishlaydi va "0 daqiqa" kabi
qisqa oraliqlarni yaxshi ko'rsatmaydi. Sessiya davomiyligi esa ko'pincha
daqiqalar bilan o'lchanadi, shuning uchun alohida filtr.

    {{ session.elapsed_seconds|duration }}   ->  1 soat 24 daq
"""

from django import template

register = template.Library()


@register.filter(name='duration')
def duration(value):
    try:
        total = int(value)
    except (TypeError, ValueError):
        return value
    if total < 0:
        total = 0

    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)

    if hours:
        # Soatlar bo'lsa soniyalar ortiqcha aniqlik — ular tashlab yuboriladi
        return f'{hours} soat {minutes} daq' if minutes else f'{hours} soat'
    if minutes:
        return f'{minutes} daq {seconds} s' if seconds else f'{minutes} daq'
    return f'{seconds} soniya'
