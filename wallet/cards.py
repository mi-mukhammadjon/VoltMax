# -*- coding: utf-8 -*-
"""Kartani biriktirish va undan pul yechish — provayderdan mustaqil.

Payme va Click bir xil ishni butunlay boshqacha qiladi. Agar bu farq
butun kodga tarqalsa, uchinchi provayder qo'shilganda yoki biri
almashtirilganda hamma joyni qayta yozish kerak bo'lardi.

Shuning uchun oqim BITTA joyda tasvirlangan:

    register(user, provider, pan, expiry)   → karta (tasdiqlanmagan)
    send_code(card)                         → bank SMS yuboradi
    verify(card, code)                      → karta faollashadi
    charge(card, amount)                    → pul yechiladi

Provayderga xos qism `adapters` da: har biri to'rtta metodli oddiy
sinf. Yangi provayder qo'shish — yangi adapter yozish, boshqa hech
narsaga tegmaslik.

KARTA RAQAMI bu qatlamdan NARIGA O'TMAYDI: u faqat `register` ga
kiradi, adapterga uzatiladi va o'sha yerda qoladi. Bazaga yozilmaydi,
logga tushmaydi, xato matniga kirmaydi.
"""
import logging

logger = logging.getLogger('wallet.cards')


class CardError(Exception):
    """Karta bilan ishlashda xato. Matn foydalanuvchiga ko'rsatiladi."""


def _adapter(provider):
    """Provayder kodiga mos adapter.

    Noma'lum kod uchun SOXTA adapter EMAS, xato: soxta adapter jimgina
    "hammasi joyida" deb javob berib, pul yechilmagan holda ham to'lov
    o'tdi deb ko'rsatardi.
    """
    from .card_adapters import ADAPTERS

    adapter = ADAPTERS.get(provider.code)
    if adapter is None:
        raise CardError(f'{provider.name} kartani biriktirishni qo‘llamaydi')
    return adapter(provider)


# ── Oqim ─────────────────────────────────────────────────────────
def register(user, provider, pan: str, expiry: str):
    """Kartani provayderga yuboradi va TASDIQLANMAGAN yozuv qaytaradi.

    `pan` shu funksiyadan naryoga chiqmaydi.
    """
    from .card_crypto import brand_of, mask_pan
    from .models import SavedCard

    digits = ''.join(ch for ch in str(pan or '') if ch.isdigit())
    if not 13 <= len(digits) <= 19:
        raise CardError('Karta raqami noto‘g‘ri')
    if not _valid_expiry(expiry):
        raise CardError('Amal muddati noto‘g‘ri (MM/YY)')

    result = _adapter(provider).register(digits, expiry)

    card = SavedCard(
        user=user, provider=provider,
        masked_pan=mask_pan(digits),
        brand=brand_of(digits),
        expires=expiry,
        verify_ref=result.get('verify_ref', '')[:120],
        state=SavedCard.State.PENDING,
    )
    card.token = result.get('token', '')
    card.save()

    # Logda faqat MASKALANGAN ko'rinish
    logger.info('Karta biriktirildi (tasdiq kutilmoqda): %s %s',
                user.username, card.masked_pan)
    return card


def send_code(card):
    """Bank SMS kodini yuborishini so'raydi."""
    if card.state == card.State.ACTIVE:
        raise CardError('Karta allaqachon tasdiqlangan')
    _adapter(card.provider).send_code(card)
    return card


def verify(card, code: str):
    """SMS kodni tekshiradi va kartani faollashtiradi."""
    from django.utils import timezone

    from .models import SavedCard

    if card.state == SavedCard.State.ACTIVE:
        return card

    result = _adapter(card.provider).verify(card, (code or '').strip())

    card.token = result.get('token', '') or card.token
    card.state = SavedCard.State.ACTIVE
    card.verified_at = timezone.now()
    card.verify_ref = ''
    card.last_error = ''
    card.save()

    # Birinchi karta o'zi asosiy bo'ladi: foydalanuvchidan keraksiz
    # tanlov so'ramaymiz
    if not SavedCard.objects.filter(
            user=card.user, is_default=True).exclude(pk=card.pk).exists():
        card.make_default()

    return card


def charge(card, amount: int, *, is_auto=False):
    """Kartadan pul yechadi va hamyonni to'ldiradi.

    Muvaffaqiyatda `PaymentOrder` qaytadi. Hamyon `mark_paid` orqali
    to'ldiriladi — oddiy to'lov bilan bir xil yo'l, ya'ni idempotentlik,
    tranzaksiya yozuvi va qulf bir joyda qoladi.
    """
    from django.utils import timezone

    from .models import PaymentOrder, SavedCard

    if not card.is_usable:
        raise CardError('Karta ishlamaydi — uni qaytadan biriktiring')
    if amount <= 0:
        raise CardError('Summa noto‘g‘ri')

    order = PaymentOrder.objects.create(
        user=card.user, provider=card.provider, amount=amount, is_auto=is_auto)

    try:
        result = _adapter(card.provider).charge(card, order)
    except CardError as error:
        order.cancel(reason=-1)
        card.last_error = str(error)[:200]
        # Bank rad etgan karta bilan qayta urinish ma'nosiz va u
        # hisobni bloklashga olib kelishi mumkin
        if getattr(error, 'card_dead', False):
            card.state = SavedCard.State.DEAD
        card.save(update_fields=['last_error', 'state'])
        raise

    order.mark_paid(external_id=result.get('external_id', ''))
    card.last_used_at = timezone.now()
    card.last_error = ''
    card.save(update_fields=['last_used_at', 'last_error'])

    logger.info('Kartadan yechildi: %s %s — %s so‘m%s',
                card.user.username, card.masked_pan, amount,
                ' (avtomatik)' if is_auto else '')
    return order


def remove(card):
    """Kartani o'chiradi va provayderga ham xabar beradi."""
    try:
        _adapter(card.provider).remove(card)
    except CardError as error:
        # Provayder javob bermasa ham yozuv bizda qolmasligi kerak:
        # foydalanuvchi "o'chirdim" deb o'ylaydi va u haq
        logger.warning('Provayderda karta o‘chmadi: %s', error)

    was_default = card.is_default
    user = card.user
    card.delete()

    # Asosiy karta o'chirilsa, qolganidan biri asosiy bo'ladi
    if was_default:
        from .models import SavedCard

        replacement = SavedCard.objects.filter(
            user=user, state=SavedCard.State.ACTIVE).first()
        if replacement:
            replacement.make_default()


# ── Yordamchi ────────────────────────────────────────────────────
def _valid_expiry(expiry: str) -> bool:
    """`MM/YY` yoki `MMYY` — ikkalasi ham qabul qilinadi."""
    digits = ''.join(ch for ch in str(expiry or '') if ch.isdigit())
    if len(digits) != 4:
        return False
    month = int(digits[:2])
    return 1 <= month <= 12
