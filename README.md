# VoltMax Backend

Elektromobil zaryadlash tarmog'ini boshqarish tizimi: xodimlar uchun web
panel, mobil ilova uchun REST API va haqiqiy chargerlar bilan ishlaydigan
OCPP 1.6J shlyuzi.

## Loyiha strukturasi

```
voltmax-backend/
├── voltmax/            # sozlamalar, urls, asgi
├── accounts/           # OTP+JWT kirish, mashinalar, RFID kartalar, korporativ mijozlar
├── stations/           # stansiyalar, ulagichlar, profilaktika, zaryadlash qoidalari
├── sessions_app/       # zaryadlash sessiyalari, telemetriya, parkovka hisobi
├── wallet/             # hamyon, tranzaksiyalar, onlayn to'lov (Payme, Click)
├── bookings/           # bronlar va qurilmadagi rezervatsiya
├── ocpp_gateway/       # OCPP 1.6J WebSocket serveri (Django Channels)
├── management/         # sozlamalar, bildirishnomalar, jurnal, davriy vazifalar
└── dashboard/          # xodimlar paneli (shu yerda hujjat generatsiyasi ham)
```

## Ishga tushirish

```bash
cd voltmax-backend
python -m venv venv && venv\Scripts\activate     # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

- Panel: http://127.0.0.1:8000/login/
- API: http://127.0.0.1:8000/api/stations/

Namuna ma'lumot: `python manage.py seed_stations`

> **Standart admin hisobi** — `admin` / `voltmax2026`. Bu parol shu yerda
> ochiq yozilgan, ya'ni parol emas — taklifnoma. Serverga chiqishdan oldin
> albatta almashtiring: `python manage.py changepassword admin`.
> Almashtirilmagani **Tizim holati** sahifasida qizil bo'lib turadi.

Panel logini parol tanlashdan himoyalangan: chegara tugagach kirish
vaqtincha yopiladi (Sozlamalar > Xavfsizlik), har urinish esa yoziladi.
Parol kamida 10 belgi va ichida loyiha nomi bo'lmasligi kerak — hujjatda
yozilgan parol birinchi bo'lib sinab ko'riladi.

Administratorlar uchun **ikki bosqichli kirish** bor (TOTP: Google
Authenticator, Aegis va boshqalar). Profil sahifasidan yoqiladi, zaxira
kodlari bilan. Sozlamalar > Xavfsizlik da uni superuser hisoblar uchun
majburiy qilish mumkin.

## Nima bor

**Panel** — stansiyalar va ulagichlar, sessiyalar va telemetriya, hamyonlar,
RFID kartalar, korporativ mijozlar, profilaktika, hisobotlar, sozlamalar.

Panelda ikki daraja bor: **menejer** kundalik ish bilan, **administrator**
tizimni sozlash bilan shug'ullanadi (sozlamalar, to'lov kalitlari,
hamkorlar bilan hisob-kitob, xodimlar). Menejerga yopiq bo'limlar menyuda
ham ko'rinmaydi.

**Hujjatlar (Word)** — korporativ mijoz bilan shartnoma (matni panelda
tahrirlanadi), to'lov uchun hisob, oylik bajarilgan ishlar dalolatnomasi
va solishtirma dalolatnoma.

**To'lov** — Payme va Click. Balans faqat to'lov tizimi tasdiqlagach oshadi
va takroriy so'rovda ikki marta qo'shilmaydi. Kalitlar panelda saqlanadi
(Sozlamalar > To'lov tizimlari), muhit o'zgaruvchisida emas.

**Bildirishnomalar** — matni panelda tahrirlanadigan shablonlar va
telefonga yetkazish (Expo push).

**Kirish kodlari** ikki kanal orqali: avval Telegram Gateway (arzon),
ishlamasa SMS (Eskiz.uz). Bitta kanal bitta nuqta edi — Telegrami yo'q
odam ilovaga umuman kira olmasdi. Ikkalasi ham Sozlamalar > Xavfsizlik
da sozlanadi va u yerda sinov yuborish tugmasi bor.

**Narx** — to'rt qatlamdan yig'iladi (`stations/pricing.py`): markaziy
standart narx → stansiyaning o'z narxi → vaqtga bog'liq tarif oynasi
(tungi tarif) → aksiya chegirmasi. Narx sessiya boshlanganda muzlatiladi,
shuning uchun tarif yoki aksiya keyin o'zgarsa ham hisob buzilmaydi.
Aksiyalar promo-kodli yoki avtomatik bo'ladi; bir vaqtda bir nechtasi
to'g'ri kelsa mijoz uchun eng foydalisi qo'llanadi va ular qo'shilmaydi.

**Zaryadlash qoidalari** — minimal balans, ish vaqti, bayram kunlari,
sessiya vaqti chegarasi, parkovka imtiyozi va RFID kartaning kunlik/oylik
sarf chegarasi. Ular sozlamada turadi va uch joyda bir xil qo'llanadi:
RFID karta, mobil ilova, panel.

## Davriy vazifalar

Vaqt bo'yicha ishlaydigan hamma narsa bitta jarayonda:

```bash
python manage.py run_workers              # hammasi
python manage.py run_workers --once       # bir marta (tekshirish uchun)
python manage.py run_workers --only push  # faqat bittasi
```

| Vazifa | Oraliq | Nima qiladi |
|---|---|---|
| `parking` | 5 daq | Parkovka daqiqalari uchun pul yechadi |
| `devices` | 2 daq | Charger holatini yangilaydi, nosozlik yozuvlarini yuritadi |
| `overdue` | 5 daq | Vaqt chegarasidan oshgan sessiyani to'xtatadi |
| `push` | 30 son | Bildirishnomalarni telefonlarga yuboradi |
| `bookings` | 5 daq | Muddati o'tgan bronlarni yopadi |
| `cleanup` | kuniga | Eskirgan telemetriya va jurnallarni tozalaydi |
| `backup` | kuniga | Bazaning zaxira nusxasini oladi (R2 sozlangan bo'lsa unga yuklaydi) |

Har vazifa oxirgi marta qachon ishlagani va nima qilgani bazaga
yoziladi. Panelda **Tizim holati** sahifasi shuni ko'rsatadi: vazifa o'z
oralig'idan uch baravar kechiksa — «ishlamayapti». Terminalda:

```bash
python manage.py health            # muammo bo'lsa chiqish kodi 1
python manage.py health --strict   # ogohlantirish ham xato hisoblanadi
```

**Bir vaqtda faqat bitta nusxada ishlashi kerak** (replica = 1). Veb-server
ichiga qo'shib bo'lmaydi: har bir worker mustaqil hisoblab, foydalanuvchidan
ortiqcha pul yechilardi.

Boshqa foydali buyruqlar:

```bash
python manage.py backup_db          # bazaning zaxira nusxasi
python manage.py normalize_phones   # telefon/STIR/hisob raqamlarini tartibga solish
python manage.py simulate_charger CP-001 --connectors 1 --auto-start 1
```

## Sinovlar

Sinovlar oddiy skriptlar — Django test runner'i emas. Har biri o'zi natija
chiqaradi va nima uchun shunday yozilganini izohlaydi:

```bash
python smoke_panel.py       # barcha panel sahifalari ochiladimi
python test_ocpp_flow.py    # ulanishdan pul yechilishigacha to'liq oqim
python test_payments.py     # Payme va Click webhook'lari
python test_mobile_api.py   # ilova ishlatadigan API
python test_pricing.py      # tarif oynalari va aksiyalar
python test_card_limits.py  # kartaning sarf chegarasi
python test_health.py       # tizim holati to'g'ri aniqlanadimi
python test_login_guard.py  # panel logini himoyasi
python test_ocpp_auth.py    # OCPP paroli va to'lov kalitlari
python test_api_hardening.py  # API ruxsatlari va so'rov chegaralari
python test_two_factor.py   # ikki bosqichli kirish
python test_injection.py    # soxta idTag, CSV formulasi, ochiq yo'naltirish
python test_sms.py          # SMS shlyuzi va ikki kanalli yetkazish
```

Hammasini o'tkazish: `for f in smoke_panel.py test_*.py; do python "$f"; done`

Sinovlar **tarmoqqa chiqmaydi**: to'lov tizimlari, Google kalendari va push
xizmati almashtiriladi. Shuning uchun ular tashqi xizmat ishlamay qolganda
ham o'tadi va CI'da maxfiy kalit talab qilmaydi.

Har push'da GitHub Actions ularni avtomatik o'tkazadi
(`.github/workflows/tests.yml`). O'sha yerda `pip-audit` bog'liqliklardagi
ma'lum zaifliklarni ham tekshiradi — u alohida ish sifatida ketadi va
sinovlarni to'sib qo'ymaydi.

## OCPP 1.6J

`runserver` HTTP va WebSocket'ni bitta portda xizmat qiladi (ASGI/Daphne).

**1. Bog'lash** — panelda stansiyaga `OCPP Charge Point ID` (masalan `CP-001`),
har ulagichga esa `OCPP connectorId` (`1`, `2`) beriladi.

**2. Parol** — stansiya sahifasida `OCPP paroli` belgilanadi va xuddi shu
parol charger sozlamasiga kiritiladi. Charger uni handshake'da yuboradi:
`Authorization: Basic base64(<OCPP_ID>:<parol>)`.

Nima uchun: `ocpp_id` maxfiy emas — qurilma ustida yozilgan va odatda
ketma-ket. Parolsiz manzilga uni bilgan har kim ulanib, soxta sessiya
ochib begona hamyondan pul yechishi mumkin edi.

**3. Ulanish** — charger `ocpp1.6` subprotokoli bilan quyidagi manzilga ulanadi:

```
ws://<server>:8000/ws/ocpp/<OCPP_ID>/     # lokal
wss://<domen>/ws/ocpp/<OCPP_ID>/          # serverda (TLS)
```

**4. Hardware'siz sinash** — simulyator to'liq oqimni taqlid qiladi:

```bash
python manage.py simulate_charger CP-001 --connectors 1 --auto-start 1
```

> **Bir nechta jarayonda ishlatilsa** `CHANNEL_LAYERS` ni `InMemoryChannelLayer`
> dan Redis'ga almashtiring — aks holda «Masofadan boshlash» buyrug'i faqat
> charger ulangan xuddi shu jarayonda ishlaydi.

## Serverga joylashtirish

Batafsil: **[DEPLOY.md](DEPLOY.md)** — ikkala servis sozlamasi, to'lov
tizimlarining webhook manzillari, zaxira nusxa va tekshiruv ro'yxati.

Qisqacha: `.env.example` dan nusxa oling, `SECRET_KEY` ni almashtiring,
`DEBUG=False` qo'ying va `DATABASE_URL` (PostgreSQL) ulang. `DEBUG=False`
bo'lganda HTTPS majburiy bo'ladi va cookie'lar `Secure` bayrog'i bilan
yuboriladi.
