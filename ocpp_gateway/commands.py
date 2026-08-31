"""Sinxron Django kodidan (masalan dashboard view'lari) charger'ga buyruq
yuborish uchun yordamchi funksiyalar. Natija kutilmaydi (fire-and-forget) —
charger buyruqni bajarib, StatusNotification/StartTransaction/StopTransaction
orqali natijani o'z vaqtida qaytaradi va bu odatdagidek consumer tomonidan
DB'ga yoziladi."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def _send(ocpp_id: str, action: str, payload: dict):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        raise RuntimeError('CHANNEL_LAYERS sozlanmagan')
    async_to_sync(channel_layer.group_send)(f'ocpp_{ocpp_id}', {
        'type': 'ocpp.command',
        'action': action,
        'payload': payload,
    })


def remote_start_transaction(ocpp_id: str, ocpp_connector_id: int, id_tag: str = 'DASHBOARD'):
    _send(ocpp_id, 'RemoteStartTransaction', {'connectorId': ocpp_connector_id, 'idTag': id_tag})


def remote_stop_transaction(ocpp_id: str, transaction_id: int):
    _send(ocpp_id, 'RemoteStopTransaction', {'transactionId': transaction_id})


def unlock_connector(ocpp_id: str, ocpp_connector_id: int):
    _send(ocpp_id, 'UnlockConnector', {'connectorId': ocpp_connector_id})


def change_availability(ocpp_id: str, ocpp_connector_id: int, operative: bool):
    """Ulagichni qurilmaning O'ZIDA xizmatdan chiqaradi/qaytaradi.

    Panelda holatni o'zgartirish faqat bazaga yozadi — charger bu haqda
    bilmaydi va RFID karta bilan mahalliy zaryadlashni qabul qilaveradi.
    Haqiqiy to'sish uchun OCPP ChangeAvailability yuborilishi shart.

    Charger javob sifatida StatusNotification yuboradi va bizdagi holat
    consumers.py orqali avtomatik yangilanadi.
    """
    _send(ocpp_id, 'ChangeAvailability', {
        'connectorId': ocpp_connector_id,
        'type': 'Operative' if operative else 'Inoperative',
    })


def trigger_status_notification(ocpp_id: str, ocpp_connector_id: int = 0):
    """Chargerdan hozirgi holatini qayta yuborishni so'raydi (OCPP 1.6
    TriggerMessage). Shu orqali "Sinxronlash" bazani taxmin qilmasdan,
    qurilmaning o'zidan haqiqiy holatni oladi.

    connectorId=0 — barcha ulagichlar bo'yicha.
    """
    payload = {'requestedMessage': 'StatusNotification'}
    if ocpp_connector_id:
        payload['connectorId'] = ocpp_connector_id
    _send(ocpp_id, 'TriggerMessage', payload)


def get_configuration(ocpp_id: str, keys: list | None = None):
    """Chargerdan sozlamalarini so'raydi.

    `keys` berilmasa charger BARCHA kalitlarini qaytaradi — panelda odatda
    shu kerak. Javob CALLRESULT sifatida keladi va consumer uni
    `ChargerConfiguration` jadvaliga yozadi (fire-and-forget emas, lekin
    javob ham shu yerda kutilmaydi).
    """
    payload = {'key': keys} if keys else {}
    _send(ocpp_id, 'GetConfiguration', payload)


def change_configuration(ocpp_id: str, key: str, value: str):
    """Chargerdagi bitta sozlamani o'zgartiradi.

    Charger javobida `Accepted`, `Rejected`, `RebootRequired` yoki
    `NotSupported` qaytaradi — natija jurnalga yoziladi.
    """
    _send(ocpp_id, 'ChangeConfiguration', {'key': key, 'value': str(value)})


def reset(ocpp_id: str, hard: bool = False):
    """Qurilmani qayta ishga tushiradi.

    `Soft` — dasturiy qayta ishga tushirish (ketayotgan tranzaksiyalar
    to'g'ri yakunlanadi), `Hard` — quvvatni uzib qayta yoqishga teng.
    """
    _send(ocpp_id, 'Reset', {'type': 'Hard' if hard else 'Soft'})


def clear_cache(ocpp_id: str):
    """Chargerdagi avtorizatsiya keshini tozalaydi (eski RFID ruxsatlari)."""
    _send(ocpp_id, 'ClearCache', {})


# ── Bron: ulagichni qurilma darajasida ushlab turish ─────────────────

def reserve_now(ocpp_id: str, ocpp_connector_id: int, reservation_id: int,
                id_tag: str, expiry_iso: str):
    """Ulagichni bron egasi uchun ushlab turadi.

    Muddati tugaguncha boshqa karta bilan zaryadlash boshlanmaydi — bizning
    bazamizdagi bron esa buni ta'minlay olmaydi, chunki charger u haqda
    bilmaydi.
    """
    _send(ocpp_id, 'ReserveNow', {
        'connectorId': ocpp_connector_id,
        'expiryDate': expiry_iso,
        'idTag': id_tag,
        'reservationId': reservation_id,
    })


def cancel_reservation(ocpp_id: str, reservation_id: int):
    _send(ocpp_id, 'CancelReservation', {'reservationId': reservation_id})


# ── Quvvat chegarasi (smart charging) ────────────────────────────────

def set_charging_profile(ocpp_id: str, ocpp_connector_id: int, limit_kw: float):
    """Ulagichdagi maksimal quvvatni cheklaydi.

    Kerak bo'ladigan holat: bitta tarmoq nuqtasida bir necha charger bo'lsa,
    hammasi to'liq quvvatda ishlasa avtomat o'chib qoladi. Chegara `W` da
    beriladi (`chargingRateUnit: 'W'`), chunki hamma qurilma `A` ni
    qo'llab-quvvatlamaydi.
    """
    _send(ocpp_id, 'SetChargingProfile', {
        'connectorId': ocpp_connector_id,
        'csChargingProfiles': {
            'chargingProfileId': ocpp_connector_id,
            'stackLevel': 0,
            # TxDefaultProfile — ushbu ulagichdagi BARCHA sessiyalarga
            # qo'llanadi (TxProfile faqat ketayotganiga tegishli bo'lardi)
            'chargingProfilePurpose': 'TxDefaultProfile',
            'chargingProfileKind': 'Absolute',
            'chargingSchedule': {
                'chargingRateUnit': 'W',
                'chargingSchedulePeriod': [
                    {'startPeriod': 0, 'limit': round(limit_kw * 1000)},
                ],
            },
        },
    })


def clear_charging_profile(ocpp_id: str, ocpp_connector_id: int):
    """Quvvat chegarasini olib tashlaydi."""
    _send(ocpp_id, 'ClearChargingProfile', {'connectorId': ocpp_connector_id})


# ── RFID: qurilmadagi mahalliy ro'yxat ───────────────────────────────

def get_local_list_version(ocpp_id: str):
    """Chargerdagi karta ro'yxatining versiyasini so'raydi."""
    _send(ocpp_id, 'GetLocalListVersion', {})


def send_local_list(ocpp_id: str, version: int, cards: list, full: bool = True):
    """Kartalar ro'yxatini qurilmaga yuklaydi.

    Nima uchun: internet uzilganda charger serverga Authorize yubora olmaydi
    va o'zidagi ro'yxatga tayanadi. Ro'yxat bo'lmasa — yo hech kim zaryadlay
    olmaydi, yo hamma zaryadlay oladi (sozlamaga qarab).

    `cards` — [{'idTag': ..., 'status': 'Accepted'|'Blocked'|'Expired'}, ...]
    """
    _send(ocpp_id, 'SendLocalList', {
        'listVersion': version,
        'updateType': 'Full' if full else 'Differential',
        'localAuthorizationList': [
            {'idTag': c['idTag'], 'idTagInfo': {'status': c['status']}} for c in cards
        ],
    })


# ── Proshivka va diagnostika ─────────────────────────────────────────

def update_firmware(ocpp_id: str, location: str, retrieve_iso: str):
    """Qurilmaga yangi proshivkani yuklab olishni buyuradi.

    `location` — proshivka fayliga to'liq havola (HTTP/FTP). Faylni biz
    bermaymiz — u ishlab chiqaruvchining serverida yoki operatorning
    faylida turadi. Jarayon FirmwareStatusNotification orqali kuzatiladi.
    """
    _send(ocpp_id, 'UpdateFirmware', {'location': location, 'retrieveDate': retrieve_iso})


def get_diagnostics(ocpp_id: str, upload_location: str):
    """Qurilmadan diagnostika faylini so'raydi.

    `upload_location` — charger faylni YUKLAYDIGAN manzil (FTP/HTTP PUT).
    Fayl bizga emas, o'sha manzilga boradi — shuning uchun operator uni
    o'zi tayyorlaydi.
    """
    _send(ocpp_id, 'GetDiagnostics', {'location': upload_location})
