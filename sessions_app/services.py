"""Sessiyani majburan to'xtatish — panel va API uchun yagona yo'l.

Muhim: ilgari ikkita yarim yechim bor edi —
  * `session_force_stop` faqat DB'da yopardi (charger zaryadlashda davom etardi);
  * `connector_remote_stop` faqat chargerga buyruq yubordi (DB'da sessiya
    "zaryadlanmoqda" bo'lib osilib qolardi).

Bu funksiya ikkalasini bitta amalda bajaradi va natijani aniq qaytaradi,
shunda operator chargerga buyruq yetib bordimi yoki yo'qmi — bilib turadi.
"""

from dataclasses import dataclass

from ocpp_gateway import commands as ocpp_commands
from stations.services import sync_station_status


@dataclass
class StopResult:
    """To'xtatish natijasi. `charger_notified=False` bo'lsa, jismoniy qurilma
    hali ham quvvat berayotgan bo'lishi mumkin — operatorga aytilishi shart."""

    stopped: bool
    charger_notified: bool
    warning: str = ''
    final_cost: int = 0


def force_stop_session(session, *, actor: str = 'panel') -> StopResult:
    """Sessiyani to'xtatadi: avval haqiqiy chargerga RemoteStopTransaction
    yuboradi, so'ng DB'da yakunlaydi (hisob-kitob, hamyon, ulagichni bo'shatish).

    Charger keyinroq o'zining StopTransaction xabarini yuborsa, u
    `_stop_live_session` ichida `status != CHARGING` tekshiruvi bilan
    to'silad — ya'ni ikki marta pul yechilmaydi.
    """
    if session.status != session.Status.CHARGING:
        return StopResult(stopped=False, charger_notified=False, warning='Sessiya allaqachon tugagan')

    station = session.station
    charger_notified = False
    warning = ''

    # Faqat haqiqiy (OCPP) sessiyani chargerga uzatish mantiqiy;
    # simulyatsiya sessiyalarida jismoniy qurilma yo'q.
    if session.is_live and station.ocpp_id:
        if station.is_online:
            try:
                ocpp_commands.remote_stop_transaction(station.ocpp_id, session.id)
                charger_notified = True
            except Exception as exc:  # channel layer ishlamayotgan bo'lishi mumkin
                warning = f"Chargerga buyruq yuborilmadi ({exc}). Qurilmani joyida tekshiring."
        else:
            warning = (
                "Charger oflayn — to'xtatish buyrug'i yetkazilmadi. "
                "Sessiya hisobda yopildi, lekin qurilmani joyida tekshirish kerak."
            )
    elif session.is_live and not station.ocpp_id:
        warning = "Stansiyaga OCPP ID berilmagan — chargerga buyruq yuborib bo'lmadi."

    session.stop()
    session.refresh_from_db()

    # Ulagich bo'shagach stansiya holati ham yangilanishi kerak
    station.refresh_from_db()
    sync_station_status(station)

    return StopResult(
        stopped=True,
        charger_notified=charger_notified,
        warning=warning,
        final_cost=session.final_cost or 0,
    )


def vehicle_snapshot(user):
    """Foydalanuvchining standart mashinasi va uning "suratga olingan" nomi.

    Sessiyaga havola ham, matn ham yoziladi: havola mashina o'chirilsa
    yo'qoladi, matn esa tarixda qolib, panelda VIN bo'yicha qidirish
    imkonini beradi.

    Qaytaradi: (vehicle | None, label, vin)
    """
    from accounts.models import Vehicle

    vehicle = Vehicle.objects.filter(user=user).order_by('-is_default', '-created_at').first()
    if vehicle is None:
        return None, '', ''
    return vehicle, vehicle.title[:150], vehicle.vin
