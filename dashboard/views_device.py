"""Qurilma bilan bevosita ishlash — sozlamalarni o'qish/yozish va boshqaruv.

Bu amallar OCPP orqali chargerning O'ZIGA boradi. Ularning hammasi
asinxron: buyruq yuboriladi, javob esa consumer'ga keladi va u ma'lumotni
bazaga yozadi. Shuning uchun view "so'raldi" deb xabar beradi, natija esa
bir necha soniyadan keyin sahifada paydo bo'ladi.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

from ocpp_gateway import commands as ocpp_commands
from stations.models import ChargerLog, Station

from .decorators import staff_required
from .redirects import safe_redirect


def _back(request, station):
    return safe_redirect(request, f'/stations/{station.id}/')


def _require_online(request, station) -> bool:
    """Chargerga buyruq yuborish mumkinmi. Mumkin bo'lmasa sababini aytadi."""
    if not station.ocpp_id:
        messages.error(request, "Stansiyaga OCPP ID berilmagan — qurilma bilan aloqa yo'q")
        return False
    if not station.is_online:
        messages.error(request, 'Charger oflayn — buyruq yetkazib bo\'lmaydi')
        return False
    return True


@staff_required
def device_read_config(request, pk):
    """Chargerdan barcha sozlamalarini so'raydi (GetConfiguration)."""
    station = get_object_or_404(Station, pk=pk)
    if request.method == 'POST' and _require_online(request, station):
        try:
            ocpp_commands.get_configuration(station.ocpp_id)
            messages.success(
                request,
                "Sozlamalar so'raldi — javob kelishi bilan ro'yxat yangilanadi "
                '(bir necha soniya)',
            )
        except Exception as exc:  # noqa: BLE001 — buyruq yuborishdagi har qanday nosozlik
            messages.error(request, f'Buyruq yuborilmadi: {exc}')
    return _back(request, station)


@staff_required
def device_write_config(request, pk):
    """Chargerdagi bitta sozlamani o'zgartiradi (ChangeConfiguration)."""
    station = get_object_or_404(Station, pk=pk)
    if request.method != 'POST':
        return _back(request, station)

    key = (request.POST.get('key') or '').strip()
    value = (request.POST.get('value') or '').strip()
    if not key:
        messages.error(request, 'Sozlama kaliti ko\'rsatilmagan')
        return _back(request, station)

    if _require_online(request, station):
        try:
            ocpp_commands.change_configuration(station.ocpp_id, key, value)
            messages.success(
                request,
                f'"{key}" uchun yangi qiymat yuborildi. Qurilma javobi jurnalda '
                "ko'rinadi — ba'zi sozlamalar qayta yuklashni talab qiladi.",
            )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f'Buyruq yuborilmadi: {exc}')
    return _back(request, station)


@staff_required
def device_reset(request, pk):
    """Qurilmani qayta ishga tushiradi (Reset).

    `Soft` — ketayotgan tranzaksiyalar to'g'ri yakunlanadi; `Hard` — quvvatni
    uzib yoqishga teng va sessiya yarim uzilib qolishi mumkin.
    """
    station = get_object_or_404(Station, pk=pk)
    if request.method != 'POST':
        return _back(request, station)

    hard = request.POST.get('mode') == 'hard'
    if _require_online(request, station):
        try:
            ocpp_commands.reset(station.ocpp_id, hard=hard)
            ChargerLog.objects.create(
                station=station, kind=ChargerLog.Kind.OTHER, action='Reset',
                summary=f"{'Hard' if hard else 'Soft'} reset yuborildi "
                        f'({request.user.username})',
                payload={'type': 'Hard' if hard else 'Soft'},
            )
            messages.success(
                request,
                f"{'Hard' if hard else 'Soft'} qayta ishga tushirish buyrug'i yuborildi",
            )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f'Buyruq yuborilmadi: {exc}')
    return _back(request, station)


@staff_required
def device_clear_cache(request, pk):
    """Chargerdagi avtorizatsiya keshini tozalaydi (eski RFID ruxsatlari)."""
    station = get_object_or_404(Station, pk=pk)
    if request.method == 'POST' and _require_online(request, station):
        try:
            ocpp_commands.clear_cache(station.ocpp_id)
            messages.success(request, 'Avtorizatsiya keshini tozalash buyrug\'i yuborildi')
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f'Buyruq yuborilmadi: {exc}')
    return _back(request, station)


