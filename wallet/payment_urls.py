"""To'lov tizimlari chaqiradigan manzillar (webhook).

Bular ochiq endpoint'lar — ularga to'lov tizimining serveri murojaat
qiladi, foydalanuvchi emas. Himoya autentifikatsiya orqali: Payme'da
`Basic` sarlavha, Click'da `sign_string` (MD5). Kalitlar panelda
saqlanadi (Sozlamalar > To'lov tizimlari).
"""

from django.urls import path

from . import click, payme

app_name = 'payments'

urlpatterns = [
    path('payme/', payme.merchant, name='payme'),
    path('click/prepare/', click.prepare, name='click_prepare'),
    path('click/complete/', click.complete, name='click_complete'),
]
