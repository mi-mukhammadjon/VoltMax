# -*- coding: utf-8 -*-
"""Kartani biriktirish, undan to'lash va avtomatik to'ldirish.

Bu loyihadagi eng qimmat xato qilinadigan joy: karta ma'lumoti va pul
yechish huquqi. Shuning uchun sinov ikki narsani tekshiradi — oqim
to'g'ri ishlashini VA maxfiy ma'lumot hech qayerda qolmasligini.

Eng muhim tekshiruv — KARTA RAQAMI bazada, logda va javoblarda yo'q.
U faqat provayderga uzatiladi va o'sha yerda qoladi.

Tarmoqqa CHIQMAYDI: soxta adapter ishlatiladi (`fake`).

Asosiy savollar:
  1. Karta raqami bazaga tushadimi (tushmasligi kerak)?
  2. Token shifrlanadimi va ilovaga chiqadimi (chiqmasligi kerak)?
  3. Tasdiqlanmagan karta bilan pul yechib bo'ladimi?
  4. Begona odam boshqa kartani ishlata oladimi?
  5. Avtomatik to'ldirish chegaralarga bo'ysunadimi?
  6. Ishlamaydigan karta bilan cheksiz urinaveradimi?
"""
import io
import logging
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import timedelta  # noqa: E402

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from management.models import PaymentProvider, SiteSettings, UserNotification  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Station  # noqa: E402
from wallet import autotopup, cards as card_flow  # noqa: E402
from wallet.card_crypto import brand_of, decrypt, mask_pan  # noqa: E402
from wallet.models import AutoTopUp, PaymentOrder, SavedCard, WalletBalance  # noqa: E402

failures = 0

PAN = '8600123456789012'
BAD_PAN = '8600000000009999'      # soxta adapter buni har doim rad etadi
CODE = '000000'


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    AutoTopUp.objects.filter(user__username__startswith='__cd').delete()
    SavedCard.objects.filter(user__username__startswith='__cd').delete()
    PaymentOrder.objects.filter(user__username__startswith='__cd').delete()
    ChargingSession.objects.filter(station__name__startswith='__cd').delete()
    Station.objects.filter(name__startswith='__cd').delete()
    UserNotification.objects.filter(user__username__startswith='__cd').delete()
    User.objects.filter(username__startswith='__cd').delete()
    PaymentProvider.objects.filter(code='fake').delete()


def api(user):
    client = Client()
    client.defaults['HTTP_AUTHORIZATION'] = (
        f'Bearer {RefreshToken.for_user(user).access_token}')
    return client


