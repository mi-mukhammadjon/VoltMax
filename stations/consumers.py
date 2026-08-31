"""Mobil ilova shu yerga ulanib, Station/Connector o'zgarganda darhol xabar
oladi. Xabar to'liq ma'lumotni o'zida saqlamaydi — faqat "nimadir o'zgardi,
qayta so'ra" signali (haqiqiy ma'lumot REST /api/stations/ orqali olinadi,
shu bilan ikkita joyda serializatsiya mantiqini takrorlamaymiz)."""

import json

from channels.generic.websocket import AsyncWebsocketConsumer


class StationUpdatesConsumer(AsyncWebsocketConsumer):
    GROUP = 'stations_updates'

    async def connect(self):
        await self.channel_layer.group_add(self.GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP, self.channel_name)

    async def stations_changed(self, event):
        await self.send(text_data=json.dumps({'type': 'stations_changed'}))
