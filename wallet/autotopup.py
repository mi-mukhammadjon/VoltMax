# -*- coding: utf-8 -*-
"""Balans pasayganda kartadan avtomatik to'ldirish.

Nima uchun kerak: zaryadlash paytida pul tugasa sessiya to'xtaydi va
odam yarim zaryadlangan mashina bilan qoladi — ko'pincha yerto'la
parkovkada, aloqasiz joyda. Bu eng yomon holat va uni oldini olish
mumkin.

Nima uchun EHTIYOT bilan: avtomatik pul yechish — ishonchni eng tez
yo'qotadigan narsa. Bitta kutilmagan yechim, bitta ikki marta
yechilgan summa, va odam kartani uzib tashlaydi. Shuning uchun:

  * har yechimdan keyin DARHOL xabar ketadi;
  * kunlik va oylik chegara bor va ular serverda turadi;
  * ketma-ket uchta xatodan keyin o'z-o'zidan o'chadi — ishlamaydigan
    karta bilan tinmay urinish bankdan bloklashga olib keladi;
  * FAQAT zaryadlash ketayotgan yoki yaqinda tugagan foydalanuvchi
    uchun ishlaydi: ilovani ochmagan odamning kartasidan pul yechish
    kutilmagan bo'lardi.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger('wallet.autotopup')

# Sessiya shu vaqt ichida faol bo'lgan bo'lsa foydalanuvchi "hozir
# zaryadlayapti" deb hisoblanadi
RECENT_WINDOW = timedelta(minutes=30)


def candidates():
    """Hozir to'ldirish kerak bo'lgan sozlamalar.

    Ikki shart birga: balans chegaradan past VA foydalanuvchi hozir
    zaryadlayapti (yoki yaqinda zaryadlagan).
    """
    from sessions_app.models import ChargingSession

    from .models import AutoTopUp, WalletBalance

    since = timezone.now() - RECENT_WINDOW
    active_users = set(
        ChargingSession.objects.filter(started_at__gte=since)
        .values_list('user_id', flat=True)
    ) | set(
        ChargingSession.objects.filter(status=ChargingSession.Status.CHARGING)
        .values_list('user_id', flat=True)
    )
    if not active_users:
        return []

    rows = (AutoTopUp.objects.filter(is_active=True, user_id__in=active_users)
            .select_related('card', 'card__provider', 'user'))

    ready = []
    for row in rows:
        wallet = WalletBalance.objects.filter(user=row.user).first()
        balance = wallet.amount if wallet else 0
        if balance < row.threshold:
            ready.append((row, balance))
    return ready


def run_once():
    """Bir tsikl. `(yechildi, xato)` sonlarini qaytaradi."""
    from . import cards as card_flow

    charged = failed = 0

    for row, balance in candidates():
        reason = row.blocked_reason()
        if reason:
            logger.info('Avtomatik to‘ldirish o‘tkazib yuborildi (%s): %s',
                        row.user.username, reason)
            continue

        try:
            card_flow.charge(row.card, row.amount, is_auto=True)
        except card_flow.CardError as error:
            failed += 1
            row.fail_streak += 1
            row.last_error = str(error)[:200]
            # Uchinchi xatodan keyin o'chadi va foydalanuvchiga
            # aytiladi: jimgina o'chgan sozlama eng yomon holat
            if row.fail_streak >= row.MAX_FAILS:
                row.is_active = False
                _notify_failed(row, str(error))
            row.save(update_fields=['fail_streak', 'last_error', 'is_active'])
            continue

        charged += 1
        row.fail_streak = 0
        row.last_error = ''
        row.last_run_at = timezone.now()
        row.save(update_fields=['fail_streak', 'last_error', 'last_run_at'])
        _notify_charged(row, balance)

    return charged, failed


def _notify_charged(row, balance_before):
    """Yechim haqida DARHOL xabar.

    Foydalanuvchi buni ilovani ochganda emas, o'sha payt bilishi kerak.
    """
    from dashboard.templatetags.money import format_som
    from management.models import UserNotification

    try:
        UserNotification.objects.create(
            user=row.user,
            kind=UserNotification.Kind.SYSTEM,
            title='Hisob avtomatik to‘ldirildi',
            body=(f'{row.card.masked_pan} kartasidan '
                  f'{format_som(row.amount)} so‘m yechildi. '
                  f'Balans {format_som(balance_before)} so‘mgacha tushgan edi.'),
        )
    except Exception:       # noqa: BLE001 — xabar yozilmasa ham to'lov o'tgan
        logger.warning('Avtomatik to‘ldirish haqida xabar yozilmadi')


def _notify_failed(row, error):
    from management.models import UserNotification

    try:
        UserNotification.objects.create(
            user=row.user,
            kind=UserNotification.Kind.SYSTEM,
            title='Avtomatik to‘ldirish o‘chirildi',
            body=(f'{row.card.masked_pan} kartasidan pul yechib bo‘lmadi: '
                  f'{error}. Sozlamani ilovada qayta yoqing.'),
        )
    except Exception:       # noqa: BLE001
        pass
