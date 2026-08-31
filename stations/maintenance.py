"""Profilaktika: nosozlik yozuvlarini ochish/yopish va foydalanuvchilarni xabardor qilish.

Bitta joyda turishining sababi — nosozlik uch xil manbadan kelib chiqadi:
chargerning o'zidan (OCPP StatusNotification), aloqa uzilishidan (Heartbeat
kelmay qolishi) va operatordan (panel orqali ta'mirga qo'yish). Uchalasi ham
bir xil yozuv qoldirishi va bir xil qoida bo'yicha xabar yuborishi kerak.
"""

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from stations.models import Connector, MaintenanceIssue, Station

logger = logging.getLogger('stations.maintenance')


def open_issue(*, station, connector=None, reason, error_code='', source=None):
    """Ochiq yozuv yaratadi. Allaqachon ochig'i bo'lsa — sababini yangilaydi.

    Har StatusNotification'da yangi yozuv yaratilmasligi uchun avval mavjudi
    qidiriladi; bazadagi UniqueConstraint esa poyga holatidan himoya qiladi.
    """
    source = source or MaintenanceIssue.Source.OCPP
    kind = MaintenanceIssue.Kind.CONNECTOR if connector else MaintenanceIssue.Kind.STATION

    existing = MaintenanceIssue.objects.filter(
        station=station, connector=connector, status=MaintenanceIssue.Status.OPEN,
    ).first()

    if existing:
        # Sabab aniqlashgan bo'lishi mumkin (avval "Unavailable", keyin aniq
        # errorCode keldi) — yozuv yangilanadi, lekin `opened_at` tegilmaydi:
        # muammo o'sha muammo, faqat tavsifi aniqlashdi.
        changed = []
        if reason and existing.reason != reason:
            existing.reason = reason
            changed.append('reason')
        if error_code and existing.error_code != error_code:
            existing.error_code = error_code
            changed.append('error_code')
        if changed:
            existing.save(update_fields=changed)
        return existing, False

    try:
        with transaction.atomic():
            issue = MaintenanceIssue.objects.create(
                station=station, connector=connector, kind=kind,
                reason=reason, error_code=error_code, source=source,
            )
        return issue, True
    except IntegrityError:
        # Boshqa oqim ayni damda ochib ulgurgan
        return MaintenanceIssue.objects.filter(
            station=station, connector=connector, status=MaintenanceIssue.Status.OPEN,
        ).first(), False


def resolve_issue(issue, *, user=None, note=''):
    """Yozuvni yopadi. Yopilgan yozuv qayta yopilmaydi."""
    if issue.status == MaintenanceIssue.Status.RESOLVED:
        return False

    issue.status = MaintenanceIssue.Status.RESOLVED
    issue.resolved_at = timezone.now()
    issue.resolved_by = user
    issue.resolution_note = note
    issue.save(update_fields=['status', 'resolved_at', 'resolved_by', 'resolution_note'])
    return True


def resolve_open_issues(*, station, connector=None, user=None, note=''):
    """Berilgan nishon bo'yicha ochiq yozuvlarni yopadi. Yopilgan soni qaytadi."""
    issues = MaintenanceIssue.objects.filter(
        station=station, connector=connector, status=MaintenanceIssue.Status.OPEN,
    )
    return sum(1 for issue in issues if resolve_issue(issue, user=user, note=note))


# ── Xabar yuborish ───────────────────────────────────────────────────

# Shu muddat ichida stansiyada zaryadlagan foydalanuvchi "doimiy mijoz"
# hisoblanadi — u yerga yana borishi ehtimoli yuqori.
REGULAR_WINDOW = timedelta(days=30)


def audience_breakdown(station):
    """Kim xabar oladi va NIMA UCHUN — [{'user': ..., 'reason': ...}, ...].

    Hamma foydalanuvchiga yubormaymiz — bu spam bo'lardi va odamlar
    bildirishnomalarni butunlay o'chirib qo'yardi. Xabar uch toifaga boradi:

      1. shu stansiyada hozir zaryadlanayotganlar — rejasi ayni damda buzildi;
      2. shu stansiyada kelgusi broni borlar — rejasi buzilmoqda;
      3. oxirgi 30 kunda shu stansiyada zaryadlagan doimiy mijozlar — ular
         yana o'sha yerga borishi ehtimoli yuqori.

    Uchinchi toifa ataylab STANSIYAGA bog'langan: xabar "sizga aloqador joy"
    haqida bo'ladi, shuning uchun baza o'sganda ham spamga aylanmaydi.

    Sabab operatorga panelda ko'rsatiladi, shuning uchun ro'yxat shu tartibda
    quriladi: bir odam bir necha toifaga tushsa, eng kuchli sabab qoladi.
    """
    from bookings.models import Booking
    from django.contrib.auth import get_user_model
    from sessions_app.models import ChargingSession

    reasons = {}   # user_id -> sabab (birinchi yozilgani kuchliroq)

    for user_id in ChargingSession.objects.filter(
        station=station, status=ChargingSession.Status.CHARGING,
    ).values_list('user_id', flat=True):
        reasons.setdefault(user_id, 'Hozir zaryadlanmoqda')

    for user_id, when in Booking.objects.filter(
        station=station,
        status=Booking.Status.CONFIRMED,
        scheduled_at__gte=timezone.now(),
    ).values_list('user_id', 'scheduled_at'):
        reasons.setdefault(user_id, f'Bron: {timezone.localtime(when):%d.%m %H:%M}')

    for user_id in ChargingSession.objects.filter(
        station=station, started_at__gte=timezone.now() - REGULAR_WINDOW,
    ).values_list('user_id', flat=True):
        reasons.setdefault(user_id, 'Doimiy mijoz (30 kun ichida)')

    users = get_user_model().objects.filter(id__in=reasons)
    return [{'user': user, 'reason': reasons[user.id]} for user in users]


