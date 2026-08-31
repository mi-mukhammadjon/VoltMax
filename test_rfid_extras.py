# -*- coding: utf-8 -*-
"""RFID kengaytmalari: tahrirlash, tarix, korporativ hisob, ommaviy amal.

Asosiy savollar:
  1. Qurilma topgan egasiz kartaga egani biriktirib bo'ladimi?
  2. Korporativ kartada pul KOMPANIYA hamyonidan yechiladimi?
  3. Bitta karta ikki joyda parallel ishlata olmaydimi (ConcurrentTx)?
  4. Foydalanuvchi o'z kartasini bloklay oladimi va operator blokini ocha
     olmasligi ta'minlanganmi?
  5. Ommaviy amal ishlaydimi?
"""
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from asgiref.sync import async_to_sync  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402

from accounts.models import Company, RfidCard  # noqa: E402
from ocpp_gateway.consumers import OCPPConsumer  # noqa: E402
from sessions_app.models import ChargingSession  # noqa: E402
from stations.models import Connector, Station  # noqa: E402
from wallet.models import WalletBalance  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:54s} {extra}')
    if not condition:
        failures += 1


def _messages(response):
    from django.contrib.messages import get_messages

    return list(get_messages(response.wsgi_request))


def api_client(user):
    from rest_framework_simplejwt.tokens import RefreshToken

    client = Client()
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {RefreshToken.for_user(user).access_token}'
    return client


def _cleanup():
    RfidCard.objects.filter(id_tag__startswith='__RX').delete()
    Company.objects.filter(name__startswith='__rx').delete()
    Station.objects.filter(name__startswith='__rx').delete()
    User.objects.filter(username__startswith='__rx').delete()
    User.objects.filter(username__startswith='company-__rx').delete()


