"""Profilaktika bo'limi — qurilmalardagi nosozliklar bilan ishlash.

Nima uchun alohida bo'lim: stansiya formasidan "Holat" tanlagichi olib
tashlandi, chunki qo'lda qo'yilgan holat qurilmanikiga zid bo'lib qolardi.
Endi holat qurilmadan hisoblanadi, nosozlik bilan ishlash esa shu yerda:
sabab ko'rinadi, tuzatilgani belgilanadi, foydalanuvchilarga xabar ketadi.
"""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from sessions_app.models import ChargingSession
from stations.maintenance import (
    affected_users,
    audience_breakdown,
    notify_issue,
    open_issue,
    resolve_issue,
    sync_issues_from_devices,
)
from stations.models import Connector, MaintenanceIssue, Station
from stations.services import sync_all, sync_station_status

from .decorators import staff_required
from .redirects import safe_redirect
from .views import PAGE_SIZE, _push_availability, _request_device_status


def _back(request):
    """Amaldan keyin operator o'sha ro'yxatga (filtri bilan) qaytsin."""
    return safe_redirect(request, 'dashboard:maintenance')


def _display_name(user):
    return user.get_full_name().strip() or user.username


def _rows_with_recipients(page_obj):
    """Har bir yozuv uchun xabar oluvchilar SONINI hisoblaydi.

    Jadvalda faqat son turadi — ismlar alohida oynada ko'rsatiladi
    (`maintenance_recipients`), aks holda ustun kengayib jadvalni buzardi.
    Bitta stansiyada bir nechta nosozlik bo'lishi mumkin, shuning uchun
    natija stansiya bo'yicha keshlanadi.
    """
    cache = {}
    rows = []

    for issue in page_obj:
        station_id = issue.station_id
        if station_id not in cache:
            cache[station_id] = affected_users(issue.station).count()
        rows.append({'issue': issue, 'count': cache[station_id]})

    return rows


@staff_required
def maintenance_recipients(request, pk):
    """Xabar kimga borishini oyna uchun JSON qilib qaytaradi.

    Alohida so'rov bo'lishining sababi: ro'yxat uzun bo'lishi mumkin va uni
    har bir jadval qatoriga yashirib qo'yish sahifani og'irlashtirardi.
    Operator qaysi qatorni ochsa — o'shaniki yuklanadi.
    """
    issue = get_object_or_404(
        MaintenanceIssue.objects.select_related('station', 'connector'), pk=pk
    )
    rows = audience_breakdown(issue.station)
    rows.sort(key=lambda row: row['reason'])

    return JsonResponse({
        'station': issue.station.name,
        'target': issue.target_label,
        'reason': issue.reason,
        'recipients': [
            {'name': _display_name(row['user']), 'reason': row['reason']}
            for row in rows
        ],
    })


@staff_required
def maintenance(request):
    issues = MaintenanceIssue.objects.select_related(
        'station', 'connector', 'resolved_by'
    ).order_by('-opened_at')

    state = request.GET.get('state', 'open')
    if state in {'open', 'resolved'}:
        issues = issues.filter(status=state)

    station_id = request.GET.get('station', '').strip()
    if station_id.isdigit():
        issues = issues.filter(station_id=int(station_id))

    counts = MaintenanceIssue.objects.aggregate(
        open=Count('id', filter=Q(status=MaintenanceIssue.Status.OPEN)),
        resolved=Count('id', filter=Q(status=MaintenanceIssue.Status.RESOLVED)),
        unnotified=Count('id', filter=Q(
            status=MaintenanceIssue.Status.OPEN, notified_at__isnull=True,
        )),
    )

    # Qo'lda nosozlik ochish uchun — hozir soz turgan ulagichlar ro'yxati
    healthy = Connector.objects.select_related('station').exclude(
        status=Connector.Status.OFFLINE
    ).order_by('station__name', 'label')

    page_obj = Paginator(issues, PAGE_SIZE).get_page(request.GET.get('page'))

    return render(request, 'dashboard/maintenance.html', {
        'page_obj': page_obj,
        'rows': _rows_with_recipients(page_obj),
        'state': state,
        'station_id': station_id,
        'counts': counts,
        'healthy_connectors': healthy,
        'stations': Station.objects.order_by('name'),
    })


@staff_required
def maintenance_sync(request):
    """Qurilmalardan holatni so'rab, yozuvlarni haqiqatga moslaydi.

    Uch bosqich: qurilmalardan joriy holatni so'rash (TriggerMessage) ->
    baza ichidagi sessiya/ulagich/stansiya mosligini tekshirish ->
    nosozlik yozuvlarini ochish/yopish.
    """
    if request.method != 'POST':
        return _back(request)

    asked = sum(
        1 for st in Station.objects.exclude(ocpp_id__isnull=True).exclude(ocpp_id='')
        if _request_device_status(st)
    )
    db_result = sync_all()
    issue_result = sync_issues_from_devices(user=request.user)

    if asked:
        messages.success(request, f"{asked} ta chargerdan joriy holat so'raldi")
    if db_result['connectors'] or db_result['stations']:
        messages.success(
            request,
            f"Baza to'g'rilandi: {db_result['connectors']} ta ulagich, "
            f"{db_result['stations']} ta stansiya",
        )
    if issue_result['opened'] or issue_result['resolved']:
        messages.success(
            request,
            f"Yozuvlar: {issue_result['opened']} ta ochildi, "
            f"{issue_result['resolved']} tasi yopildi",
        )
    if not any([asked, db_result['connectors'], db_result['stations'],
                issue_result['opened'], issue_result['resolved']]):
        messages.success(request, 'Hammasi mos — tuzatish talab qilinmadi')

    return _back(request)