@staff_required
def device_power_limit(request, pk, connector_pk):
    """Ulagichdagi maksimal quvvatni cheklaydi (SetChargingProfile).

    Kerak bo'ladigan holat: bitta tarmoq nuqtasida bir necha charger bo'lsa,
    hammasi to'liq quvvatda ishlaganda kirish avtomati o'chib qoladi.
    """
    from stations.models import Connector

    connector = get_object_or_404(Connector.objects.select_related('station'),
                                  pk=connector_pk, station_id=pk)
    station = connector.station
    if request.method != 'POST':
        return _back(request, station)

    raw = (request.POST.get('limit_kw') or '').strip()
    if raw:
        try:
            limit = int(raw)
        except ValueError:
            messages.error(request, 'Chegara butun son bo\'lishi kerak')
            return _back(request, station)
        if limit < 1 or limit > connector.power_kw:
            messages.error(
                request,
                f'Chegara 1 dan {connector.power_kw} kVt gacha bo\'lishi kerak '
                f'(ulagich quvvati)',
            )
            return _back(request, station)
    else:
        limit = None

    if not connector.ocpp_connector_id:
        messages.error(request, "Ulagichga OCPP raqami berilmagan — chegara yuborib bo'lmaydi")
        return _back(request, station)
    if not _require_online(request, station):
        return _back(request, station)

    try:
        if limit is None:
            ocpp_commands.clear_charging_profile(station.ocpp_id, connector.ocpp_connector_id)
            messages.success(request, f'{connector.label}: quvvat chegarasi olib tashlandi')
        else:
            ocpp_commands.set_charging_profile(
                station.ocpp_id, connector.ocpp_connector_id, limit)
            messages.success(request, f'{connector.label}: chegara {limit} kVt qilib yuborildi')
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f'Buyruq yuborilmadi: {exc}')
        return _back(request, station)

    connector.power_limit_kw = limit
    connector.save(update_fields=['power_limit_kw'])
    return _back(request, station)


@staff_required
def device_update_firmware(request, pk):
    """Qurilmaga yangi proshivkani yuklab olishni buyuradi (UpdateFirmware).

    Faylni biz bermaymiz — havola ishlab chiqaruvchining serveriga yoki
    operator joylagan faylga ishora qiladi. Jarayon FirmwareStatusNotification
    orqali kuzatiladi va pasportda ko'rinadi.
    """
    station = get_object_or_404(Station, pk=pk)
    if request.method != 'POST':
        return _back(request, station)

    location = (request.POST.get('location') or '').strip()
    if not location.startswith(('http://', 'https://', 'ftp://')):
        messages.error(request, "Proshivka havolasi http://, https:// yoki ftp:// bilan boshlanishi kerak")
        return _back(request, station)

    if _require_online(request, station):
        try:
            ocpp_commands.update_firmware(
                station.ocpp_id, location,
                retrieve_iso=timezone.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
            )
            ChargerLog.objects.create(
                station=station, kind=ChargerLog.Kind.FIRMWARE, action='UpdateFirmware',
                summary=f'Proshivka yangilash boshlandi ({request.user.username})',
                payload={'location': location},
            )
            messages.success(
                request,
                "Proshivka yuklab olish buyrug'i yuborildi — jarayon qurilma "
                'pasportida ko\'rinadi',
            )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f'Buyruq yuborilmadi: {exc}')
    return _back(request, station)


@staff_required
def device_get_diagnostics(request, pk):
    """Qurilmadan diagnostika faylini so'raydi (GetDiagnostics).

    Fayl BIZGA emas, ko'rsatilgan manzilga yuklanadi (charger o'zi jo'natadi),
    shuning uchun manzilni operator tayyorlaydi.
    """
    station = get_object_or_404(Station, pk=pk)
    if request.method != 'POST':
        return _back(request, station)

    location = (request.POST.get('location') or '').strip()
    if not location.startswith(('http://', 'https://', 'ftp://')):
        messages.error(request, 'Yuklash manzili http://, https:// yoki ftp:// bilan boshlanishi kerak')
        return _back(request, station)

    if _require_online(request, station):
        try:
            ocpp_commands.get_diagnostics(station.ocpp_id, location)
            messages.success(
                request,
                "Diagnostika so'raldi — qurilma faylni ko'rsatilgan manzilga yuklaydi",
            )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f'Buyruq yuborilmadi: {exc}')
    return _back(request, station)
