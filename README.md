# VoltMax Backend

EV zaryadlash stansiyalarini boshqarish uchun Django backend — xodimlar uchun boshqaruv paneli (dashboard) va mobil ilova uchun REST API.

## Loyiha strukturasi

```
voltmax-backend/
├── voltmax/            # loyiha konfiguratsiyasi (settings, urls, asgi)
├── accounts/           # OTP+JWT autentifikatsiya (Telegram Gateway orqali)
├── stations/           # Station/Connector/StationAmenity modellari + REST API (/api/stations/)
├── sessions_app/       # ChargingSession — mock (simulyatsiya) va real (OCPP) sessiyalar
├── wallet/             # WalletBalance/Transaction
├── ocpp_gateway/       # Real charger'lar uchun OCPP 1.6J WebSocket server (Django Channels)
├── dashboard/          # xodimlar uchun web panel
├── manage.py
└── requirements.txt
```

## Ishga tushirish

```bash
cd voltmax-backend
venv\Scripts\activate          # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

- Panel: http://127.0.0.1:8000/login/
- API: http://127.0.0.1:8000/api/stations/

**Standart admin hisob:** `admin` / `voltmax2026` — **productionga chiqishdan oldin albatta o'zgartiring**
(`python manage.py changepassword admin`).

Namuna stansiyalar (mobil ilovadagi mock data bilan bir xil) qo'shish uchun:
```bash
python manage.py seed_stations
```

## API

| Endpoint | Metod | Tavsif |
|---|---|---|
| `/api/stations/` | GET | Barcha stansiyalar ro'yxati (mobil ilovadagi `StationsAPI.list()`) |
| `/api/stations/<id>/` | GET | Bitta stansiya (mobil ilovadagi `StationsAPI.getById()`) |

Javob formati mobil ilovadagi `src/types/index.ts`'dagi `Station`/`Connector`/`StationAmenity` tiplariga aynan mos (camelCase maydonlar).

## Real EV charger'larni ulash (OCPP 1.6J)

Backend Django Channels orqali OCPP 1.6J (JSON/WebSocket) serverini o'z ichiga oladi —
`python manage.py runserver` shu bilan birga HTTP (REST/dashboard) va WebSocket
(charger ulanishlari) so'rovlarini bitta portda xizmat qiladi (Daphne/ASGI).

**1. Stansiyani charger'ga bog'lash** — dashboard'da stansiyani tahrirlab, `OCPP Charge
Point ID` maydoniga charger'ning o'ziga tanishtiradigan ID'sini kiriting (masalan
`CP-001`), so'ng har bir ulagichga charger tomonidagi raqamli `OCPP connectorId`ni
(masalan `1`, `2`) yozing.

**2. Charger'ni ulash** — jismoniy charger quyidagi manzilga `ocpp1.6` subprotokol bilan
ulanishi kerak:
```
ws://<server-ip>:8000/ws/ocpp/<OCPP_ID>/          # lokal/HTTP
wss://<domen>/ws/ocpp/<OCPP_ID>/                   # productionda (TLS)
```
Charger ulangach BootNotification/Heartbeat/StatusNotification avtomatik qabul
qilinadi; foydalanuvchi zaryadlashni boshlaganda (RFID yoki mobil ilova orqali
dashboard'dagi "Masofadan boshlash" tugmasi) StartTransaction/MeterValues/
StopTransaction orqali `ChargingSession` (`is_live=True`) real vaqtda yoziladi.

**3. Hardware bo'lmasa ham sinash** — o'rnatilgan simulyator to'liq oqimni taqlid qiladi:
```bash
python manage.py simulate_charger CP-001 --connectors 1 --auto-start 1
```
`--url ws://<ip>:8000` bilan boshqa manzilga, `--connectors 1,2` bilan bir nechta
ulagichga ulanish mumkin. `--auto-start` bermasangiz, charger faqat kutib turadi va
dashboard'dagi "Masofadan boshlash" tugmasi orqali (RemoteStartTransaction) ishga tushiriladi.

**Productionda** (bir nechta worker/process bilan scale qilinsa): `settings.py`dagi
`CHANNEL_LAYERS`ni `InMemoryChannelLayer`dan `channels_redis.core.RedisChannelLayer`ga
almashtiring — aks holda "Masofadan boshlash" buyrug'i faqat charger ulangan xuddi shu
worker jarayonida ishlaydi.

## Keyingi qadamlar

- Mobil ilovaning "Zaryadlashni boshlash" oqimini real charger mavjud stansiyalar uchun
  `RemoteStartTransaction`ga ulash (hozircha faqat dashboard'dan qo'lda ishga tushiriladi)
- Productionda `channels_redis` (Redis) bilan ko'p-worker qo'llab-quvvatlashni yoqish
- Production uchun: `.env` fayl yaratish (`.env.example`dan nusxa), `SECRET_KEY`
  almashtirish, Postgres (`DATABASE_URL`) ulash, Railway'ga deploy
  (`Procfile`/`railway.json` — Daphne bilan yangilangan)
