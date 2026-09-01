# Keyingi ishlar

Orqaga surilgan hamma narsa shu yerda. Ro'yxat **tirik**: ish bajarilsa
o'chirilmaydi, `[x]` bilan belgilanadi va sana qo'yiladi — nima qachon
qilingani ko'rinib tursin.

Ikkala repozitoriyni ham qamraydi: `voltmax-backend` va `voltmax-app`.

Oxirgi yangilangan: **01.09.2026**

---

## 1. Sizning tomondan — tashqi imkon kerak

Bularsiz qurilgan narsalarning yarmi ishlamaydi. Holatni tekshirish:
`python manage.py health` yoki panel > **Tizim holati**.

### Joylashtirish (Railway)

- [ ] `SECRET_KEY` — berilmasa server **umuman ishga tushmaydi** (ataylab)
- [ ] `DEBUG=False`
- [ ] `R2_BUCKET` va kalitlari — bo'lmasa stansiya rasmlari, avatarlar va
      zaxira nusxalar **har deploy'da yo'qoladi**
- [ ] `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` — o'z domeningiz
- [ ] Ikkinchi servis: `python manage.py run_workers`, **replica = 1**.
      Usiz parkovka hisoblanmaydi, push ketmaydi, muddati o'tgan sessiya
      to'xtatilmaydi va zaxira nusxa olinmaydi

Batafsil: `DEPLOY.md`.

### Xizmatlar

- [ ] **Panelda saqlangan kartalar ko'rinishi** — operator
      foydalanuvchining nechta kartasi borligini va avtomatik
      to'ldirish yoqilganini ko'ra olmaydi. Shikoyat kelganda («pul
      yechilib ketdi») javob berish qiyin bo'ladi.
      Token EMAS, faqat maskalangan raqam va oxirgi yechimlar

- [ ] **Kartani biriktirish shartnomasi** — Payme Subscribe yoki Click
      Card Token uchun ALOHIDA ruxsat kerak (hozirgi merchant API emas).
      Server tomoni tayyor va soxta provayder bilan sinovdan o'tgan;
      kalitlar kelganda faqat ulanadi.
      **Ogohlantirish:** karta raqami ilovadan serverga, serverdan
      provayderga o'tadi — bu bizni PCI DSS doirasiga kiritadi

- [ ] **Payme/Click** sinov kabineti: webhook manzillarini berish,
      kalitlarni panelga kiritish (Sozlamalar > To'lov tizimlari).
      Eng ko'p kutish talab qiladigan qadam — erta boshlagan ma'qul
- [ ] **Eskiz SMS**: login va parol (Sozlamalar > Xavfsizlik).
      Usiz Telegrami yo'q odam ilovaga **umuman kira olmaydi**
- [ ] **Eskiz'da SMS matnini tasdiqlash** — tasdiqlanmagan matn
      "yuborildi" deb qaytadi-yu, abonentga yetib bormaydi
- [ ] **SMTP** (Sozlamalar > Bildirishnoma): hujjat yuborish, parolni
      tiklash va ogohlantirish shunsiz ishlamaydi
- [ ] **Google Maps kalitini cheklash** (Cloud Console): Android paket
      `uz.voltmax.app` + SHA-1, iOS bundle ID, faqat Maps SDK, billing
      ogohlantirishi. Kalit APK ichida baribir ochiq bo'ladi —
      himoya faqat cheklovda

### Xavfsizlik

- [ ] Standart parolni almashtirish: `manage.py changepassword admin`
- [ ] Administratorlarga **ikki bosqichli kirish** (Profil > Yoqish),
      keyin Sozlamalar > Xavfsizlik da majburiy qilish
- [ ] Har chargerga **OCPP paroli** — parolsiz manzilga uni bilgan har
      kim ulanib, begona hamyondan pul yechishi mumkin

### Tekshirish

- [ ] **EAS build** — push, avatar va SecureStore faqat haqiqiy
      qurilmada tekshiriladi (emulyatorda push tokeni berilmaydi)
- [ ] **Zaxira nusxani TIKLAB ko'rish**. Tiklash sinab ko'rilmagan
      nusxa nusxa emas
- [ ] Bitta haqiqiy charger ulash: simulyator bor, lekin haqiqiy
      qurilma boshqacha xatolar beradi

---

## 2. Ochiq texnik ishlar

- [ ] **Profil sahifasidagi yonga surilish sababi topilmagan.**
      `.main` da `overflow-x: clip` qo'yilgan va u muammoni **yashiradi**,
      tuzatmaydi. Sababni topish: sahifani `?overflow` bilan ochish
      (masalan `/profile/?overflow`) — pastki chap burchakda hisobot
      chiqadi. Vosita himoya to'rini vaqtincha olib o'lchaydi

---

## 3. Kelajakda — shoshilinch emas

Bular hozir kerak emas, lekin vaqti kelganda foydali.

### Ishonchlilik

- [ ] **Redis `CHANNEL_LAYERS`** — server bir nechta jarayonda ishlasa.
      Hozir `InMemoryChannelLayer`: «Masofadan boshlash» buyrug'i faqat
      charger ulangan xuddi shu jarayonda ishlaydi
- [ ] **Sentry** (`SENTRY_DSN`) — xatolar hozir faqat server logiga
      tushadi va odatda hech kim ko'rmaydi
### Mahsulot

- [ ] **Nizo va pul qaytarish oqimi** — mijoz «noto'g'ri pul yechildi»
      desa, hozir operatorda qo'lda hamyonga qo'shishdan boshqa vosita
      yo'q. Haqiqiy mijozlar paydo bo'lgach kerak bo'ladi
- [ ] **Sodiqlik dasturi** — narx tizimi tayyor, uning ustiga qurish
      oson: har N-zaryad chegirmali, do'stni taklif qilish. Bu o'sish
      uchun, ishonchlilik uchun emas
- [ ] **Hamkorlar uchun cheklangan panel** — hamkor faqat o'z
      stansiyasini ko'rsin. Hozir ular panelga umuman kirmaydi, ya'ni
      bu xavf emas; kirish berilsa birinchi navbatda shu kerak

### Sifat

- [ ] **Ilova ekranlarining sinovlari** — hozir faqat mantiq qamralgan
      (57 tekshiruv). Ekranlar React va butun RN muhitini talab qiladi
- [ ] Panelning klaviatura bilan boshqarilishi va ekran o'quvchisi
      uchun moslashuvi

---

## Bajarilganlar

Ro'yxat shu yerdan boshlangan ishlar tarixini saqlaydi.

- [x] **01.09.2026** — Tokenlar apparat himoyasiga (Keychain/Keystore),
      `allowBackup: false`
- [x] **01.09.2026** — Ilova sinovlari (57 tekshiruv) va ular ochgan
      beshta xato
- [x] **01.09.2026** — Aloqasiz holat: saqlangan ma'lumot, sabab,
      o'zi tiklanish
- [x] **01.09.2026** — Panel tezligi: bosh sahifa 44 → 19 so'rov,
      so'rovlar chegarasi sinovi
- [x] **01.09.2026** — Kartani biriktirish, undan to'lash va chegarali
      avtomatik to'ldirish — server va ilova tomoni
- [x] **01.09.2026** — Rad etilgan webhook urinishlari yoziladi va
      Tizim holatida ko'rinadi. Bloklash ATAYLAB qo'shilmadi: panelda
      kalit xato kiritilsa, to'lov tizimining o'z serverini bloklab
      qo'yardik — va kalit tuzatilgandan keyin ham to'lovlar o'tmasdi.
      Bunday "himoya" muammoni tuzatishning o'zini imkonsiz qiladi
