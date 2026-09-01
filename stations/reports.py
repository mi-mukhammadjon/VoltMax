# -*- coding: utf-8 -*-
"""Foydalanuvchi yuboradigan nosozlik xabarlari.

Ilova ilgari «xabaringiz qabul qilindi» deb yozardi va hech qayerga
hech narsa yubormasdi. Bu oddiy ishlamaydigan tugmadan yomonroq:
buzuq charger oldida turgan odam operator endi biladi deb o'ylab
ketardi, aslida hech kim bilmasdi.

Bu yerdagi asosiy qoida: FOYDALANUVCHINING XABARI STANSIYANI
O'CHIRMAYDI. U tekshirilmagan signal — qurilmaning o'zi aytmagan,
operator ham ko'rmagan. Bitta odamning xabari bilan stansiya rasman
buzuq bo'lib qolsa, uni ataylab «o'chirish» mumkin bo'lardi.

Shuning uchun xabar ikki narsa qiladi: `StationReport` yozuvi
qoldiradi va operator ro'yxatida ko'rinishi uchun manbasi `USER`
bo'lgan nosozlik yozuvini ochadi. Stansiya holati o'zgarmaydi — uni
faqat qurilma yoki operator o'zgartiradi.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger('stations.reports')

# Bir odam bitta stansiya haqida shu vaqt ichida qayta xabar yubora
# olmaydi. Cheklovsiz bo'lsa, bitta odam ro'yxatni to'ldirib, haqiqiy
# nosozliklarni ko'rinmas qilib qo'yardi.
COOLDOWN = timedelta(hours=6)

# Izoh uzun bo'lsa kesiladi: u operator ro'yxatida bitta qatorda
# ko'rinadi va uzun matn qolganini siqib chiqarardi
NOTE_LIMIT = 300


class ReportError(Exception):
    """Xabarni qabul qilib bo'lmadi. Matn foydalanuvchiga ko'rsatiladi."""


def recent_report(user, station):
    """Shu odamning shu stansiya haqidagi oxirgi yangi xabari."""
    from .models import StationReport

    return StationReport.objects.filter(
        user=user, station=station,
        created_at__gte=timezone.now() - COOLDOWN,
    ).first()


def submit(user, station, note=''):
    """Xabarni qabul qiladi. `(report, issue, created)` qaytaradi.

    `created` — SHU xabar nosozlik yozuvini ochdimi. Ochilmagan
    bo'lishi normal: yozuv allaqachon ochiq bo'lishi mumkin (qurilma
    o'zi aytgan yoki boshqa odam xabar bergan).
    """
    from . import maintenance
    from .models import MaintenanceIssue, StationReport

    if recent_report(user, station):
        raise ReportError('Siz bu stansiya haqida yaqinda xabar bergansiz')

    note = (note or '').strip()[:NOTE_LIMIT]

    # Ochiq yozuv bo'lsa xabar o'shanga ulanadi. Yangi yozuv ochish
    # bir muammoni ikki marta ko'rsatardi.
    issue = MaintenanceIssue.objects.filter(
        station=station, connector=None,
        status=MaintenanceIssue.Status.OPEN,
    ).first()
    created = False

    if issue is None:
        issue, created = maintenance.open_issue(
            station=station,
            reason='Foydalanuvchi xabari',
            source=MaintenanceIssue.Source.USER,
        )

    report = StationReport.objects.create(
        station=station, user=user, note=note, issue=issue)

    # Sabab YOZUV YARATILGANDAN KEYIN hisoblanadi: aks holda birinchi
    # xabarning o'zi «2 ta» bo'lib ko'rinardi va operator ikki kishi
    # shikoyat qilgan deb o'ylardi.
    #
    # Faqat foydalanuvchi manbali yozuv yangilanadi: qurilma «Qisqa
    # tutashuv» degan bo'lsa, uni «ishlamayapti» bilan almashtirish
    # tashxisni yo'qotardi.
    if issue and issue.source == MaintenanceIssue.Source.USER:
        issue.reason = _reason(station, note)
        issue.save(update_fields=['reason'])

    logger.info('Foydalanuvchi xabari: %s — %s', station.name, user)
    return report, issue, created


def _reason(station, note):
    """Operator ro'yxatida ko'rinadigan matn."""
    from .models import StationReport

    count = StationReport.objects.filter(
        station=station,
        created_at__gte=timezone.now() - timedelta(days=7),
    ).count()

    base = f'Foydalanuvchi xabari ({count} ta)' if count > 1 else 'Foydalanuvchi xabari'
    return f'{base}: {note}'[:200] if note else base
