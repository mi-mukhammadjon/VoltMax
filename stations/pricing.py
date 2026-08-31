# -*- coding: utf-8 -*-
"""Narx qanday hisoblanadi — YAGONA joy.

Ilgari narx ikki qatordan iborat edi: stansiyaning chegirma narxi yoki
sozlamadagi standart narx. Aksiyalar esa panelda yaratilardi-yu, hisobga
umuman qo'shilmasdi — operator aksiya e'lon qilardi, mijoz to'liq narxda
to'lardi. Panelda bor, lekin ishlamaydigan imkoniyat eng yomon holat.

Narx to'rt qatlamdan yig'iladi, shu tartibda:

  1. ASOS      — sozlamalardagi markaziy standart narx
  2. STANSIYA  — stansiyaning o'z narxi (belgilangan bo'lsa) asosni ALMASHTIRADI
  3. TARIF     — kunning soatiga bog'liq oyna (tungi tarif) ham ALMASHTIRADI
  4. AKSIYA    — qolgan narxdan chegirma OLIB TASHLAYDI

`Quote.base` — HAR DOIM markaziy narx. Shuning uchun stansiyaning o'z
arzon narxi ham "chegirma" bo'lib ko'rinadi va ilovada chizib
ko'rsatiladi — foydalanuvchi uchun bu ham chegirma.

Nima uchun aynan shunday tartib: tarif — bu stansiyaning e'lon qilingan
narxi (u ko'rsatkichda turadi), aksiya esa shu narx ustidan beriladigan
imtiyoz. Teskarisi bo'lsa tungi tarif aksiyani "yeb" qo'yardi.

Hamma joy shu modulga murojaat qiladi: mobil ilova, RFID (OCPP), panel va
bron. Shunda ilovada ko'ringan narx bilan hisobdan yechilgan summa bir xil
bo'ladi.
"""
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from django.utils import timezone

# Tarif oynalari va aksiyalar bitta so'rov davomida bir marta o'qiladi.
# Stansiyalar ro'yxatida narx har bir qator uchun hisoblanadi — keshsiz
# 50 ta stansiya 100 ta ortiqcha so'rov degani. Kesh `SiteSettings`
# bilan bir xil qoidada ishlaydi (`management.current` ga qarang):
# so'rov davomida yashaydi, undan tashqarida qisqa muddatdan keyin
# o'z-o'zidan eskiradi.
CATALOGUE_TTL = 30

_catalogue = ContextVar('voltmax_pricing_catalogue', default=None)


def clear_catalogue():
    _catalogue.set(None)


def _load_catalogue():
    entry = _catalogue.get()
    if entry is not None:
        stamp, value = entry
        if time.monotonic() - stamp <= CATALOGUE_TTL:
            return value

    from management.models import Holiday, Offer
    from stations.models import TariffWindow

    windows = list(TariffWindow.objects.filter(is_active=True))
    # Bayramlar faqat kun turi muhim bo'lganda kerak — hech qanday
    # "ish kunlari/dam olish" oynasi bo'lmasa, jadvalga tegilmaydi
    needs_days = any(w.day_kind != TariffWindow.DayKind.EVERY for w in windows)

    value = {
        'windows': windows,
        'offers': list(Offer.objects.filter(is_active=True).prefetch_related('stations')),
        'holidays': (set(Holiday.objects.values_list('date', flat=True))
                     if needs_days else set()),
    }
    _catalogue.set((time.monotonic(), value))
    return value


@dataclass
class Quote:
    """Bir sessiya uchun narx va u qanday chiqqani.

    `price` — to'lanadigan narx, `base` — chegirmasiz narx. Ikkalasi ham
    kerak: chekda va ilovada "1200 → 900" ko'rinishida ko'rsatiladi.
    """

    base: int
    price: int
    tariff: object = None
    offer: object = None
    parts: list = field(default_factory=list)

    @property
    def has_discount(self) -> bool:
        return self.price < self.base

    @property
    def label(self) -> str:
        """Nima uchun shu narx ekanini bir qatorda tushuntiradi."""
        return ' · '.join(self.parts)

    @property
    def saved_per_kwh(self) -> int:
        return max(0, self.base - self.price)


def _settings():
    from management.models import SiteSettings

    return SiteSettings.load()


# ── 1-qatlam: asos ───────────────────────────────────────────────
def base_price(station=None, settings_obj=None) -> int:
    """Markaziy standart narx — hech qanday chegirmasiz.

    Stansiyaning o'z narxi bu yerga KIRMAYDI: u ham chegirma qatlami
    hisoblanadi va chizib ko'rsatiladigan narx aynan shu bo'lishi kerak.
    """
    settings_obj = settings_obj or _settings()
    return settings_obj.default_price_per_kwh


