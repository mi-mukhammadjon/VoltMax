"""ASGI config for voltmax project.

Oddiy HTTP so'rovlar (REST API, dashboard) va OCPP charger WebSocket
ulanishlari shu bitta ASGI ilova orqali xizmat qiladi.
"""

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402

# django.setup() dan keyin, lekin ocpp_gateway.routing import qilinishidan oldin
# chaqirilishi shart — aks holda app registry hali to'liq yuklanmagan bo'ladi.
django_asgi_app = get_asgi_application()

from ocpp_gateway.routing import websocket_urlpatterns as ocpp_websocket_urlpatterns  # noqa: E402
from stations.routing import websocket_urlpatterns as stations_websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': URLRouter(ocpp_websocket_urlpatterns + stations_websocket_urlpatterns),
})
