# -*- coding: utf-8 -*-
"""Hamkorlar bilan oylik hisob-kitob.

Stansiya hamkorga tegishli, tushum esa bizga keladi — haydovchining
hamyonidan pul yechiladi. Oy oxirida hamkorga uning ulushini o'tkazish
kerak.

`Partner.commission_percent` — BIZ ushlab qoladigan foiz, qolgani
hamkorniki. Foiz butun tushumga (energiya + parkovka) qo'llanadi:
parkovka haqi hamkorning ulagichi band bo'lgani uchun olinadi, ya'ni u
ham xizmatning bir qismi.

Hisob yaxlitlash bilan: so'mning kasri yo'q, shuning uchun hamkor ulushi
pastga yaxlitlanadi va qoldiq bizda qoladi. Aks holda bir necha yuz
sessiyada tiyinlar yig'ilib, hisob mos kelmay qolardi.
"""

from datetime import date, timedelta


def month_range(year: int, month: int):
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return start, end


def partner_totals(partner, year, month):
    """Hamkorning davr ichidagi ko'rsatkichlari.

    Faqat TUGAGAN sessiyalar hisobga olinadi: ketayotganining yakuniy
    summasi hali ma'lum emas va u keyingi davrga tushadi.
    """
    from django.db.models import Count, Sum

    from sessions_app.models import ChargingSession

    start, end = month_range(year, month)
    stats = (ChargingSession.objects
             .filter(station__partner=partner,
                     stopped_at__date__gte=start, stopped_at__date__lte=end)
             .exclude(status=ChargingSession.Status.CHARGING)
             .aggregate(gross=Sum('final_cost'),
                        kwh=Sum('final_kwh_charged'),
                        count=Count('id')))

    gross = stats['gross'] or 0
    percent = partner.commission_percent or 0
    commission = gross * percent // 100        # pastga yaxlitlash
    return {
        'gross': gross,
        'commission_percent': percent,
        'commission': commission,
        'amount': gross - commission,
        'sessions': stats['count'] or 0,
        'kwh': round(stats['kwh'] or 0, 2),
    }


def build_period(year, month, *, only_active=True):
    """Davr bo'yicha barcha hamkorlarning hisobi.

    Mavjud yozuv bo'lsa u OLINADI, qayta hisoblanmaydi: to'lov qilingandan
    keyin komissiya foizi o'zgarsa, eski davr ham o'zgarib ketardi.
    """
    from management.models import Partner, PartnerPayout

    saved = {row.partner_id: row for row in
             PartnerPayout.objects.filter(year=year, month=month)
             .select_related('partner')}

    partners = Partner.objects.all()
    if only_active:
        partners = partners.filter(is_active=True)

    rows = []
    for partner in partners.order_by('name'):
        record = saved.get(partner.pk)
        if record is not None:
            rows.append({'partner': partner, 'payout': record,
                         'gross': record.gross, 'commission': record.commission,
                         'amount': record.amount, 'sessions': record.sessions,
                         'kwh': record.kwh,
                         'commission_percent': record.commission_percent})
            continue

        totals = partner_totals(partner, year, month)
        rows.append({'partner': partner, 'payout': None, **totals})

    return rows


def freeze(partner, year, month, user=None):
    """Hisobni yozuvga aylantiradi (muzlatadi).

    Shundan keyin komissiya foizi o'zgarsa ham bu davr o'zgarmaydi.
    Yozuv allaqachon bo'lsa u qaytariladi — ikkinchi marta yaratilmaydi.
    """
    from management.models import PartnerPayout

    existing = PartnerPayout.objects.filter(
        partner=partner, year=year, month=month).first()
    if existing is not None:
        return existing, False

    totals = partner_totals(partner, year, month)
    record = PartnerPayout.objects.create(
        partner=partner, year=year, month=month, created_by=user, **totals)
    return record, True