# ── 2-qatlam: tarif oynasi ───────────────────────────────────────
def active_tariff(station, now=None):
    """Shu payt amal qilayotgan tarif oynasi (yo'q bo'lsa `None`).

    Bir necha oyna bir vaqtga tushib qolsa: avval AYNAN SHU stansiyaga
    qo'yilgani, keyin arzoni tanlanadi. Ikkinchi qoida ataylab mijoz
    foydasiga — ikkita e'lon qilingan tarifdan qimmatini olish mijoz
    kutgan narsa emas va nizoga sabab bo'ladi.
    """
    now = now or timezone.localtime()
    catalogue = _load_catalogue()
    candidates = [
        window for window in catalogue['windows']
        if window.station_id in (None, station.pk)
        and window.covers(now, holidays=catalogue['holidays'])
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda w: (w.station_id is None, w.price_per_kwh, w.pk))
    return candidates[0]


# ── 3-qatlam: aksiya ─────────────────────────────────────────────
def _offer_price(offer, price: int) -> int:
    """Aksiya qo'llangandan keyingi narx.

    `FIXED` — kVt·soatdan olib tashlanadigan SO'M (jami summadan emas).
    Narx birligi so'm/kVt·s bo'lgani uchun chegirma ham shu birlikda
    bo'lgani izchil; panelda ham shunday yozilgan.
    """
    from management.models import Offer

    if offer.discount_type == Offer.DiscountType.PERCENT:
        value = min(100, offer.discount_value)
        return round(price * (100 - value) / 100)
    return max(0, price - offer.discount_value)


def available_offers(station, now=None, promo_code=''):
    """Shu stansiyada hozir qo'llash mumkin bo'lgan aksiyalar.

    Promo-kodli aksiya faqat kod kiritilganda qo'shiladi — aks holda kod
    ma'nosini yo'qotardi. Kod katta-kichik harf bilan solishtirilmaydi.
    """
    now = now or timezone.now()
    code = (promo_code or '').strip()

    rows = _load_catalogue()['offers']
    result = []
    for offer in rows:
        if offer.starts_at and now < offer.starts_at:
            continue
        if offer.ends_at and now > offer.ends_at:
            continue
        # Stansiyalar ro'yxati bo'sh — hamma joyda amal qiladi
        linked = [s.pk for s in offer.stations.all()]
        if linked and station.pk not in linked:
            continue
        if offer.promo_code and offer.promo_code.strip().lower() != code.lower():
            continue
        if offer.discount_value <= 0:
            continue
        result.append(offer)
    return result


def best_offer(station, price, now=None, promo_code=''):
    """Mijoz uchun eng foydali aksiya (bir nechtasi mos kelsa).

    Aksiyalar QO'SHILMAYDI — faqat bittasi qo'llanadi. Qo'shilsa narx
    nolga tushib qolishi mumkin va operator buni oldindan ko'rmaydi.
    """
    offers = available_offers(station, now=now, promo_code=promo_code)
    if not offers:
        return None, price

    best, best_price = None, price
    for offer in offers:
        candidate = _offer_price(offer, price)
        if candidate < best_price:
            best, best_price = offer, candidate
    return best, best_price


# ── Yig'indi ─────────────────────────────────────────────────────
def resolve(station, now=None, promo_code='', settings_obj=None) -> Quote:
    """Uch qatlamni birlashtirib yakuniy narxni beradi."""
    settings_obj = settings_obj or _settings()
    now = now or timezone.localtime()

    base = base_price(settings_obj=settings_obj)
    quote = Quote(base=base, price=base)

    # 2-qatlam: stansiyaning o'z narxi. Izohga yozilmaydi — bu doimiy
    # narx, vaqtinchalik chegirma emas; "nima uchun arzon" degan savol
    # unga nisbatan tug'ilmaydi.
    if station.discount_price_per_kwh:
        quote.price = station.discount_price_per_kwh

    window = active_tariff(station, now=now)
    if window is not None:
        quote.tariff = window
        quote.price = window.price_per_kwh
        quote.parts.append(window.name)

    offer, price = best_offer(station, quote.price, now=now, promo_code=promo_code)
    if offer is not None:
        quote.offer = offer
        quote.price = price
        quote.parts.append(offer.title)

    return quote


def check_promo(station, code, now=None):
    """Kiritilgan promo-kod haqiqatmi. `(offer, xato_matni)` qaytaradi.

    Ilova kodni sessiya boshlashdan OLDIN tekshiradi — foydalanuvchi
    zaryadlash tugagach "kod ishlamabdi" degan xabarni ko'rmasligi kerak.
    """
    from management.models import Offer

    code = (code or '').strip()
    if not code:
        return None, 'Promo-kod kiritilmadi'

    offer = Offer.objects.filter(promo_code__iexact=code).first()
    if offer is None:
        return None, 'Bunday promo-kod topilmadi'
    if not offer.is_running:
        return None, f'«{offer.title}» aksiyasi hozir amal qilmaydi'

    linked = [s.pk for s in offer.stations.all()]
    if linked and station is not None and station.pk not in linked:
        return None, 'Bu aksiya boshqa stansiyalarda amal qiladi'

    return offer, None
