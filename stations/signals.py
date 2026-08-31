"""Station/Connector/StationAmenity DB'da o'zgarganda barcha ulangan mobil
ilova klientlariga darhol xabar beradi (WebSocket orqali) — foydalanuvchi
xaritani qo'lda yangilamasa ham stansiya holati (bo'sh/band) real vaqtda
ko'rinadi. Signal'lar barcha o'zgarish manbalarini (dashboard, OCPP charger,
mock sessiya) bitta joydan ushlaydi — har bir view/consumer'da alohida
broadcast chaqirish shart emas."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Station, Connector, StationAmenity


def broadcast_stations_changed():
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)('stations_updates', {'type': 'stations.changed'})


@receiver([post_save, post_delete], sender=Station)
def on_station_changed(sender, **kwargs):
    broadcast_stations_changed()


@receiver([post_save, post_delete], sender=Connector)
def on_connector_changed(sender, instance, **kwargs):
    # Ulagich holati o'zgarsa, stansiyaning umumiy holati ham unga mos bo'lishi
    # kerak (bo'sh/band/ishlamayapti) — aks holda xaritada stansiya "bo'sh"
    # ko'rinib, ichidagi ulagichlarning hammasi band bo'lib qolardi.
    from .services import sync_station_status

    station = getattr(instance, 'station', None)
    if station is not None:
        # sync_station_status o'zi Station'ni saqlaydi va u ham broadcast qiladi;
        # o'zgarish bo'lmasa ortiqcha yozuv ham, ortiqcha xabar ham yuborilmaydi.
        station.refresh_from_db()
        if sync_station_status(station):
            return
    broadcast_stations_changed()


@receiver([post_save, post_delete], sender=StationAmenity)
def on_amenity_changed(sender, **kwargs):
    broadcast_stations_changed()
