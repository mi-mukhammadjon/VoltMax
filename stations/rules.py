# -*- coding: utf-8 -*-
"""Zaryadlash qoidalari — sozlamalardagi cheklovlarni HAQIQATAN qo'llaydi.

Ilgari bu cheklovlar faqat sozlamalar sahifasida turardi: operator minimal
balansni yoki ish vaqtini belgilardi, tizim esa ularga qaramasdi. Panelda
bor, lekin ishlamaydigan sozlama eng yomon holat — operator himoya bor deb
o'ylaydi.

Qoidalar bitta joyda, chunki ular uch xil yo'ldan tekshiriladi:
  * RFID karta (OCPP `Authorize`),
  * mobil ilova (sessiyani boshlash API'si),
  * panel (operator qo'lda boshlaganda).

Har funksiya sababni MATN bilan qaytaradi: `None` — ruxsat, matn — rad
etish sababi. Shunda har uch joyda bir xil xabar ko'rinadi.
"""

from datetime import timedelta

from django.utils import timezone


def _settings():
    from management.models import SiteSettings

    return SiteSettings.load()


# ── Ish vaqti ───────────────────────────────────────────────────
def is_working_now(now=None, settings_obj=None):
    """Stansiyalar hozir ishlaydimi.

    Bayram kunlari ham hisobga olinadi: ular kalendarga Google'dan tushadi
    (Sozlamalar > Bayramlar). Bayramda kunu tun ishlash mantiqiy emas —
    tarif va navbatchilik boshqacha bo'ladi, shuning uchun bayram kuni
    ish vaqti qoidasi qat'iy amal qiladi.
    """
    settings_obj = settings_obj or _settings()
    if settings_obj.work_all_day:
        return True, None

    now = now or timezone.localtime()
    start, end = settings_obj.work_start, settings_obj.work_end
    current = now.time()

    # Tunga o'tuvchi jadval (22:00 → 06:00) — oraliq yarim tundan o'tadi
    if start <= end:
        working = start <= current <= end
    else:
        working = current >= start or current <= end

    if working:
        return True, None
    return False, (f"Stansiyalar {start:%H:%M} dan {end:%H:%M} gacha ishlaydi. "
                   f"Hozir {current:%H:%M}.")


def holiday_today(day=None):
    """Bugun bayram bo'lsa uning nomi, aks holda `None`."""
    from management.models import Holiday

    row = Holiday.objects.filter(date=day or timezone.localdate()).first()
    return row.name if row else None


# ── Balans ──────────────────────────────────────────────────────
def check_balance(user, settings_obj=None):
    """Foydalanuvchida zaryadlashni boshlashga yetarli pul bormi.

    Chegara sozlamada: 0 bo'lsa faqat musbat balans talab qilinadi. Aks
    holda sessiya boshlanib, o'rtasida pul tugab qolardi — charger esa
    to'xtaganini foydalanuvchiga tushuntirmaydi.
    """
    from wallet.models import WalletBalance

    if user is None:
        return None      # xizmat kartasi — hisob yuritilmaydi

    settings_obj = settings_obj or _settings()
    wallet = WalletBalance.objects.filter(user=user).first()
    amount = wallet.amount if wallet else 0
    minimum = settings_obj.min_balance_to_start

    if amount <= 0:
        return "Hamyonda mablag' yo'q. Hisobni to'ldiring."
    if minimum and amount < minimum:
        from dashboard.templatetags.money import format_som

        return (f"Zaryadlashni boshlash uchun kamida {format_som(minimum)} so'm "
                f"kerak. Hozir {format_som(amount)} so'm.")
    return None


# ── Karta sarf chegarasi ────────────────────────────────────────
def check_card_limits(card):
    """Kartaga qo'yilgan kunlik/oylik chegara oshib ketmadimi.

    Chegara kompaniya uchun kerak: karta haydovchida turadi, hamyon esa
    kompaniyaniki. Chegarasiz bitta karta butun oylik byudjetni bir kunda
    sarflab yuborishi mumkin edi.

    Chegara BOSHLASHDA tekshiriladi. Sessiya o'rtasida to'xtatilmaydi:
    yarim yo'lda uzilgan zaryad haydovchini stansiyada qoldiradi va bu
    chegaradan ko'ra kattaroq muammo. Shuning uchun oxirgi sessiya
    chegaradan biroz oshishi mumkin — buni operator ham bilishi uchun
    panelda sarf ko'rsatiladi.
    """
    if card is None:
        return None

    from dashboard.templatetags.money import format_som

    for label, spent, limit in card.limit_state:
        if spent >= limit:
            return (f'{label} uchun chegara tugagan: {format_som(limit)} so\'m. '
                    f'Sarflandi: {format_som(spent)} so\'m.')
    return None


def can_start(user, now=None, settings_obj=None, card=None):
    """Sessiyani boshlash mumkinmi. `None` — mumkin, matn — sabab."""
    settings_obj = settings_obj or _settings()

    working, reason = is_working_now(now=now, settings_obj=settings_obj)
    if not working:
        holiday = holiday_today()
        return f'{reason} (bugun {holiday})' if holiday else reason

    reason = check_balance(user, settings_obj=settings_obj)
    if reason:
        return reason

    # Chegara balansdan KEYIN tekshiriladi: pul umuman yo'q bo'lsa, sabab
    # sifatida "chegara tugadi" emas, "hamyon bo'sh" aytilgani to'g'riroq.
    return check_card_limits(card)


# ── Sessiya davomiyligi ─────────────────────────────────────────
def session_deadline(session, settings_obj=None):
    """Sessiya qachon majburiy to'xtatilishi kerak. Chegara yo'q bo'lsa `None`."""
    settings_obj = settings_obj or _settings()
    limit = settings_obj.max_session_minutes
    if not limit or session.started_at is None:
        return None
    return session.started_at + timedelta(minutes=limit)


def overdue_sessions(now=None, settings_obj=None):
    """Chegaradan oshib ketgan, hali ham ketayotgan sessiyalar.

    Unutilgan sessiya kun bo'yi hisoblanib, foydalanuvchiga katta hisob
    chiqarardi — bu esa qaytarib berish va nizo demakdir.
    """
    from sessions_app.models import ChargingSession

    settings_obj = settings_obj or _settings()
    limit = settings_obj.max_session_minutes
    if not limit:
        return ChargingSession.objects.none()

    cutoff = (now or timezone.now()) - timedelta(minutes=limit)
    return ChargingSession.objects.filter(
        status=ChargingSession.Status.CHARGING,
        started_at__lte=cutoff,
    ).select_related('station', 'connector', 'user')


# ── Parkovka ────────────────────────────────────────────────────
def parking_minutes(finished_at, now=None, settings_obj=None):
    """Haq olinadigan parkovka daqiqalari.

    Imtiyoz vaqti chegirib tashlanadi: zaryad tugagach avtomobilni darhol
    olib ketish har doim ham mumkin emas (kutish, navbat), shu sababli
    birinchi daqiqalardan pul olish nizoga sabab bo'lardi.
    """
    if finished_at is None:
        return 0

    settings_obj = settings_obj or _settings()
    elapsed = ((now or timezone.now()) - finished_at).total_seconds() / 60
    billable = elapsed - settings_obj.parking_grace_minutes
    return max(0, int(billable))