@staff_required
def maintenance_open(request):
    """Qo'lda nosozlik ochish — ulagichni ta'mirga qo'yish."""
    if request.method != 'POST':
        return _back(request)

    connector = get_object_or_404(Connector, pk=request.POST.get('connector') or 0)
    reason = (request.POST.get('reason') or '').strip()[:200] or "Ta'mirlash ishlari olib borilmoqda"

    if ChargingSession.objects.filter(
        connector=connector, status=ChargingSession.Status.CHARGING
    ).exists():
        messages.error(request, "Faol sessiya bor — avval zaryadlashni to'xtating")
        return _back(request)

    connector.status = Connector.Status.OFFLINE
    connector.offline_reason = reason
    connector.save(update_fields=['status', 'offline_reason'])

    # Chargerning o'ziga ham aytamiz — aks holda u RFID karta bilan
    # mahalliy zaryadlashni qabul qilaverardi.
    delivered = _push_availability(request, connector, operative=False)

    open_issue(
        station=connector.station, connector=connector, reason=reason,
        source=MaintenanceIssue.Source.MANUAL,
    )
    connector.station.refresh_from_db()
    sync_station_status(connector.station)

    suffix = ' va qurilmaga buyruq yuborildi' if delivered else ''
    messages.success(
        request, f'{connector.station.name} — {connector.label} ta\'mirga qo\'yildi{suffix}'
    )
    return _back(request)


@staff_required
def maintenance_resolve(request, pk):
    """Nosozlik tuzatildi: yozuv yopiladi va ulagich xizmatga qaytariladi."""
    if request.method != 'POST':
        return _back(request)

    issue = get_object_or_404(MaintenanceIssue.objects.select_related('station', 'connector'), pk=pk)
    note = (request.POST.get('note') or '').strip()[:300]

    delivered = False
    if issue.connector and issue.connector.status == Connector.Status.OFFLINE:
        connector = issue.connector
        connector.status = Connector.Status.AVAILABLE
        connector.offline_reason = ''
        connector.save(update_fields=['status', 'offline_reason'])
        delivered = _push_availability(request, connector, operative=True)

    resolve_issue(issue, user=request.user, note=note)
    issue.station.refresh_from_db()
    sync_station_status(issue.station)

    suffix = ' va qurilmaga buyruq yuborildi' if delivered else ''
    messages.success(request, f'{issue.target_label} tuzatilgan deb belgilandi{suffix}')

    # Nosozlik haqida xabar bergan bo'lsak, tuzatilgani haqida ham aytamiz —
    # aks holda foydalanuvchi "ishlamayapti" xabari bilan qolib ketardi.
    if issue.notified_at:
        sent = notify_issue(issue, resolved=True)
        if sent:
            messages.success(request, f'{sent} ta foydalanuvchiga tuzatilgani haqida xabar yuborildi')

    return _back(request)


@staff_required
def maintenance_notify(request, pk):
    """Nosozlik haqida foydalanuvchilarga xabar yuboradi.

    Avtomatik emas, ataylab tugma orqali: xabar foydalanuvchiga chiqadi va
    uni qaytarib bo'lmaydi, shuning uchun qaror operatorniki.
    """
    if request.method != 'POST':
        return _back(request)

    issue = get_object_or_404(MaintenanceIssue.objects.select_related('station', 'connector'), pk=pk)
    resolved = issue.status == MaintenanceIssue.Status.RESOLVED
    note = (request.POST.get('note') or '').strip()[:200]

    # Belgini CHAQIRUVDAN OLDIN tekshiramiz: `notify_issue` uni o'zi qo'yadi,
    # keyin tekshirilsa endigina yuborilgan xabar ham "allaqachon yuborilgan"
    # bo'lib ko'rinardi.
    if issue.resolved_notified_at if resolved else issue.notified_at:
        messages.error(request, "Bu yozuv bo'yicha xabar allaqachon yuborilgan")
        return _back(request)

    sent = notify_issue(issue, resolved=resolved, extra_note=note)
    if sent:
        messages.success(request, f'{sent} ta foydalanuvchiga xabar yuborildi')
    else:
        messages.success(
            request,
            "Xabar oluvchi topilmadi — bu stansiyada faol sessiya ham, "
            "kelgusi bron ham yo'q",
        )
    return _back(request)


@staff_required
def maintenance_notify_all(request):
    """Barcha xabar berilmagan ochiq nosozliklar bo'yicha bir yo'la xabar."""
    if request.method != 'POST':
        return _back(request)

    pending = MaintenanceIssue.objects.select_related('station', 'connector').filter(
        status=MaintenanceIssue.Status.OPEN, notified_at__isnull=True,
    )
    total = sum(notify_issue(issue) for issue in pending)
    if total:
        messages.success(request, f'{total} ta foydalanuvchiga xabar yuborildi')
    else:
        messages.success(request, 'Xabar yuborish talab qilinmadi')
    return _back(request)
