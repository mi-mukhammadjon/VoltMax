# -*- coding: utf-8 -*-
"""Push xabarlarni telefonga yetkazish (Expo).

Ilgari xabar faqat bazaga yozilardi: ilova ochilmasa foydalanuvchi undan
bexabar qolardi. «Zaryad tugadi» yoki «stansiya ishlamayapti» kabi xabarning
qiymati esa aynan O'SHA PAYTDA yetib borishida.

Nima uchun Expo: mobil ilova Expo'da qurilgan, uning push xizmati kalit ham,
Firebase sozlamasi ham talab qilmaydi — token ilovada olinadi va shu yerga
yuboriladi. Keyinchalik boshqa xizmatga o'tilsa faqat `send_batch` almashadi.

Nima uchun NAVBAT orqali (so'rov ichida emas): tashqi xizmat sekin javob
berishi yoki umuman javob bermasligi mumkin. Xabar yozilishi shunga bog'liq
bo'lsa, zaryadni to'xtatish yoki nosozlikni qayd etish ham sekinlashardi.
Shuning uchun xabar avval bazaga yoziladi, yuborish esa alohida jarayonda.
"""

import json
import logging
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.utils import timezone

logger = logging.getLogger('management.push')

EXPO_URL = 'https://exp.host/--/api/v2/push/send'
TIMEOUT = 15
BATCH = 100          # Expo bir so'rovda 100 tagacha xabar qabul qiladi
MAX_ATTEMPTS = 3     # shundan keyin xabar "yetkazilmadi" bo'lib qoladi

# Har xabar turi o'z sozlamasiga bog'langan: operator "zaryad tugadi"ni
# o'chirib qo'yishi, lekin nosozlik xabarini qoldirishi mumkin
KIND_SETTINGS = {
    'station_down': None,        # nosozlik har doim yuboriladi
    'station_up': None,
    'charging_complete': 'notify_charging_complete',
    'parking_started': 'notify_parking_started',
    'low_balance': 'notify_low_balance',
}


def allowed(notification, settings_obj) -> bool:
    """Shu xabar telefonga yuborilishi mumkinmi.

    Ikki daraja: umumiy «Push bildirishnomalar» va turga bog'langan
    sozlama. Ikkalasi ham «Sozlamalar > Bildirishnoma» da.
    """
    if not settings_obj.push_enabled:
        return False

    field = KIND_SETTINGS.get(notification.kind)
    return True if field is None else getattr(settings_obj, field, True)


def send_batch(messages):
    """Xabarlar to'plamini Expo'ga yuboradi va javoblar ro'yxatini qaytaradi.

    Javob elementi: `{'status': 'ok'}` yoki `{'status': 'error', ...}`.
    Tarmoq xatosi bo'lsa istisno ko'tariladi — chaqiruvchi qayta urinadi.
    """
    payload = json.dumps(messages).encode('utf-8')
    request = Request(EXPO_URL, data=payload, headers={
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    with urlopen(request, timeout=TIMEOUT) as response:
        body = json.loads(response.read().decode('utf-8'))
    return body.get('data') or []


def deliver_pending(limit=BATCH, transport=None):
    """Yuborilmagan xabarlarni telefonlarga yetkazadi.

    `transport` — testda tarmoqqa chiqmaslik uchun. Qaytaradi:
    `{'sent': n, 'failed': n, 'skipped': n, 'no_device': n}`.
    """
    from accounts.models import DeviceToken

    from .models import SiteSettings, UserNotification

    transport = transport or send_batch
    settings_obj = SiteSettings.load()
    result = {'sent': 0, 'failed': 0, 'skipped': 0, 'no_device': 0}

    pending = (UserNotification.objects
               .filter(pushed_at__isnull=True, push_attempts__lt=MAX_ATTEMPTS)
               .select_related('user')
               .order_by('created_at')[:limit])

    messages, rows = [], []
    for note in pending:
        if not allowed(note, settings_obj):
            # Sozlama o'chirilgan — xabar bazada qoladi (ilovada ko'rinadi),
            # lekin telefonga chiqmaydi. Qayta urinmaslik uchun belgilaymiz.
            note.push_attempts = MAX_ATTEMPTS
            note.push_error = "sozlama o'chirilgan"
            note.save(update_fields=['push_attempts', 'push_error'])
            result['skipped'] += 1
            continue

        tokens = list(DeviceToken.objects
                      .filter(user_id=note.user_id, is_active=True)
                      .values_list('token', flat=True))
        if not tokens:
            note.push_attempts += 1
            note.push_error = 'qurilma tokeni yo\'q'
            note.save(update_fields=['push_attempts', 'push_error'])
            result['no_device'] += 1
            continue

        for token in tokens:
            messages.append({
                'to': token,
                'title': note.title,
                'body': note.body,
                'sound': 'default',
                # Ilova xabarni bosganda qaysi ekranga o'tishini bilishi uchun
                'data': {'notificationId': note.id, 'kind': note.kind,
                         'stationId': note.station_id},
            })
            rows.append((note, token))

    if not messages:
        return result

    try:
        tickets = transport(messages)
    except (URLError, OSError, ValueError) as error:
        # Tarmoq yiqilgan — urinish sanaladi, xabar navbatda qoladi
        logger.warning('Push yuborilmadi: %s', error)
        for note, _token in {id(n): (n, t) for n, t in rows}.values():
            note.push_attempts += 1
            note.push_error = str(error)[:255]
            note.save(update_fields=['push_attempts', 'push_error'])
        result['failed'] += len(rows)
        return result

    return _apply_tickets(rows, tickets, result)


def _apply_tickets(rows, tickets, result):
    """Expo javoblarini xabarlar va tokenlarga tarqatadi."""
    from accounts.models import DeviceToken

    now = timezone.now()
    delivered = set()

    for index, (note, token) in enumerate(rows):
        ticket = tickets[index] if index < len(tickets) else {'status': 'error'}
        if ticket.get('status') == 'ok':
            delivered.add(note.id)
            continue

        message = ticket.get('message', 'xato')
        details = (ticket.get('details') or {}).get('error', '')
        # Token eskirgan bo'lsa uni o'chiramiz: har safar urinish navbatni
        # behuda band qiladi va xato bir xil takrorlanadi
        if details == 'DeviceNotRegistered':
            DeviceToken.objects.filter(token=token).update(
                is_active=False, failed_at=now)
        note.push_error = f'{message} {details}'.strip()[:255]

    for note, _token in rows:
        if note.id in delivered:
            note.pushed_at = now
            note.push_attempts += 1
            note.push_error = ''
            note.save(update_fields=['pushed_at', 'push_attempts', 'push_error'])
            result['sent'] += 1
        else:
            note.push_attempts += 1
            note.save(update_fields=['push_attempts', 'push_error'])
            result['failed'] += 1

    # Bir xabar bir nechta qurilmaga ketishi mumkin — ikki marta sanamaymiz
    result['sent'] = len(delivered)
    result['failed'] = len({n.id for n, _ in rows}) - len(delivered)
    return result
