# -*- coding: utf-8 -*-
"""Push xabarlarni telefonga yetkazish.

Xabar bazaga yozilishi — uni foydalanuvchi ko'rdi degani emas: ilova
yopiq bo'lsa u bexabar qoladi. Bu yerda yetkazish qatlami tekshiriladi.

Asosiy savollar:
  1. Ilova push manzilini saqlay oladimi va u boshqa odamga o'tib
     ketmaydimi?
  2. Xabar navbatdan olinib yuboriladimi va ikki marta yuborilmaydimi?
  3. Sozlama o'chirilgan bo'lsa yuborilmaydimi (lekin ilovada qoladimi)?
  4. Eskirgan token o'chiriladimi?
  5. Tarmoq yiqilsa xabar yo'qolmaydimi va cheksiz urinilmaydimi?

Tarmoqqa chiqilmaydi — yuborish funksiyasi testda almashtiriladi.
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from accounts.models import DeviceToken  # noqa: E402
from management.models import SiteSettings, UserNotification  # noqa: E402
from management.push import MAX_ATTEMPTS, deliver_pending  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    UserNotification.objects.filter(user__username__startswith='__ps').delete()
    DeviceToken.objects.filter(token__startswith='__ps').delete()
    User.objects.filter(username__startswith='__ps').delete()


def api(user):
    client = Client()
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {RefreshToken.for_user(user).access_token}'
    return client


def note_for(user, kind=UserNotification.Kind.STATION_DOWN):
    return UserNotification.objects.create(
        user=user, kind=kind, title='Sinov', body='Sinov xabari')


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f)
             for f in ('push_enabled', 'notify_low_balance')}
    try:
        settings_obj.push_enabled = True
        settings_obj.notify_low_balance = True
        settings_obj.save()

        driver = User.objects.create(username='__ps_driver__')
        other = User.objects.create(username='__ps_other__')

        # ── 1. Manzilni saqlash ─────────────────────────────────
        response = api(driver).post('/api/notifications/device/',
                                    {'token': '__ps_token_1', 'platform': 'android'},
                                    content_type='application/json')
        check('token saqlandi', response.status_code == 200, response.status_code)
        device = DeviceToken.objects.filter(token='__ps_token_1').first()
        check('egasi va platformasi yozildi',
              device.user_id == driver.id and device.platform == 'android')

        check('tokensiz so\'rov rad etildi',
              api(driver).post('/api/notifications/device/', {},
                               content_type='application/json').status_code == 400)
        check('anonim foydalanuvchi saqlay olmadi',
              Client().post('/api/notifications/device/', {'token': '__ps_x'},
                            content_type='application/json').status_code in (401, 403))

        # Telefon boshqa odamga o'tsa — egasi almashadi, nusxa paydo bo'lmaydi
        api(other).post('/api/notifications/device/',
                        {'token': '__ps_token_1', 'platform': 'ios'},
                        content_type='application/json')
        device.refresh_from_db()
        check('token egasi almashdi',
              device.user_id == other.id
              and DeviceToken.objects.filter(token='__ps_token_1').count() == 1)

        api(driver).post('/api/notifications/device/',
                         {'token': '__ps_token_1', 'platform': 'android'},
                         content_type='application/json')

        # ── 2. Yuborish ─────────────────────────────────────────
        sent_batches = []

        def ok_transport(messages):
            sent_batches.append(messages)
            return [{'status': 'ok'} for _ in messages]

        note = note_for(driver)
        result = deliver_pending(transport=ok_transport)
        note.refresh_from_db()
        check('xabar yuborildi', result['sent'] == 1 and note.pushed_at is not None, result)
        check('sarlavha va matn uzatildi',
              sent_batches[0][0]['title'] == 'Sinov'
              and sent_batches[0][0]['to'] == '__ps_token_1', sent_batches[0][0])
        check('ilova uchun ma\'lumot qo\'shildi',
              sent_batches[0][0]['data']['notificationId'] == note.id)

        sent_batches.clear()
        result = deliver_pending(transport=ok_transport)
        check('ikkinchi marta yuborilmadi',
              result['sent'] == 0 and not sent_batches, result)

        # Ikki qurilma — bitta xabar ikkalasiga ham boradi
        DeviceToken.register(driver, '__ps_token_2', 'ios')
        note_for(driver)
        sent_batches.clear()
        result = deliver_pending(transport=ok_transport)
        check('ikkala qurilmaga ham ketdi',
              len(sent_batches[0]) == 2 and result['sent'] == 1, result)

        # ── 3. Sozlama o'chirilgan ──────────────────────────────
        settings_obj.notify_low_balance = False
        settings_obj.save(update_fields=['notify_low_balance'])
        low = note_for(driver, kind='low_balance')
        sent_batches.clear()
        result = deliver_pending(transport=ok_transport)
        low.refresh_from_db()
        check('o\'chirilgan tur yuborilmadi',
              result['skipped'] == 1 and not sent_batches, result)
        check('xabar bazada qoldi (ilovada ko\'rinadi)',
              UserNotification.objects.filter(pk=low.pk).exists())

        settings_obj.push_enabled = False
        settings_obj.save(update_fields=['push_enabled'])
        note_for(driver)
        sent_batches.clear()
        result = deliver_pending(transport=ok_transport)
        check('push umuman o\'chirilganda yuborilmadi',
              result['skipped'] == 1 and not sent_batches, result)
        settings_obj.push_enabled = True
        settings_obj.save(update_fields=['push_enabled'])

        # ── 4. Eskirgan token ───────────────────────────────────
        def dead_transport(messages):
            return [{'status': 'error', 'message': 'not registered',
                     'details': {'error': 'DeviceNotRegistered'}} for _ in messages]

        note_for(driver)
        result = deliver_pending(transport=dead_transport)
        check('eskirgan token o\'chirildi',
              DeviceToken.objects.filter(user=driver, is_active=True).count() == 0,
              DeviceToken.objects.filter(user=driver, is_active=True).count())
        check('yuborilmagan deb belgilandi', result['failed'] == 1, result)

        # Qurilmasiz foydalanuvchi
        note_for(driver)
        result = deliver_pending(transport=ok_transport)
        check('qurilmasiz xabar alohida sanaldi', result['no_device'] >= 1, result)

        # ── 5. Tarmoq yiqilganda ────────────────────────────────
        DeviceToken.register(driver, '__ps_token_3', 'android')

        def broken_transport(messages):
            raise OSError('tarmoq yo\'q')

        pending = note_for(driver)
        deliver_pending(transport=broken_transport)
        pending.refresh_from_db()
        check('tarmoq xatosida xabar yo\'qolmadi',
              pending.pushed_at is None and pending.push_attempts == 1,
              pending.push_attempts)
        check('xato sababi saqlandi', 'tarmoq' in pending.push_error, pending.push_error)

        for _ in range(MAX_ATTEMPTS):
            deliver_pending(transport=broken_transport)
        pending.refresh_from_db()
        sent_batches.clear()
        deliver_pending(transport=ok_transport)
        check('urinishlar tugagach navbatdan chiqdi',
              pending.push_attempts >= MAX_ATTEMPTS and not sent_batches,
              pending.push_attempts)

        # ── 6. Chiqishda token o'chadi ──────────────────────────
        api(driver).delete('/api/notifications/device/',
                           {'token': '__ps_token_3'}, content_type='application/json')
        check('chiqishda token o\'chirildi',
              not DeviceToken.objects.filter(token='__ps_token_3').exists())

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
