"""Pullik parkovka uchun davriy hisob-kitob.

Ilgari parkovka faqat sessiya tugaganda bir yo'la yechilardi. Bu ikki muammoni
tug'diradi:
  * avtomobil bir necha soat turib qolsa, hamyonda pul yetmay qolishi mumkin —
    lekin buni faqat oxirida bilib qolamiz;
  * foydalanuvchi ilovada summa o'sayotganini ko'radi, balans esa qimirlamaydi.

Endi `bill_parking()` davriy chaqiriladi va faqat YANGI to'plangan daqiqalarni
yechadi. `ChargingSession.parking_billed_minutes` hisoblangan daqiqalarni
saqlagani uchun amal takroran chaqirilsa ham ikki marta yechilmaydi.
"""

import logging

from django.db import transaction

from stations.models import Connector
from wallet.models import Transaction, WalletBalance

from .models import ChargingSession

logger = logging.getLogger('sessions_app')


def bill_parking() -> dict:
    """Parkovka rejimidagi barcha sessiyalardan yangi daqiqalar uchun pul yechadi.

    Qaytaradi: {'sessions': n, 'minutes': n, 'charged': n, 'unpaid': n}
    `unpaid` — hamyonda pul yetmagani uchun yechib bo'lmagan summa.
    """
    result = {'sessions': 0, 'minutes': 0, 'charged': 0, 'unpaid': 0}

    active = (
        ChargingSession.objects
        .filter(status=ChargingSession.Status.CHARGING, connector__isnull=False)
        .select_related('connector', 'station', 'user')
    )

    for session in active:
        connector = session.connector
        if connector is None or connector.status == Connector.Status.OFFLINE:
            continue
        if not connector.parking_mode:
            continue

        # Har chaqiruvda faqat oxirgi hisobdan keyingi to'liq daqiqalar olinadi.
        # Aniq hisob qulf ostida qayta bajariladi (pastdagi `_charge`).
        if connector.parking_minutes - (session.parking_billed_minutes or 0) < 1:
            continue

        minutes, charged, unpaid = _charge(session.pk, connector.parking_minutes)
        if not minutes:
            continue

        result['sessions'] += 1
        result['minutes'] += minutes
        result['charged'] += charged
        result['unpaid'] += unpaid

    return result


def _charge(session_id: int, total_minutes: int) -> tuple:
    """Bitta sessiya uchun yangi daqiqalarni hisoblab, pul yechadi.

    Butun amal `select_for_update` qulfi ostida bajariladi va hisob qulf ichida
    QAYTA o'qiladi — shunda buyruq tasodifan ikki marta ishga tushsa ham bir xil
    daqiqalar ikki marta yechilmaydi.

    Qaytaradi: (hisoblangan_daqiqa, yechilgan_summa, yechilmagan_summa)
    """
    with transaction.atomic():
        session = (
            ChargingSession.objects
            .select_for_update()
            .select_related('station', 'user')
            .filter(pk=session_id, status=ChargingSession.Status.CHARGING)
            .first()
        )
        if session is None:
            return 0, 0, 0

        already = session.parking_billed_minutes or 0
        minutes = total_minutes - already
        if minutes < 1:
            return 0, 0, 0

        amount = minutes * session.parking_fee_per_min
        wallet, _ = WalletBalance.objects.select_for_update().get_or_create(user=session.user)
        charged = min(amount, wallet.amount)
        unpaid = amount - charged

        if charged:
            wallet.amount -= charged
            wallet.save(update_fields=['amount'])
            Transaction.objects.create(
                user=session.user,
                type=Transaction.Type.CHARGE_PAYMENT,
                amount=charged,
                description=f'{session.station.name} — parkovka {minutes} daq',
            )

        # Daqiqalar pul yetmagan holatda ham hisoblanadi: aks holda keyingi
        # chaqiruvda o'sha daqiqalar qayta urinilib, ledger buzilardi.
        # Yechilmagan qism sessiya tugaganda umumiy summadan olinadi.
        session.parking_billed_minutes = already + minutes
        session.parking_billed_amount = (session.parking_billed_amount or 0) + charged
        session.save(update_fields=['parking_billed_minutes', 'parking_billed_amount'])

        if unpaid:
            logger.warning(
                "Parkovka: %s hamyonida %s so'm yetmadi (sessiya %s)",
                session.user.username, unpaid, session.pk,
            )

    return minutes, charged, unpaid