def affected_users(station):
    """Xabar oluvchi foydalanuvchilar (QuerySet). Sabab kerak bo'lsa —
    `audience_breakdown()`."""
    from django.contrib.auth import get_user_model

    ids = {row['user'].id for row in audience_breakdown(station)}
    return get_user_model().objects.filter(id__in=ids)


def notify_issue(issue, *, resolved=False, extra_note=''):
    """Nosozlik (yoki uning tuzatilgani) haqida foydalanuvchilarga xabar yozadi.

    Yuborilgan xabarlar soni qaytadi. Nol qaytishining ikki sababi bor:
    xabar allaqachon yuborilgan yoki hozir xabar oluvchi yo'q — chaqiruvchi
    ularni ajratishi kerak bo'lsa, `issue.notified_at` ni CHAQIRUVDAN OLDIN
    tekshirsin (bu funksiya uni o'zi qo'yadi).
    """
    from management.models import UserNotification

    stamp_field = 'resolved_notified_at' if resolved else 'notified_at'
    if getattr(issue, stamp_field):
        return 0

    station = issue.station
    users = list(affected_users(station))

    # Belgi FAQAT haqiqatan xabar ketganda qo'yiladi. Aks holda hozir broni
    # yo'q stansiya "xabar berilgan" bo'lib qolar va keyinroq kimdir bron
    # qilganda operator uni ogohlantira olmasdi.
    if not users:
        return 0

    # Matn panelda tahrirlanadi (Sozlamalar > Bildirishnoma). Shablon
    # o'chirilgan bo'lsa xabar umuman yozilmaydi — operator shu hodisani
    # ataylab o'chirgan.
    from management.models import NotificationTemplate

    event = (NotificationTemplate.Event.STATION_UP if resolved
             else NotificationTemplate.Event.STATION_DOWN)
    template = NotificationTemplate.for_event(event)
    if template is None:
        return 0

    title, body = template.render({
        'stansiya': station.name,
        'ulagich': issue.target_label,
        'sabab': issue.reason,
    })
    kind = (UserNotification.Kind.STATION_UP if resolved
            else UserNotification.Kind.STATION_DOWN)
    if extra_note:
        body = f'{body} {extra_note}'

    UserNotification.objects.bulk_create([
        UserNotification(user=user, kind=kind, title=title, body=body[:400], station=station)
        for user in users
    ])

    setattr(issue, stamp_field, timezone.now())
    issue.save(update_fields=[stamp_field])
    logger.info('Profilaktika: %s uchun %s ta xabar yuborildi', issue, len(users))
    return len(users)


# ── Qurilma holatidan avtomatik yozuv ────────────────────────────────

def sync_issues_from_devices(*, user=None):
    """Barcha stansiyalarni ko'rib chiqib, yozuvlarni HOZIRGI holatga keltiradi.

    Ikki tomonlama ishlaydi: nosoz bo'lib yozuvsiz qolganlarga yozuv ochadi,
    tuzalib ketgan yozuvlarni esa yopadi. "Sinxronlash" tugmasi shuni chaqiradi.
    """
    opened = resolved = 0

    for station in Station.objects.prefetch_related('connectors'):
        # ── Charger darajasi: ocpp_id bor, lekin aloqa yo'q ──
        if station.ocpp_id and not station.is_online:
            _, created = open_issue(
                station=station, reason="Charger bilan aloqa yo'q (Heartbeat kelmayapti)",
                source=MaintenanceIssue.Source.OCPP,
            )
            opened += int(created)
        else:
            resolved += resolve_open_issues(
                station=station, connector=None, user=user, note='Aloqa tiklandi',
            )

        # ── Ulagich darajasi ──
        for connector in station.connectors.all():
            if connector.status == Connector.Status.OFFLINE:
                _, created = open_issue(
                    station=station, connector=connector,
                    reason=connector.offline_reason or 'Ulagich ishlamayapti',
                    source=MaintenanceIssue.Source.OCPP,
                )
                opened += int(created)
            else:
                resolved += resolve_open_issues(
                    station=station, connector=connector, user=user, note='Holat tiklandi',
                )

    return {'opened': opened, 'resolved': resolved}