@override_settings(ALLOWED_HOSTS=['testserver'], DEBUG=True)
def main():
    _cleanup()

    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f) for f in ('min_topup', 'max_topup')}
    try:
        settings_obj.min_topup = 5000
        settings_obj.max_topup = 1000000
        settings_obj.save()

        # Soxta provayder: shartnoma va sinov kabineti bo'lmaganda ham
        # butun oqimni tekshirish kerak
        provider = PaymentProvider.objects.create(
            code='fake', name='Sinov', merchant_id='1', secret_key='x',
            is_active=True)

        driver = User.objects.create(username='__cd_driver__')
        WalletBalance.objects.create(user=driver, amount=0)
        client = api(driver)

        # ── 1. Biriktirish ──────────────────────────────────────
        added = client.post('/api/wallet/cards/',
                            {'provider': 'fake', 'pan': PAN, 'expiry': '12/29'},
                            content_type='application/json')
        check('karta biriktirildi', added.status_code == 201, added.content[:120])

        payload = added.json()
        check('faqat oxirgi 4 raqam qaytdi',
              payload.get('maskedPan') == '**** 9012', payload.get('maskedPan'))
        check('karta turi aniqlandi', payload.get('brand') == 'uzcard',
              payload.get('brand'))
        check('holat "tasdiqlanmagan"',
              payload.get('state') == SavedCard.State.PENDING, payload.get('state'))

        # ENG MUHIMI: token ILOVAGA chiqmasligi kerak — u telefondan
        # o'g'irlanishi mumkin bo'lardi
        check('token javobda yo‘q', 'token' not in str(payload).lower(), payload)

        card = SavedCard.objects.get(pk=payload['id'])

        # ── 2. Karta raqami hech qayerda yo'q ───────────────────
        # Bu sinovning eng muhim qismi. Raqam bazaga tushsa, uni
        # keyin ham topib bo'lmaydi — zaxira nusxalarda ham qoladi.
        row = {field.name: str(getattr(card, field.name))
               for field in SavedCard._meta.fields}
        check('karta raqami YOZUVDA yo‘q',
              not any(PAN in value for value in row.values()), row)
        check('raqamning bir qismi ham yo‘q',
              not any('86001234' in value for value in row.values()))

        # Token shifrlangan: baza nusxasi oshkor bo'lsa u o'qilmaydi
        check('token shifrlangan',
              card.token_encrypted and 'fake-9012' not in card.token_encrypted,
              card.token_encrypted[:40])
        check('shifr ochiladi', card.token == 'fake-9012-1229', card.token)

        # ── 3. Tasdiqlanmagan karta bilan to'lab bo'lmaydi ──────
        early = client.post(f'/api/wallet/cards/{card.pk}/charge/',
                            {'amount': 50000}, content_type='application/json')
        check('tasdiqlanmagan karta bilan to‘lab bo‘lmadi',
              early.status_code == 400, early.status_code)

        # ── 4. Tasdiqlash ───────────────────────────────────────
        wrong = client.post(f'/api/wallet/cards/{card.pk}/verify/',
                            {'code': '111111'}, content_type='application/json')
        check('noto‘g‘ri kod rad etildi', wrong.status_code == 400, wrong.status_code)

        good = client.post(f'/api/wallet/cards/{card.pk}/verify/',
                           {'code': CODE}, content_type='application/json')
        card.refresh_from_db()
        check('kod bilan tasdiqlandi',
              good.status_code == 200 and card.state == SavedCard.State.ACTIVE,
              card.state)
        check('birinchi karta o‘zi asosiy bo‘ldi', card.is_default)

        # ── 5. To'lash ──────────────────────────────────────────
        paid = client.post(f'/api/wallet/cards/{card.pk}/charge/',
                           {'amount': 50000}, content_type='application/json')
        check('kartadan to‘landi', paid.status_code == 201, paid.content[:120])
        check('hamyon to‘ldi', paid.json().get('balance') == 50000,
              paid.json().get('balance'))

        wallet = WalletBalance.objects.get(user=driver)
        check('balans bazada ham o‘sdi', wallet.amount == 50000, wallet.amount)

        order = PaymentOrder.objects.filter(user=driver).first()
        check('to‘lov qo‘lda deb belgilandi', order and not order.is_auto)

        small = client.post(f'/api/wallet/cards/{card.pk}/charge/',
                            {'amount': 1000}, content_type='application/json')
        check('chegaradan kam summa rad etildi', small.status_code == 400,
              small.status_code)

        # ── 6. Begona karta ─────────────────────────────────────
        stranger = User.objects.create(username='__cd_begona__')
        theirs = api(stranger)
        check('begona karta bilan to‘lab bo‘lmadi',
              theirs.post(f'/api/wallet/cards/{card.pk}/charge/',
                          {'amount': 50000},
                          content_type='application/json').status_code == 404)
        check('begona kartani o‘chirib bo‘lmadi',
              theirs.delete(f'/api/wallet/cards/{card.pk}/').status_code == 404)
        check('begona kartani ro‘yxatda ko‘rmadi',
              theirs.get('/api/wallet/cards/').json()['results'] == [])

        # ── 7. Avtomatik to'ldirish ─────────────────────────────
        setup = client.put('/api/wallet/auto-topup/',
                           {'cardId': card.pk, 'amount': 50000, 'threshold': 20000},
                           content_type='application/json')
        check('avtomatik to‘ldirish yoqildi', setup.status_code == 200,
              setup.content[:120])

        # Chegara summadan katta bo'lsa halqa hosil bo'lardi
        loop = client.put('/api/wallet/auto-topup/',
                          {'cardId': card.pk, 'amount': 20000, 'threshold': 30000},
                          content_type='application/json')
        check('halqa hosil qiluvchi sozlama rad etildi', loop.status_code == 400,
              loop.status_code)

        rule = AutoTopUp.objects.get(user=driver)

        # Zaryadlash bo'lmasa ishlamasligi kerak: ilovani ochmagan
        # odamning kartasidan pul yechish kutilmagan bo'lardi
        wallet.amount = 5000
        wallet.save()
        charged, _failed = autotopup.run_once()
        check('zaryadlashsiz to‘ldirilmadi', charged == 0, charged)

        station = Station.objects.create(
            name='__cd Stansiya', address='a', latitude=41.0, longitude=69.0,
            charger_type='DC', power_kw=60)
        connector = Connector.objects.create(station=station, label='A',
                                             type='ccs2', power_kw=60)
        ChargingSession.objects.create(
            user=driver, station=station, connector=connector, start_percent=10,
            power_kw=60, price_per_kwh=1000, connector_label='A',
            status=ChargingSession.Status.CHARGING)

        charged, _failed = autotopup.run_once()
        wallet.refresh_from_db()
        check('zaryadlash paytida to‘ldirildi',
              charged == 1 and wallet.amount == 55000, wallet.amount)

        auto_order = PaymentOrder.objects.filter(user=driver, is_auto=True).first()
        check('to‘lov avtomatik deb belgilandi', auto_order is not None)

        # Har yechimdan keyin DARHOL xabar: jimgina yechilgan pul
        # ishonchni yo'qotadi
        note = UserNotification.objects.filter(
            user=driver, title__icontains='avtomatik').first()
        check('foydalanuvchiga xabar berildi', note is not None,
              note.title if note else None)
        check('xabarda karta va summa bor',
              note and '9012' in note.body and '50' in note.body,
              note.body if note else '')

        # Balans chegaradan yuqori bo'lsa qayta yechilmasligi kerak
        charged, _failed = autotopup.run_once()
        check('balans yetarli bo‘lganda yechilmadi', charged == 0, charged)

        # ── 8. Kunlik chegara ───────────────────────────────────
        wallet.amount = 1000
        wallet.save()
        rule.daily_limit = 60000        # 50 000 allaqachon yechilgan
        rule.save()
        check('kunlik chegara to‘sdi',
              rule.blocked_reason() == 'kunlik chegara', rule.blocked_reason())

        charged, _failed = autotopup.run_once()
        check('chegara oshganda yechilmadi', charged == 0, charged)

        rule.daily_limit = 500000
        rule.save()

        # ── 9. Ishlamaydigan karta ──────────────────────────────
        # Ketma-ket xatolardan keyin o'chishi kerak: tinmay urinish
        # bankdan bloklashga olib keladi
        bad = client.post('/api/wallet/cards/',
                          {'provider': 'fake', 'pan': BAD_PAN, 'expiry': '12/29'},
                          content_type='application/json')
        bad_card = SavedCard.objects.get(pk=bad.json()['id'])
        client.post(f'/api/wallet/cards/{bad_card.pk}/verify/', {'code': CODE},
                    content_type='application/json')
        bad_card.refresh_from_db()

        rule.card = bad_card
        rule.fail_streak = 0
        rule.is_active = True
        rule.save()

        for _ in range(AutoTopUp.MAX_FAILS):
            wallet.amount = 1000
            wallet.save()
            autotopup.run_once()

        rule.refresh_from_db()
        check('ketma-ket xatodan keyin o‘chdi', not rule.is_active,
              f'{rule.fail_streak} ta xato')
        check('sabab saqlandi', bool(rule.last_error), rule.last_error)

        off_note = UserNotification.objects.filter(
            user=driver, title__icontains='o‘chirildi').first()
        check('o‘chgani haqida xabar berildi', off_note is not None)

        # ── 10. O'chirish ───────────────────────────────────────
        removed = client.delete(f'/api/wallet/cards/{card.pk}/')
        check('karta o‘chirildi',
              removed.status_code == 204
              and not SavedCard.objects.filter(pk=card.pk).exists())

        # ── 11. Yordamchi funksiyalar ───────────────────────────
        check('maskalash to‘g‘ri', mask_pan(PAN) == '**** 9012', mask_pan(PAN))
        check('qisqa raqam ham xavfsiz', mask_pan('12') == '****')
        check('Humo tanildi', brand_of('9860111122223333') == 'humo')
        check('buzuq shifr bo‘sh qaytardi', decrypt('yolgon') == '')

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
