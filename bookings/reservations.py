"""Bronni QURILMA darajasida ushlab turish (OCPP ReserveNow).

Muammo: bron faqat bizning bazamizda bo'lsa, charger u haqda bilmaydi va
belgilangan vaqtda kelgan boshqa odam ulagichdan bemalol foydalanadi. Bron
egasi esa kelib bo'sh joy topmaydi.

`ReserveNow` chargerga "shu ulagich shu kartaga, shu vaqtgacha atalgan" deb
aytadi — qurilma boshqa kartani rad etadi.

Cheklovlar (ataylab):
  * bron ulagichga biriktirilgan bo'lishi kerak — charger "istalgan ulagich"ni
    ushlab tura olmaydi;
  * charger onlayn bo'lishi kerak, aks holda buyruq yetib bormaydi;
  * bron egasi mobil ilova foydalanuvchisi bo'lgani uchun `APP-<id>` idTag'i
    ishlatiladi — RFID kartasi shart emas.
"""

import logging
from datetime import timedelta, timezone as dt_timezone

from ocpp_gateway import commands as ocpp_commands

logger = logging.getLogger('bookings')


def _can_reserve(booking) -> bool:
    station = booking.station
    return bool(
        booking.connector_id
        and booking.connector.ocpp_connector_id
        and station.ocpp_id
        and station.is_online
    )


def hold_connector(booking) -> bool:
    """Bron bo'yicha ulagichni qurilmada ushlab turadi. Yuborilgan bo'lsa True.

    `reservationId` sifatida bronning o'z `id`si ishlatiladi — alohida
    raqamlagich saqlash shart emas va bekor qilishda ham shu raqam kerak.
    """
    if not _can_reserve(booking):
        return False

    # OCPP vaqtni UTC'da, `Z` bilan kutadi
    expiry = booking.scheduled_at + timedelta(minutes=booking.duration_minutes)
    try:
        ocpp_commands.reserve_now(
            booking.station.ocpp_id,
            booking.connector.ocpp_connector_id,
            reservation_id=booking.id,
            id_tag=f'APP-{booking.user_id}',
            expiry_iso=expiry.astimezone(dt_timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        )
    except Exception:  # noqa: BLE001 — bron baribir bazada qoladi
        logger.exception('ReserveNow yuborilmadi (booking=%s)', booking.id)
        return False

    booking.ocpp_reservation_id = booking.id
    booking.save(update_fields=['ocpp_reservation_id'])
    return True


def release_connector(booking) -> bool:
    """Qurilmadagi bronni bekor qiladi. Yuborilgan bo'lsa True."""
    if not booking.ocpp_reservation_id or not booking.station.ocpp_id:
        return False
    if not booking.station.is_online:
        # Charger oflayn: bron muddati tugagach o'zi bo'shaydi, shuning uchun
        # bu holat xato emas — lekin bizdagi belgi tozalanadi.
        booking.ocpp_reservation_id = None
        booking.save(update_fields=['ocpp_reservation_id'])
        return False

    try:
        ocpp_commands.cancel_reservation(
            booking.station.ocpp_id, booking.ocpp_reservation_id
        )
    except Exception:  # noqa: BLE001
        logger.exception('CancelReservation yuborilmadi (booking=%s)', booking.id)
        return False

    booking.ocpp_reservation_id = None
    booking.save(update_fields=['ocpp_reservation_id'])
    return True


def expire_stale(now=None, grace_minutes=15):
    """Muddati o'tgan bronlarni yopadi va ulagichni bo'shatadi.

    Mijoz kelmasa bron abadiy ochiq qolardi: ulagich qurilmada band
    bo'lib turardi va boshqa hech kim undan foydalana olmasdi. Charger
    o'zi ham bronni bekor qiladi, lekin faqat `expiryDate` kelganda —
    biz esa bazadagi holatni ham tozalashimiz kerak, aks holda
    foydalanuvchi "bronim bor" deb kutib qolardi.

    `grace_minutes` — kechikish uchun beriladigan vaqt: mijoz bir necha
    daqiqa kechikishi odatiy hol.

    Qaytaradi: {'closed': n, 'released': n}
    """
    from django.utils import timezone

    from .models import Booking

    now = now or timezone.now()
    result = {'closed': 0, 'released': 0}

    rows = Booking.objects.filter(
        status=Booking.Status.CONFIRMED
    ).select_related('station', 'connector')

    for booking in rows:
        deadline = (booking.scheduled_at
                    + timedelta(minutes=booking.duration_minutes + grace_minutes))
        if deadline > now:
            continue

        # Bron vaqtida sessiya boshlangan bo'lsa — bu bajarilgan bron,
        # muddati o'tgani uchun bekor qilinmaydi
        from sessions_app.models import ChargingSession

        used = ChargingSession.objects.filter(
            user_id=booking.user_id, station_id=booking.station_id,
            started_at__gte=booking.scheduled_at,
            started_at__lte=deadline,
        ).exists()

        if release_connector(booking):
            result['released'] += 1

        booking.status = (Booking.Status.COMPLETED if used
                          else Booking.Status.CANCELLED)
        booking.save(update_fields=['status'])
        result['closed'] += 1

    return result
