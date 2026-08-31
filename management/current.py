# -*- coding: utf-8 -*-
"""Sozlamalarni bitta so'rov davomida bir marta o'qish.

`SiteSettings.load()` juda ko'p joyda chaqiriladi: har stansiyaning narxi,
har sessiyaning tarifi, har sahifaning konteksti. Stansiyalar ro'yxatida u
14 marta takrorlanardi — bir xil qatorni o'n to'rt marta o'qish.

Ilgari yozuv XOTIRADA 5 daqiqa saqlanardi va bu jiddiy muammo tug'dirgan:
server bir nechta jarayonda ishlaydi, saqlash faqat o'z nusxasini
yangilardi, qolganlari esa eski qiymatni ko'rsatib turardi.

Bu yerdagi kesh boshqacha — u faqat BITTA SO'ROV davom etguncha yashaydi:

  * so'rov boshida bo'sh, oxirida tashlanadi (`SettingsCacheMiddleware`);
  * `save()` uni darhol bekor qiladi, ya'ni saqlagandan keyin o'sha
    so'rovda yangi qiymat ko'rinadi;
  * boshqa jarayon o'zgartirsa, keyingi so'rov uni darrov ko'radi —
    kesh so'rovdan uzoq yashamaydi.

`ContextVar` ishlatiladi: server ASGI'da (Daphne) ishlaydi va bir jarayonda
bir nechta so'rov parallel bajariladi. Oddiy global o'zgaruvchi ularning
ma'lumotini aralashtirib yuborardi.

SO'ROVDAN TASHQARIDA — davriy vazifalar va OCPP ulanishlari — o'rtada
tozalaydigan hech kim yo'q: charger soatlab ulangan turadi, ishchi esa
uzluksiz aylanadi. Ular eski qiymat bilan qolib ketmasligi uchun kesh
qisqa muddatdan keyin o'z-o'zidan eskiradi. Ya'ni «qat'iy rejim»ni
yoqqandan keyin u eng ko'pi bilan shu muddatdan so'ng amal qiladi.
"""

import time
from contextvars import ContextVar

# So'rovdan tashqarida keshning eng uzun umri (soniya)
TTL = 30

_settings = ContextVar('voltmax_site_settings', default=None)


def get_cached():
    entry = _settings.get()
    if entry is None:
        return None

    stamp, value = entry
    if time.monotonic() - stamp > TTL:
        clear_cached()
        return None
    return value


def set_cached(value):
    _settings.set((time.monotonic(), value))


def clear_cached():
    _settings.set(None)


class SettingsCacheMiddleware:
    """So'rov boshida keshni tozalaydi.

    Oxirida ham tozalanadi: ba'zi serverlar oqimni (thread) qayta
    ishlatadi va eski qiymat keyingi so'rovga o'tib ketishi mumkin edi.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        clear_cached()
        try:
            return self.get_response(request)
        finally:
            clear_cached()
