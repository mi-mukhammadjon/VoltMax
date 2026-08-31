# -*- coding: utf-8 -*-
"""SMS shlyuzi va kirish kodining ikki kanali.

Kirish kodlari FAQAT Telegram orqali ketardi. Ikki muammo bor edi:

  * Telegrami yo'q odam ilovaga umuman kira olmasdi — va buni operator
    ko'rmaydi ham, odam shunchaki ilovani o'chiradi;
  * bitta kanal — bitta nuqta: hisobda mablag' tugasa yoki xizmat
    ishlamay qolsa, HECH KIM kira olmasdi.

Sinov tarmoqqa CHIQMAYDI: Eskiz javoblari almashtiriladi. Aks holda
sinov begona xizmatga bog'liq bo'lardi va CI'da pul sarflardi.

Asosiy savollar:
  1. Telegram ishlaganda SMS yuborilmaydimi (behuda xarajat)?
  2. Telegram yiqilganda SMS ishga tushadimi?
  3. Ikkalasi ham yiqilsa sabab AYTILADIMI?
  4. Token keshlanadimi va muddati tugaganda yangilanadimi?
  5. Yoqilgan, lekin sozlanmagan shlyuz saqlanadimi (saqlanmasligi kerak)?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from datetime import timedelta  # noqa: E402
from unittest.mock import patch  # noqa: E402

from django.utils import timezone  # noqa: E402

from accounts import otp_delivery  # noqa: E402
from accounts.telegram_gateway import TelegramGatewayError  # noqa: E402
from management import sms  # noqa: E402
from management.models import SiteSettings  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


class FakeResponse:
    """Eskiz javobining o'rnini bosadi."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def main():
    settings_obj = SiteSettings.load()
    saved = {f: getattr(settings_obj, f)
             for f in ('sms_enabled', 'sms_login', 'sms_password', 'sms_sender',
                       'sms_otp_text', 'sms_token', 'sms_token_at')}
    try:
        settings_obj.sms_enabled = True
        settings_obj.sms_login = 'sinov@voltmax.uz'
        settings_obj.sms_password = 'maxfiy'
        settings_obj.sms_sender = 'VoltMax'
        settings_obj.sms_otp_text = ''
        settings_obj.sms_token = ''
        settings_obj.sms_token_at = None
        settings_obj.save()

        # ── 1. Raqam formati ────────────────────────────────────
        check('raqam tozalandi',
              sms.normalize('+998 (90) 123-45-67') == '998901234567',
              sms.normalize('+998 (90) 123-45-67'))
        check('sozlangan deb topildi', sms.is_configured())

        # ── 2. Token olinadi va SAQLANADI ───────────────────────
        # Har SMS uchun qaytadan kirish sekin va keraksiz
        login_calls = []

        def fake_post(url, **kwargs):
            if url.endswith('/auth/login'):
                login_calls.append(url)
                return FakeResponse({'data': {'token': 'sinov-token'}})
            return FakeResponse({'status': 'waiting', 'message': 'ok'})

        with patch('management.sms.requests.post', side_effect=fake_post):
            sms.send('998901234567', 'birinchi')
            sms.send('998901234567', 'ikkinchi')

        settings_obj.refresh_from_db()
        check('token saqlandi', settings_obj.sms_token == 'sinov-token',
              settings_obj.sms_token)
        check('token bir marta olindi', len(login_calls) == 1, len(login_calls))

        # Muddati tugagan token yangilanadi
        settings_obj.sms_token_at = timezone.now() - timedelta(days=30)
        settings_obj.save(update_fields=['sms_token_at'])
        login_calls.clear()
        with patch('management.sms.requests.post', side_effect=fake_post):
            sms.send('998901234567', 'uchinchi')
        check('eskirgan token yangilandi', len(login_calls) == 1, len(login_calls))

        # ── 3. Xizmat rad etsa ──────────────────────────────────
        def rejecting_post(url, **kwargs):
            if url.endswith('/auth/login'):
                return FakeResponse({'data': {'token': 'sinov-token'}})
            return FakeResponse({'status': 'error', 'message': 'balans yetarli emas'},
                                status_code=400)

        with patch('management.sms.requests.post', side_effect=rejecting_post):
            try:
                sms.send('998901234567', 'matn')
                check('rad etilgan SMS xato berdi', False)
            except sms.SmsError as error:
                check('rad etilgan SMS xato berdi', 'balans' in str(error), str(error))

        # Noto'g'ri login: xato tushunarli bo'lishi kerak
        with patch('management.sms.requests.post',
                   return_value=FakeResponse({'message': 'Unauthorized'})):
            try:
                sms.get_token(force_new=True)
                check('noto\'g\'ri login rad etildi', False)
            except sms.SmsError as error:
                check('noto\'g\'ri login rad etildi', 'rad etdi' in str(error),
                      str(error))

        # ── 4. Ikki kanalli yetkazish ───────────────────────────
        settings_obj.sms_token = 'sinov-token'
        settings_obj.sms_token_at = timezone.now()
        settings_obj.save()

        # Telegram ishlaganda SMS ga umuman tegilmasligi kerak — har
        # xabar pul turadi
        with patch('accounts.telegram_gateway.send_verification_code'), \
             patch('management.sms.send') as sms_send:
            channel, _ = otp_delivery.deliver('998901234567', '123456')
            check('Telegram ishlaganda SMS yuborilmadi',
                  channel == otp_delivery.TELEGRAM and not sms_send.called)

        with patch('accounts.telegram_gateway.send_verification_code',
                   side_effect=TelegramGatewayError('hisob bo‘sh')), \
             patch('management.sms.send') as sms_send:
            channel, problems = otp_delivery.deliver('998901234567', '123456')
            check('Telegram yiqilganda SMS ishga tushdi',
                  channel == otp_delivery.SMS and sms_send.called)
            check('Telegram xatosi eslab qolindi',
                  'hisob' in problems.get('telegram', ''), problems)
            check('standart matnda kod bor',
                  '123456' in sms_send.call_args[0][1], sms_send.call_args[0][1])

        # O'z matni qo'llanadimi
        settings_obj.sms_otp_text = 'Kodingiz: {code}. Hech kimga aytmang'
        settings_obj.save(update_fields=['sms_otp_text'])
        with patch('accounts.telegram_gateway.send_verification_code',
                   side_effect=TelegramGatewayError('yo‘q')), \
             patch('management.sms.send') as sms_send:
            otp_delivery.deliver('998901234567', '654321')
            check('sozlamadagi matn ishlatildi',
                  sms_send.call_args[0][1] == 'Kodingiz: 654321. Hech kimga aytmang',
                  sms_send.call_args[0][1])

        # ── 5. Ikkalasi ham yiqilsa ─────────────────────────────
        with patch('accounts.telegram_gateway.send_verification_code',
                   side_effect=TelegramGatewayError('tg yiqildi')), \
             patch('management.sms.send', side_effect=sms.SmsError('sms yiqildi')):
            try:
                otp_delivery.deliver('998901234567', '111111')
                check('ikkalasi yiqilganda xato tashlandi', False)
            except otp_delivery.DeliveryError as error:
                check('ikkalasi yiqilganda xato tashlandi', True)
                check('ikkala sabab ham aytildi',
                      'tg yiqildi' in str(error) and 'sms yiqildi' in str(error),
                      str(error))

        # ── 6. SMS o'chirilgan bo'lsa ───────────────────────────
        settings_obj.sms_enabled = False
        settings_obj.save(update_fields=['sms_enabled'])
        with patch('accounts.telegram_gateway.send_verification_code',
                   side_effect=TelegramGatewayError('yo‘q')):
            try:
                otp_delivery.deliver('998901234567', '222222')
                check('SMS o\'chiq bo\'lsa yetkazilmadi', False)
            except otp_delivery.DeliveryError as error:
                check('SMS o\'chiq bo\'lsa yetkazilmadi',
                      'sozlanmagan' in str(error), str(error))

    finally:
        for field, value in saved.items():
            setattr(settings_obj, field, value)
        settings_obj.save()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
