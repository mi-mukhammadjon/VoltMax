# Railway'ga joylashtirish

Loyiha **ikkita servis** sifatida ishlaydi: veb-server va davriy vazifalar
ishchisi. Ikkalasi ham bitta repozitoriydan quriladi, farqi — start buyrug'i.

## Nima uchun ikkita servis

Veb-server so'rovlarga javob beradi. Parkovka hisobi, qurilma nazorati,
sessiya vaqti chegarasi va push yuborish esa **vaqt bo'yicha** ishlaydi —
ularni so'rov ichida bajarib bo'lmaydi.

Ular veb-server ichiga qo'shilmaydi: Railway bir nechta nusxada
ishlatganda har bir nusxa mustaqil hisoblab, foydalanuvchidan **ortiqcha
pul yechilardi**. Shu sababli ishchi alohida va **replica = 1**.

## 1. Veb-servis

| Sozlama | Qiymat |
|---|---|
| Start Command | *(bo'sh — Procfile'dagi `web` ishlatiladi)* |
| Replicas | 1 yoki undan ko'p |

`release` bosqichi migratsiya va statik fayllarni o'zi bajaradi.

> Agar Railway'da «Custom Start Command» to'ldirilgan bo'lsa, u Procfile'ni
> **bosib ketadi** va `release` bosqichi ham o'tmasligi mumkin — natijada
> migratsiyalar qo'llanmay, sahifalar xato beradi. Uni bo'sh qoldiring.

## 2. Ishchi servisi

| Sozlama | Qiymat |
|---|---|
| Start Command | `python manage.py run_workers` |
| Replicas | **1 (albatta)** |

Bitta jarayonda to'rtta vazifa ishlaydi:

| Vazifa | Oraliq | Nima qiladi |
|---|---|---|
| `parking` | 5 daq | Parkovka daqiqalari uchun pul yechadi |
| `devices` | 2 daq | Charger holatini yangilaydi, nosozlik yozuvlarini ochadi/yopadi |
| `overdue` | 5 daq | Vaqt chegarasidan oshgan sessiyani to'xtatadi |
| `push` | 30 son | Bildirishnomalarni telefonlarga yuboradi |

Faqat bir qismini ishlatish: `python manage.py run_workers --only push,parking`
Bir marta ishga tushirib tekshirish: `python manage.py run_workers --once`

## 3. Muhit o'zgaruvchilari

Ikkala servisda ham bir xil bo'lishi kerak (`.env.example` ga qarang):
`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`,
Telegram Gateway kaliti va R2 sozlamalari.

**To'lov kalitlari muhit o'zgaruvchisida emas** — ular panelda saqlanadi
(Sozlamalar > To'lov tizimlari), chunki yangi to'lov tizimi qo'shilganda
deploy qilish kerak bo'lmasligi kerak.

## 4. To'lov tizimlarining webhook manzillari

To'lov tizimi kabinetida quyidagilarni ko'rsating:

```
Payme:  https://<domain>/api/payments/payme/
Click:  https://<domain>/api/payments/click/prepare/
        https://<domain>/api/payments/click/complete/
```

Panelda esa (Sozlamalar > To'lov tizimlari):

* **Payme** — Merchant ID va kalit (`Paycom:<kalit>` bilan tekshiriladi);
* **Click** — Merchant ID maydoniga `service_id`, kalit, izohga
  `merchant_id=<raqam>`.

Kalitlar to'ldirilmaguncha tizim ilovada ko'rinmaydi — foydalanuvchini
ishlamaydigan to'lovga yuborgandan ko'ra ko'rsatmagan afzal.

## 5. Joylashtirishdan keyin tekshirish

Eng qisqa yo'l — bitta buyruq:

```bash
python manage.py health
```

U vazifalar, push, to'lov tizimlari va charger ulanishlarini tekshiradi
va muammo bo'lsa **chiqish kodi 1** qaytaradi, ya'ni deploy skriptidan
ham chaqirish mumkin. O'sha ma'lumot panelda ham bor:
**Tizim holati** sahifasi (menyuda) va bosh sahifadagi ogohlantirish.

Eng ko'p uchraydigan holat: `Vazifa «push» — hech qachon ishlamagan`.
Bu ishchi servis ishga tushmaganini bildiradi (2-bo'limga qarang).
Sayt bemalol ochilaveradi, shuning uchun buni faqat shu yerdan bilib
olish mumkin.

Productionga chiqishdan oldin **majburiy** uchtasi:

1. **Standart parolni almashtiring** — `python manage.py changepassword admin`.
   U hujjatlarda ochiq yozilgan.
2. **`DEBUG=False`** — aks holda xato sahifalari kod va sozlamalarni
   ko'rsatib turadi.
3. **`R2_BUCKET`** — sozlanmasa yuklangan stansiya rasmlari va zaxira
   nusxalar serverning diskida qoladi, u esa har deploy'da tozalanadi.

Uchalasi ham `manage.py health` da alohida tekshiriladi.

Qo'shimcha tekshiruvlar:

```bash
python manage.py migrate --check          # migratsiyalar qo'llanganmi
python manage.py run_workers --once       # vazifalar xatosiz o'tadimi
python manage.py normalize_phones         # eski raqamlar tartibda emasmi
```

## 6. Zaxira nusxa

Bazada pul harakati bor — hamyon qoldiqlari, to'lovlar, hisob-kitoblar.
Railway'ning o'z zaxirasi bor, lekin u **platformaga bog'liq**: hisob
yopilsa yoki xizmat ko'chirilsa, nusxa ham yo'qoladi.

```bash
python manage.py backup_db                # backups/ papkasiga
python manage.py backup_db --out /mnt/d   # boshqa diskka
python manage.py backup_db --keep 14      # 14 kunlik nusxalar qoladi
```

Tavsiya: haftada bir marta nusxani **boshqa joyga** (masalan R2 bucket yoki
lokal disk) ko'chiring.

> Nusxa faqat olinsa yetarli emas — uni **tiklab ko'rish** kerak. Tiklash
> sinab ko'rilmagan nusxa nusxa emas. Har chorakda bir marta bo'sh bazaga
> tiklab, panelga kirib ko'ring.

## 7. Xatolar haqida xabar (ixtiyoriy)

`SENTRY_DSN` berilsa istisnolar Sentry'ga yuboriladi. Berilmasa hech
narsa yoqilmaydi va loyiha odatdagidek ishlayveradi.

Foydalanuvchi ma'lumoti (telefon raqami, hamyon holati) **yuborilmaydi** —
`send_default_pii=False`.

## 8. Panel darajalari

Panelda ikki daraja bor:

| Daraja | Nima qila oladi |
|---|---|
| **Menejer** (`is_staff`) | Stansiyalar, sessiyalar, kartalar, mijozlar, profilaktika, hisobotlar |
| **Administrator** (`is_superuser`) | Yuqoridagilarning hammasi + sozlamalar, to'lov tizimlari kalitlari, hamkorlar bilan hisob-kitob, xodimlar va rollar |

Menejerga yopiq bo'limlar menyuda ham ko'rinmaydi.