def main():
    _cleanup()

    admin = User.objects.create(username='__rx_admin__', is_staff=True, is_superuser=True)
    driver = User.objects.create(username='__rx_driver__')
    WalletBalance.objects.create(user=driver, amount=100000)

    station = Station.objects.create(
        name='__rx_station__', address='a', latitude=41.0, longitude=69.0,
        power_kw=120, ocpp_id='__RX_CP__',
    )
    connector = Connector.objects.create(
        station=station, label='A', type='DC', power_kw=60, ocpp_connector_id=1)

    consumer = OCPPConsumer()
    consumer.station_id = station.id
    consumer.ocpp_id = station.ocpp_id
    consumer._pending_calls = {}
    consumer._sent_actions = {}

    try:
        with override_settings(ALLOWED_HOSTS=['testserver']):
            panel = Client()
            panel.force_login(admin)

            # ── 1. Egasiz kartaga egani biriktirish ─────────────
            found = RfidCard.objects.create(
                id_tag='__RX_FOUND__', status=RfidCard.Status.PENDING,
                first_seen_station=station)

            page = panel.get(f'/rfid/{found.id}/')
            body = page.content.decode()
            check('karta sahifasi ochildi', page.status_code == 200, page.status_code)

            # Tahrirlash formasi sahifada emas, OYNADA
            check('tahrirlash oynasi bor', 'id="card-edit-modal"' in body)
            check('oyna boshida yopiq', 'id="card-edit-modal" hidden' in body)
            check('ochish tugmasi bor', 'data-modal-open="#card-edit-modal"' in body)
            check("ma'lumot faqat o'qish uchun ko'rsatilgan",
                  'kv-list' in body and 'Pul kimdan yechiladi' in body)
            # Karta nomi katta harfda ko'rinadi (CSS orqali — bazada asl holicha)
            check('karta nomi katta harfda', 'card-name' in body)

            resp = panel.post(f'/rfid/{found.id}/', {
                'id_tag': '__RX_FOUND__', 'label': 'Ali haydovchi',
                'user': str(driver.id), 'status': RfidCard.Status.ACTIVE,
            })

            # Forma xato bo'lsa oyna avtomatik ochilishi kerak — aks holda
            # foydalanuvchi xatoni ko'rmay qolardi
            bad = panel.post(f'/rfid/{found.id}/', {'id_tag': '', 'label': 'X'})
            bad_body = bad.content.decode()
            check('xatoda oyna ochiq qoladi',
                  'id="card-edit-modal" hidden' not in bad_body)
            check("xato oynada ko'rinadi", 'errorlist' in bad_body)
            found.refresh_from_db()
            check('so\'rov qabul qilindi', resp.status_code == 302, resp.status_code)
            check('egasi biriktirildi', found.user_id == driver.id, found.user_id)
            check('nomi saqlandi', found.label == 'Ali haydovchi', found.label)
            check('holat faolga o\'tdi', found.status == RfidCard.Status.ACTIVE)

            # ── 1b. Ro'yxat sahifasi ko'rinishi ────────────────
            import re as _re
            page = panel.get('/rfid/').content.decode()

            # Rejim holati HAR DOIM ko'rinishi kerak — ilgari faqat o'chiq
            # holatda chiqardi va operator nima uchun karta ishlamayotganini
            # tushunmasdi
            check("rejim holati ko'rsatilgan",
                  bool(_re.search(r"Qat'iy rejim (yoqilgan|o'chiq)", page)))

            # Formaning O'ZI ajratiladi: sahifadan belgilangan uzunlikda
            # kesib olish filtr qatoridagi maydonlarni ham qamrab olardi
            add_form = page.split('action="/rfid/new/"')[1].split('</form>')[0]
            check("qo'shish formasida korporativ maydon bor",
                  'name="company"' in add_form)
            # Holat so'ralmaydi — karta har doim tasdiqlanmagan bo'lib qo'shiladi
            check("qo'shish formasida holat so'ralmaydi",
                  'name="status"' not in add_form)
            check('karta raqami katta harfda kiritiladi',
                  'data-uppercase' in add_form and 'uppercase' in add_form)

            # Qo'shilgan karta darhol faol bo'lib qolmasligi kerak
            resp = panel.post('/rfid/new/', {'id_tag': '__rx_new__', 'label': 'Yangi'})
            fresh = RfidCard.objects.get(id_tag='__RX_NEW__')
            check('yangi karta tasdiqlanmagan',
                  fresh.status == RfidCard.Status.PENDING, fresh.status)
            check("karta raqami katta harfga o'girildi",
                  fresh.id_tag == '__RX_NEW__', fresh.id_tag)

            # Muddati tugagan karta "faol" ko'rinmasligi kerak
            from datetime import timedelta as _td
            from django.utils import timezone as _tz

            expired = RfidCard.objects.create(
                id_tag='__RX_EXPIRED__', status=RfidCard.Status.ACTIVE,
                expires_at=_tz.now() - _td(days=1))
            check('muddati tugagan holat haqiqiy',
                  expired.effective_status == 'expired', expired.effective_status)
            check('muddati tugagan yozuvi',
                  expired.effective_status_display == 'Muddati tugagan')

            listing = panel.get('/rfid/?status=expired').content.decode()
            check('muddat filtri ishlaydi', '__RX_EXPIRED__' in listing)
            active_only = panel.get('/rfid/?status=active').content.decode()
            check("faol filtrida muddati tugagani yo'q",
                  '__RX_EXPIRED__' not in active_only)

            row = page.split('<tbody>')[1].split('</tr>')[0]
            buttons = _re.findall(r'class="btn small[^"]*"[^>]*>\s*([^<]+?)\s*<', row)
            check('qatorda ikkita amal', len(buttons) == 2, buttons)
            check('tugma nomlari takrorlanmaydi',
                  len(set(buttons)) == len(buttons), buttons)
            check("qatorda o'chirish yo'q", "O'chirish" not in buttons, buttons)

            head = page.split('<thead>')[1].split('</thead>')[0]
            check('RFID ustunlari mos',
                  len(_re.findall(r'<th[\s>]', head)) == len(_re.findall(r'<td[\s>]', row)),
                  f"th={len(_re.findall(r'<th[\s>]', head))}")

            # ── 2. Korporativ hisob ────────────────────────────
            resp = panel.post('/companies/new/', {
                'name': '__rx_taxi__', 'contact_name': 'Vali',
                'contact_phone': '+998901112233', 'inn': '123456789', 'is_active': 'on',
            })
            company = Company.objects.get(name='__rx_taxi__')
            check('kompaniya yaratildi', resp.status_code == 302, resp.status_code)
            check('hisob foydalanuvchisi bor', company.billing_user_id is not None)
            check('hisob tizimga kira olmaydi', company.billing_user.is_active is False)
            check('hamyon ochildi', company.balance == 0, company.balance)

            WalletBalance.objects.filter(user=company.billing_user).update(amount=500000)

            corp_card = RfidCard.objects.create(
                id_tag='__RX_CORP__', status=RfidCard.Status.ACTIVE,
                user=driver, company=company)
            check('to\'lovchi kompaniya hisobi',
                  corp_card.billing_user == company.billing_user,
                  corp_card.billing_user.username)

            res = async_to_sync(consumer.on_authorize)({'idTag': '__RX_CORP__'})
            check('korporativ karta qabul qilindi',
                  res['idTagInfo']['status'] == 'Accepted', res)

            connector.status = Connector.Status.AVAILABLE
            connector.save(update_fields=['status'])
            session = async_to_sync(consumer._start_live_session)(1, '__RX_CORP__', 0)
            check('sessiya kompaniya hisobiga yozildi',
                  session.user_id == company.billing_user_id, session.user.username)
            check('haydovchi hisobiga yozilmadi', session.user_id != driver.id)

            # Kompaniya to'xtatilsa — pul haydovchidan yechiladi
            company.is_active = False
            company.save(update_fields=['is_active'])
            corp_card.refresh_from_db()
            check("to'xtatilgan kompaniyada egasiga qaytadi",
                  corp_card.billing_user == driver, corp_card.billing_user.username)
            company.is_active = True
            company.save(update_fields=['is_active'])

            # ── 2b. Hamyonni to'ldirish ────────────────────────
            # `refresh_from_db()` bog'langan obyekt keshini tozalamaydi, shuning
            # uchun balansni o'qishdan oldin kompaniya qaytadan olinadi
            company = Company.objects.select_related('billing_user__wallet').get(pk=company.pk)
            before = company.balance
            resp = panel.post(f'/companies/{company.id}/topup/', {
                'amount': "1 500 000", 'reference': "№142 topshiriqnoma",
            })
            company = Company.objects.select_related('billing_user__wallet').get(pk=company.pk)
            check("to'ldirish qabul qilindi", resp.status_code == 302, resp.status_code)
            check('balans oshdi', company.balance == before + 1500000, company.balance)

            last_tx = company.billing_user.transactions.order_by('-created_at').first()
            check("to'lov asosi izohda saqlandi",
                  last_tx and '142' in last_tx.description, last_tx and last_tx.description)
            check("tranzaksiya turi to'g'ri", last_tx.type == 'topup', last_tx.type)

            # Noto'g'ri summa rad etiladi
            before = company.balance
            resp = panel.post(f'/companies/{company.id}/topup/', {'amount': 'abc'})
            company = Company.objects.select_related('billing_user__wallet').get(pk=company.pk)
            texts = [str(m) for m in _messages(resp)]
            check("noto'g'ri summa rad etildi",
                  company.balance == before and any("to'g'ri kiriting" in t for t in texts),
                  texts)

            resp = panel.post(f'/companies/{company.id}/topup/', {'amount': '0'})
            company = Company.objects.select_related('billing_user__wallet').get(pk=company.pk)
            check('nol summa rad etildi', company.balance == before, company.balance)

            # ── 2c. Bank rekvizitlari ──────────────────────────
            check('rekvizitsiz holat aniqlandi', company.has_bank_details is False)

            # Rekvizitlar batafsil sahifadagi o'z bo'limi orqali saqlanadi
            resp = panel.post(f'/companies/{company.id}/edit/requisites/', {
                'legal_name': '"Taksi Park" MChJ', 'inn': '123456789',
                'oked': '49320', 'legal_address': 'Toshkent sh.',
                'director': 'Vali Aliyev',
                'bank_name': 'Kapitalbank', 'bank_account': '20208000900123456789',
                'bank_mfo': '00450',
            })
            company.refresh_from_db()
            check('rekvizitlar saqlandi', resp.status_code == 302, resp.status_code)
            check('STIR saqlandi', company.inn == '123456789', company.inn)
            check('hisob raqami saqlandi',
                  company.bank_account == '20208000900123456789', company.bank_account)
            check("rekvizitlar to'liq deb belgilandi", company.has_bank_details is True)
            check('hisob-faktura nomi yuridik nomdan',
                  company.invoice_name == '"Taksi Park" MChJ', company.invoice_name)

            # Xato uzunlikdagi raqamlar rad etiladi
            resp = panel.post(f'/companies/{company.id}/edit/requisites/',
                              {'inn': '12345'}, follow=True)
            company.refresh_from_db()
            check('qisqa STIR rad etildi',
                  company.inn == '123456789'
                  and 'raqamdan' in resp.content.decode(), company.inn)

            page = panel.get(f'/companies/{company.id}/').content.decode()
            check("detalda to'ldirish formasi bor", 'company_topup' in page or '/topup/' in page)
            # Hisob raqami bo'laklangan holda ko'rsatiladi
            check('detalda rekvizitlar bor', '20208 000 9 00123456 789' in page)

            # ── 2d. Qurilmasiz holat tushunarli aytiladi ───────
            # Stansiyaga OCPP ID berilmagan bo'lsa "topilmadi" degan quruq
            # xabar operatorni nima qilish kerakligidan bexabar qoldirardi
            Station.objects.filter(pk=station.pk).update(ocpp_id=None)
            resp = panel.post('/rfid/push/', {})
            texts = [str(m) for m in _messages(resp)]
            check('qurilmasiz sabab tushuntirildi',
                  any('OCPP Charge Point ID' in t for t in texts), texts)

            page = panel.get('/rfid/').content.decode()
            check('yuborish tugmasi yashirildi', '/rfid/push/' not in page)
            check("ogohlantirish ko'rsatildi", 'charger ulanmagan' in page)

            Station.objects.filter(pk=station.pk).update(ocpp_id='__RX_CP__')
            page = panel.get('/rfid/').content.decode()
            check("qurilma bor bo'lsa tugma qaytdi", '/rfid/push/' in page)

            # ── 2e. Qidiruv ────────────────────────────────────
            # View `q` ni qo'llab-quvvatlardi, lekin shablonda maydon yo'q edi
            page = panel.get('/rfid/').content.decode()
            check('qidiruv maydoni bor', 'type="search"' in page and 'name="q"' in page)
            # Tablar va qidiruv bitta qatorda: chapda tablar, o'ngda qidiruv
            check('filtr qatori bor', 'filter-row' in page)
            check('jonli qidiruv yoqilgan', 'data-live-search' in page)

            # Filtr qatoridagi tartib: qidiruv maydoni -> tugmalar.
            # Korporativ tanlov «Filtr» oynasiga ko'chirildi — qatorda
            # turganda ekran torayishi bilan ikkinchi qatorga tushardi.
            fs = page.split('class="filter-search"')[1].split('</form>')[0]
            order = [
                ('maydon', fs.find('type="search"')),
                ('filtr tugmasi', fs.find('filter-btn')),
                ('yuborish', fs.find('type="submit"')),
            ]
            check('filtr elementlari tartibi',
                  all(pos != -1 for _, pos in order)
                  and [n for n, _ in sorted(order, key=lambda x: x[1])]
                  == ['maydon', 'filtr tugmasi', 'yuborish'],
                  [n for n, _ in sorted(order, key=lambda x: x[1])])
            check("korporativ tanlov oynaga ko'chdi",
                  fs.find('multi-select') > fs.find('card-filter-modal') > 0)

            # JS ishlamasa forma odatdagidek tugma bilan ishlashi kerak
            check('tugma ham qoldi', 'Qidirish</button>' in page)

            # Jonli qidiruv AJAX so'rovi yuboradi — javob to'liq sahifa
            # bo'lishi shart, chunki app.js undan `.layout` ni oladi
            ajax = panel.get('/rfid/?q=__RX_CORP__',
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            body = ajax.content.decode()
            check("AJAX javobi to'g'ri", ajax.status_code == 200
                  and 'class="layout"' in body and '__RX_CORP__' in body,
                  ajax.status_code)
            check('tartib: tablar keyin qidiruv',
                  page.index('filter-tabs') < page.index('filter-search'))

            found_page = panel.get('/rfid/?q=__RX_CORP__').content.decode()
            check("karta raqami bo'yicha topildi", '__RX_CORP__' in found_page)
            check('boshqa kartalar chiqmadi', '__RX_FOUND__' not in found_page)

            by_company = panel.get('/rfid/?q=__rx_taxi__').content.decode()
            check("korporativ mijoz bo'yicha topildi", '__RX_CORP__' in by_company)

            by_owner = panel.get('/rfid/?q=__rx_driver__').content.decode()
            check("egasi bo'yicha topildi", '__RX_CORP__' in by_owner)

            nothing = panel.get('/rfid/?q=__YOQ__').content.decode()
            check('topilmasa xabar chiqadi', 'topilmadi' in nothing)

            # Filtr va qidiruv birga saqlanadi
            both = panel.get('/rfid/?status=active&q=__RX_CORP__').content.decode()
            check('filtr qidiruvni saqlaydi',
                  'status=active&amp;q=' in both or 'q=__RX_CORP__' in both)

            # ── 2e2. Korporativ filtri (ko'p tanlov) ───────────
            other = Company.create_with_account(name='__rx_other__')
            RfidCard.objects.create(id_tag='__RX_OTHER__',
                                    status=RfidCard.Status.ACTIVE, company=other)

            page = panel.get('/rfid/').content.decode()
            check('korporativ tanlagich bor', 'data-multi-select' in page)
            check("mijozlar ro'yxatda", '__rx_taxi__' in page and '__rx_other__' in page)
            check('"korporativ emas" tanlovi bor', 'value="none"' in page)

            one = panel.get(f'/rfid/?company={company.id}').content.decode()
            one_body = one.split('<tbody>')[1].split('</tbody>')[0]
            check("bitta mijoz bo'yicha filtr", '__RX_CORP__' in one_body)
            check('boshqa mijoz chiqmadi', '__RX_OTHER__' not in one_body)

            two = panel.get(f'/rfid/?company={company.id}&company={other.id}').content.decode()
            two_body = two.split('<tbody>')[1].split('</tbody>')[0]
            check('ikkala mijoz ham chiqdi',
                  '__RX_CORP__' in two_body and '__RX_OTHER__' in two_body)

            none_only = panel.get('/rfid/?company=none').content.decode()
            none_body = none_only.split('<tbody>')[1].split('</tbody>')[0]
            check('"korporativ emas" filtri',
                  '__RX_FOUND__' in none_body and '__RX_CORP__' not in none_body)

            mixed = panel.get(f'/rfid/?company=none&company={other.id}').content.decode()
            mixed_body = mixed.split('<tbody>')[1].split('</tbody>')[0]
            check('aralash tanlov ishlaydi',
                  '__RX_OTHER__' in mixed_body and '__RX_FOUND__' in mixed_body
                  and '__RX_CORP__' not in mixed_body)

            # Tanlangan katakchalar sahifada belgilangan holda qaytadi
            check('tanlov saqlanadi',
                  f'value="{other.id}"' in mixed and 'checked' in mixed)

            RfidCard.objects.filter(id_tag='__RX_OTHER__').delete()

            # ── 2f. Muddatni uzaytirish ────────────────────────
            from datetime import timedelta as _td2
            from django.utils import timezone as _tz2

            old_card = RfidCard.objects.create(
                id_tag='__RX_OLD__', status=RfidCard.Status.ACTIVE,
                expires_at=_tz2.now() - _td2(days=30))
            check('boshida muddati tugagan', old_card.is_expired is True)

            panel.post(f'/rfid/{old_card.id}/extend/', {'months': '3'})
            old_card.refresh_from_db()
            check('muddat uzaytirildi', old_card.is_expired is False, old_card.expires_at)
            # Muddati o'tib ketgan kartada sanoq HOZIRDAN boshlanadi
            days = (old_card.expires_at - _tz2.now()).days
            check('sanoq hozirdan boshlandi', 85 < days < 95, days)

            # Hali tugamagan kartani uzaytirish uni QISQARTIRMASLIGI kerak
            before = old_card.expires_at
            panel.post(f'/rfid/{old_card.id}/extend/', {'months': '1'})
            old_card.refresh_from_db()
            check("mavjud muddat ustiga qo'shildi", old_card.expires_at > before,
                  f'{before:%d.%m} -> {old_card.expires_at:%d.%m}')

            panel.post(f'/rfid/{old_card.id}/extend/', {'months': 'clear'})
            old_card.refresh_from_db()
            check('muddat olib tashlandi', old_card.expires_at is None)

            resp = panel.post(f'/rfid/{old_card.id}/extend/', {'months': '99'})
            texts = [str(m) for m in _messages(resp)]
            check("noto'g'ri muddat rad etildi",
                  any('tanlovi' in t for t in texts), texts)

            # Ommaviy uzaytirish
            batch2 = [RfidCard.objects.create(
                id_tag=f'__RX_E{i}__', status=RfidCard.Status.ACTIVE,
                expires_at=_tz2.now() - _td2(days=10)) for i in range(2)]
            panel.post('/rfid/bulk/', {
                'ids': [str(c.id) for c in batch2], 'bulk_action': 'extend', 'months': '6'})
            check('ommaviy uzaytirish ishladi',
                  all(not RfidCard.objects.get(pk=c.pk).is_expired for c in batch2))

            detail = panel.get(f'/rfid/{old_card.id}/').content.decode()
            check('kartada muddat bloki bor', 'Amal qilish muddati' in detail)
            check('tez tanlov tugmalari bor', '+3 oy' in detail and '+1 yil' in detail)

            # ── 2g. Karta sarf hisoboti ────────────────────────
            from dashboard.views_rfid import card_usage

            usage_card = RfidCard.objects.create(
                id_tag='__RX_USAGE__', status=RfidCard.Status.ACTIVE, user=driver)
            plan = [('__rx_st_a__', [(12.5, 18750), (8.0, 12000)]),
                    ('__rx_st_b__', [(20.0, 30000)]),
                    ('__rx_st_c__', [(4.0, 6000)])]
            for st_name, rows in plan:
                st = Station.objects.create(name=st_name, address='a', latitude=41.0,
                                            longitude=69.0, power_kw=60)
                con = Connector.objects.create(station=st, label='A', type='DC', power_kw=60)
                for kwh, cost in rows:
                    ChargingSession.objects.create(
                        user=driver, station=st, connector=con, start_percent=20,
                        power_kw=60, price_per_kwh=1500, connector_label='A',
                        is_live=True, id_tag='__RX_USAGE__', status='completed',
                        final_kwh_charged=kwh, final_cost=cost)

            card_sessions = ChargingSession.objects.filter(id_tag='__RX_USAGE__')
            u2 = card_usage(card_sessions)

            check('sessiyalar sanaldi', u2['count'] == 4, u2['count'])
            check("energiya yig'ildi", abs(u2['kwh'] - 44.5) < 0.01, u2['kwh'])
            check("summa yig'ildi", u2['cost'] == 66750, u2['cost'])
            check("o'rtacha hisoblandi", u2['avg_cost'] == 16688, u2['avg_cost'])
            check('stansiyalar soni', len(u2['stations']) == 3, len(u2['stations']))

            top = u2['stations'][0]
            check("eng ko'p sarflangan birinchi", top['name'] == '__rx_st_a__', top['name'])
            check('bir stansiyaning sessiyalari birlashdi',
                  top['count'] == 2 and top['cost'] == 30750, top)
            check('ustun eng kattasiga nisbatan', top['pct'] == 100, top['pct'])
            check("ulushlar yig'indisi ~100",
                  95 <= sum(r['share'] for r in u2['stations']) <= 105,
                  sum(r['share'] for r in u2['stations']))

            # Ketayotgan sessiya ham hisobga olinishi kerak
            live_station = Station.objects.get(name='__rx_st_c__')
            ChargingSession.objects.create(
                user=driver, station=live_station,
                connector=live_station.connectors.first(), start_percent=20,
                power_kw=60, price_per_kwh=1500, connector_label='A',
                is_live=True, id_tag='__RX_USAGE__', status='charging')
            u3 = card_usage(ChargingSession.objects.filter(id_tag='__RX_USAGE__'))
            check('ketayotgan sessiya ham sanaldi', u3['count'] == 5, u3['count'])

            page = panel.get(f'/rfid/{usage_card.id}/').content.decode()
            check('sahifada sarf bloki bor', 'usage-list' in page)
            check('stansiya nomlari chiqdi',
                  '__rx_st_a__' in page and '__rx_st_b__' in page)
            check("eng ko'p stansiya KPI si",
                  "Eng ko'p stansiya" in page and '__rx_st_a__' in page)

            ChargingSession.objects.filter(id_tag='__RX_USAGE__').delete()
            Station.objects.filter(name__startswith='__rx_st_').delete()

            # Sarfsiz kartada bo'sh holat
            empty_page = panel.get(f'/rfid/{usage_card.id}/').content.decode()
            check("sarfsiz kartada bo'sh holat", 'Hali sarf' in empty_page)

            # ── 3. Bir vaqtda ikki sessiya ─────────────────────
            res = async_to_sync(consumer.on_authorize)({'idTag': '__RX_CORP__'})
            check('parallel sessiya rad etildi',
                  res['idTagInfo']['status'] == 'ConcurrentTx', res)

            session.status = ChargingSession.Status.STOPPED
            session.save(update_fields=['status'])
            res = async_to_sync(consumer.on_authorize)({'idTag': '__RX_CORP__'})
            check('sessiya tugagach yana ishlaydi',
                  res['idTagInfo']['status'] == 'Accepted', res)

            # ── 4. Karta tarixi sahifada ───────────────────────
            body = panel.get(f'/rfid/{corp_card.id}/').content.decode()
            check('tarixda sessiya ko\'rinadi', '__rx_station__' in body)
            check('to\'lovchi hisob ko\'rsatilgan', '__rx_taxi__' in body)

            listing = panel.get('/companies/').content.decode()
            l_head = listing.split('<thead>')[1].split('</thead>')[0]
            l_row = listing.split('<tbody>')[1].split('</tr>')[0]
            check('korporativ ustunlari mos',
                  len(_re.findall(r'<th[\s>]', l_head)) == len(_re.findall(r'<td[\s>]', l_row)),
                  f"th={len(_re.findall(r'<th[\s>]', l_head))} td={len(_re.findall(r'<td[\s>]', l_row))}")
            check('korporativda KPI bor', 'Umumiy balans' in listing)
            # Tahrirlash endi batafsil sahifada, bo'limlar ustida bo'ladi —
            # ro'yxatdagi amal shu sahifaga olib boradi
            check('korporativda amal ustuni bor',
                  'Batafsil' in l_row and 'Hamyon' in l_row)

            comp_page = panel.get(f'/companies/{company.id}/').content.decode()
            check('kompaniya sahifasida karta bor', '__RX_CORP__' in comp_page)
            check('kompaniya sahifasida balans bor', '500' in comp_page)

            # ── 5. Ommaviy amal ────────────────────────────────
            batch = [RfidCard.objects.create(
                id_tag=f'__RX_B{i}__', status=RfidCard.Status.PENDING) for i in range(3)]
            resp = panel.post('/rfid/bulk/', {
                'ids': [str(c.id) for c in batch], 'bulk_action': 'active',
            })
            check('ommaviy tasdiqlash ishladi',
                  RfidCard.objects.filter(
                      id__in=[c.id for c in batch],
                      status=RfidCard.Status.ACTIVE).count() == 3)

            panel.post('/rfid/bulk/', {
                'ids': [str(batch[0].id)], 'bulk_action': 'delete'})
            check('ommaviy o\'chirish ishladi',
                  not RfidCard.objects.filter(pk=batch[0].pk).exists())

            resp = panel.post('/rfid/bulk/', {'bulk_action': 'active'})
            from django.contrib.messages import get_messages
            texts = [str(m) for m in get_messages(resp.wsgi_request)]
            check('bo\'sh tanlovda ogohlantirish',
                  any('belgilanmagan' in t for t in texts), texts)

            # ── 6. Foydalanuvchi o'z kartasini bloklaydi ───────
            mobile = api_client(driver)
            rows = mobile.get('/api/auth/rfid-cards/').json()
            rows = rows.get('results', rows)
            tags = {r['idTag'] for r in rows}
            check('mobil API o\'z kartalarini berdi',
                  '__RX_FOUND__' in tags and '__RX_CORP__' in tags, tags)

            resp = mobile.post(f'/api/auth/rfid-cards/{found.id}/block/',
                               {'block': True}, content_type='application/json')
            found.refresh_from_db()
            check('foydalanuvchi bloklay oldi',
                  found.status == RfidCard.Status.BLOCKED and found.blocked_by_owner,
                  found.status)

            res = async_to_sync(consumer.on_authorize)({'idTag': '__RX_FOUND__'})
            check('bloklangan karta qurilmada ishlamaydi',
                  res['idTagInfo']['status'] == 'Blocked', res)

            resp = mobile.post(f'/api/auth/rfid-cards/{found.id}/block/',
                               {'block': False}, content_type='application/json')
            found.refresh_from_db()
            check('o\'zi bloklaganini ocha oldi',
                  resp.status_code == 200 and found.status == RfidCard.Status.ACTIVE,
                  found.status)

            # Operator bloklasa — foydalanuvchi ocha olmaydi
            panel.post('/rfid/bulk/', {'ids': [str(found.id)], 'bulk_action': 'blocked'})
            found.refresh_from_db()
            check('operator bloki "egasi bloklagan" emas',
                  found.blocked_by_owner is False)

            resp = mobile.post(f'/api/auth/rfid-cards/{found.id}/block/',
                               {'block': False}, content_type='application/json')
            found.refresh_from_db()
            check('operator blokini foydalanuvchi ocha olmadi',
                  resp.status_code == 403 and found.status == RfidCard.Status.BLOCKED,
                  resp.status_code)

            # Begona karta ko'rinmaydi
            stranger = User.objects.create(username='__rx_stranger__')
            rows = api_client(stranger).get('/api/auth/rfid-cards/').json()
            check('begona kartalarni ko\'rmadi',
                  len(rows.get('results', rows)) == 0)

    finally:
        ChargingSession.objects.filter(station__name__startswith='__rx').delete()
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
