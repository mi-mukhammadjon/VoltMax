"""Stansiya/ulagich holatini sinxronlashtirish.

Muammo: `Station.status`, `Connector.status` va `ChargingSession.status` uch xil
joyda saqlanadi. Ular bir-biriga mos kelmay qolishi mumkin — masalan charger
qayta yuklangan, sessiya xato bilan tugagan, yoki panel orqali qo'lda
o'zgartirilgan. Bu modul ularni yagona haqiqatga keltiradi:

    sessiya (haqiqat manbai) → ulagich holati → stansiya holati
"""

from stations.models import Connector, Station


def sync_station_status(station: Station) -> bool:
    """Stansiya holatini ulagichlaridan hisoblab qo'yadi.

    Qoida: kamida bitta ulagich bo'sh bo'lsa — stansiya bo'sh; hech biri
    bo'sh bo'lmasa, lekin zaryadlanayotgani bo'lsa — band; hammasi nosoz
    bo'lsa — ishlamayapti. Ulagichlari yo'q stansiya qo'lda qo'yilgan
    holatida qoldiriladi.

    O'zgarish bo'lganda True qaytaradi (va saqlaydi).
    """
    connectors = list(station.connectors.all())

    # Charger biriktirilgan bo'lsa, aloqa holati hamma narsadan ustun turadi:
    # qurilma javob bermayotgan bo'lsa, ulagichlar bazada "bo'sh" ko'rinsa ham
    # stansiya aslida ishlamaydi. Panelda holat qo'lda tanlanmaydi — aynan
    # shuning uchun bu yer yagona haqiqat manbai bo'lishi kerak.
    if station.ocpp_id and not station.is_online:
        new_status = Station.Status.OFFLINE
        if station.status == new_status:
            return False
        station.status = new_status
        station.save(update_fields=['status'])
        return True

    if not connectors:
        return False

    statuses = {c.status for c in connectors}
    if Connector.Status.AVAILABLE in statuses:
        new_status = Station.Status.AVAILABLE
    # Bron qilingan ulagich jismonan soz, lekin band — stansiya "ishlamayapti"
    # emas, "band" bo'lishi kerak.
    elif statuses & {Connector.Status.CHARGING, Connector.Status.RESERVED}:
        new_status = Station.Status.BUSY
    else:
        new_status = Station.Status.OFFLINE

    if station.status == new_status:
        return False

    station.status = new_status
    # .save() — signal orqali mobil ilovaga real-vaqt xabar ketadi
    station.save(update_fields=['status'])
    return True


def sync_connector_from_sessions(connector: Connector) -> bool:
    """Ulagich holatini undagi sessiyalarga qarab to'g'rilaydi.

    Ikki xil nomuvofiqlik bo'lishi mumkin:
      * ulagich "zaryadlanmoqda", lekin faol sessiya yo'q → bo'shatiladi;
      * faol sessiya bor, lekin ulagich "bo'sh" → band qilinadi.

    Nosoz (offline) ulagichga tegilmaydi — u qurilma darajasidagi holat.
    """
    from sessions_app.models import ChargingSession

    # Nosoz va bron qilingan holatlar qurilma darajasida boshqariladi —
    # sessiyalarga qarab o'zgartirilmaydi.
    if connector.status in (Connector.Status.OFFLINE, Connector.Status.RESERVED):
        return False

    has_active = ChargingSession.objects.filter(
        connector=connector, status=ChargingSession.Status.CHARGING
    ).exists()

    if has_active and connector.status != Connector.Status.CHARGING:
        connector.status = Connector.Status.CHARGING
        connector.save(update_fields=['status'])
        return True

    if not has_active and connector.status == Connector.Status.CHARGING:
        connector.status = Connector.Status.AVAILABLE
        connector.charging_percent = None
        connector.parking_started_at = None
        connector.save(update_fields=['status', 'charging_percent', 'parking_started_at'])
        return True

    return False


def sync_all() -> dict:
    """Butun tarmoqni sinxronlaydi. Panel'dagi "Holatni sinxronlash" tugmasi
    va kerak bo'lsa davriy vazifa uchun."""
    fixed_connectors = 0
    fixed_stations = 0

    for station in Station.objects.prefetch_related('connectors'):
        for connector in station.connectors.all():
            if sync_connector_from_sessions(connector):
                fixed_connectors += 1
        station.refresh_from_db()
        if sync_station_status(station):
            fixed_stations += 1

    return {'connectors': fixed_connectors, 'stations': fixed_stations}
