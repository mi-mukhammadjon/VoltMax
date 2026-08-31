"""Admin panelning kontent va biznes modellari.

Bu yerdagi modellar faqat panel orqali boshqariladi (Hamkorlar, Aksiyalar,
Bannerlar, FAQ, huquqiy sahifalar, tizim sozlamalari). Mobil ilova ularning
bir qismini keyinchalik API orqali o'qiydi — shuning uchun `is_active` va
tartib maydonlari hammasida bor.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Partner(models.Model):
    """Stansiya egasi bo'lgan tashkilot. Bitta hamkorga bir nechta stansiya tegishli."""

    name = models.CharField('Nomi', max_length=150)
    legal_name = models.CharField('Yuridik nomi', max_length=200, blank=True)
    contact_person = models.CharField("Mas'ul shaxs", max_length=150, blank=True)
    phone = models.CharField('Telefon', max_length=30, blank=True)
    email = models.EmailField('Email', blank=True)
    address = models.CharField('Manzil', max_length=255, blank=True)
    commission_percent = models.PositiveSmallIntegerField(
        'Komissiya (%)', default=0, validators=[MaxValueValidator(100)],
        help_text="VoltMax ushlab qoladigan ulush",
    )
    is_active = models.BooleanField('Faol', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Hamkor'
        verbose_name_plural = 'Hamkorlar'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def station_count(self) -> int:
        return self.stations.count()


class Offer(models.Model):
    """Aksiya/chegirma. Muddat va faollik bo'yicha `is_running` hisoblanadi."""

    class DiscountType(models.TextChoices):
        PERCENT = 'percent', 'Foiz (%)'
        FIXED = 'fixed', "Belgilangan summa (so'm)"

    title = models.CharField('Sarlavha', max_length=150)
    description = models.TextField('Tavsif', blank=True)
    discount_type = models.CharField(
        'Chegirma turi', max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT
    )
    discount_value = models.PositiveIntegerField('Chegirma qiymati', default=0)
    promo_code = models.CharField(
        'Promo-kod', max_length=40, blank=True,
        help_text="Bo'sh bo'lsa aksiya avtomatik qo'llanadi",
    )
    stations = models.ManyToManyField(
        'stations.Station', blank=True, related_name='offers',
        verbose_name='Stansiyalar', help_text="Bo'sh — barcha stansiyalarda amal qiladi",
    )
    starts_at = models.DateTimeField('Boshlanishi', default=timezone.now)
    ends_at = models.DateTimeField('Tugashi', null=True, blank=True)
    is_active = models.BooleanField('Faol', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Aksiya'
        verbose_name_plural = 'Aksiyalar'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._drop_price_cache()

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        self._drop_price_cache()
        return result

    @staticmethod
    def _drop_price_cache():
        """Narx keshini bekor qiladi — aks holda operator aksiyani
        saqlaydi-yu, o'sha so'rovda eski narxni ko'rardi."""
        from stations.pricing import clear_catalogue

        clear_catalogue()

    @property
    def is_running(self) -> bool:
        """Hozir amal qilayotgan aksiyami (faol + muddat ichida)."""
        if not self.is_active:
            return False
        now = timezone.now()
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True

    @property
    def status_label(self) -> str:
        if not self.is_active:
            return "O'chirilgan"
        now = timezone.now()
        if self.starts_at and now < self.starts_at:
            return 'Rejalashtirilgan'
        if self.ends_at and now > self.ends_at:
            return 'Tugagan'
        return 'Amalda'


class Banner(models.Model):
    """Mobil ilovaning bosh ekranidagi reklama banneri."""

    title = models.CharField('Sarlavha', max_length=150)
    subtitle = models.CharField("Qo'shimcha matn", max_length=255, blank=True)
    image = models.ImageField('Rasm', upload_to='banners/%Y/%m/', null=True, blank=True)
    link_url = models.URLField('Havola', blank=True)
    order = models.PositiveSmallIntegerField('Tartib', default=0)
    is_active = models.BooleanField('Faol', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Banner'
        verbose_name_plural = 'Bannerlar'
        ordering = ['order', '-created_at']

    def __str__(self):
        return self.title


class FaqItem(models.Model):
    """Ilovadagi "Ko'p so'raladigan savollar" bo'limi."""

    class Category(models.TextChoices):
        GENERAL = 'general', 'Umumiy'
        CHARGING = 'charging', 'Zaryadlash'
        PAYMENT = 'payment', "To'lov"
        ACCOUNT = 'account', 'Hisob'

    category = models.CharField("Bo'lim", max_length=20, choices=Category.choices, default=Category.GENERAL)
    question = models.CharField('Savol', max_length=255)
    answer = models.TextField('Javob')
    order = models.PositiveSmallIntegerField('Tartib', default=0)
    is_active = models.BooleanField('Faol', default=True)

    class Meta:
        verbose_name = 'FAQ savoli'
        verbose_name_plural = 'FAQ savollari'
        ordering = ['category', 'order']

    def __str__(self):
        return self.question


class LegalPage(models.Model):
    """Maxfiylik siyosati / foydalanish shartlari kabi statik sahifalar."""

    class Slug(models.TextChoices):
        PRIVACY = 'privacy', 'Maxfiylik siyosati'
        TERMS = 'terms', 'Foydalanish shartlari'
        ABOUT = 'about', 'Ilova haqida'

    slug = models.CharField('Sahifa', max_length=20, choices=Slug.choices, unique=True)
    title = models.CharField('Sarlavha', max_length=150)
    body = models.TextField('Matn', blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Huquqiy sahifa'
        verbose_name_plural = 'Huquqiy sahifalar'

    def __str__(self):
        return self.title


class SiteSettings(models.Model):
    """Tizim sozlamalari — yagona yozuv (singleton). `load()` orqali olinadi."""

    # Umumiy
    app_name = models.CharField('Ilova nomi', max_length=100, default='VoltMax')
    support_phone = models.CharField("Qo'llab-quvvatlash telefoni", max_length=30, blank=True)
    support_telegram = models.CharField('Telegram', max_length=100, blank=True)
    maintenance_mode = models.BooleanField(
        'Texnik ishlar rejimi', default=False,
        help_text="Yoqilsa mobil ilovaga tegishli ogohlantirish ko'rsatiladi",
    )

    # ── Tashkilot rekvizitlari ────────────────────────────────────
    # Shartnoma va hisob-fakturada BIZNING tomon sifatida chiqadi.
    # Korporativ mijoz rekvizitlari `accounts.Company` da.
    org_legal_name = models.CharField(
        "Tashkilotning to'liq nomi", max_length=250, blank=True,
        help_text="Shartnomada ko'rsatiladi, masalan: VoltMax MChJ",
    )
    org_inn = models.CharField('Tashkilot STIR', max_length=20, blank=True)
    org_address = models.CharField('Tashkilot manzili', max_length=300, blank=True)
    org_director = models.CharField('Rahbar (F.I.Sh.)', max_length=150, blank=True)
    org_bank_name = models.CharField('Tashkilot banki', max_length=200, blank=True)
    org_bank_account = models.CharField('Tashkilot hisob raqami', max_length=30, blank=True)
    org_bank_mfo = models.CharField('Tashkilot MFO', max_length=10, blank=True)

    # ── Shartnoma shablonining sarlavha qismi ─────────────────────
    # Bo'limlar (shartlar) alohida modelda — `ContractSection`.
    contract_title = models.CharField(
        'Shartnoma sarlavhasi', max_length=200,
        default='ELEKTROMOBILLARNI ZARYADLASH XIZMATLARI SHARTNOMASI',
    )
    contract_city = models.CharField('Tuzilgan joyi', max_length=100, default='Toshkent sh.')
    contract_preamble = models.TextField(
        'Kirish qismi (preambula)',
        default=(
            "{ijrochi} nomidan Ustavga asosan ish yurituvchi rahbar "
            "{ijrochi_rahbari} (keyingi o'rinlarda — «Ijrochi») bir tomondan va "
            "{buyurtmachi} nomidan Ustavga asosan ish yurituvchi rahbar "
            "{buyurtmachi_rahbari} (keyingi o'rinlarda — «Buyurtmachi») ikkinchi "
            "tomondan, quyidagilar to'g'risida ushbu shartnomani tuzdilar:"
        ),
        help_text="O'rin egallovchilar ishlaydi: {ijrochi}, {buyurtmachi} va boshqalar",
    )
    contract_appendix_note = models.CharField(
        'Ilova ostidagi izoh', max_length=300,
        default='Kartalar Buyurtmachiga topshirildi, Buyurtmachi ularni qabul qildi.',
    )

    # ── Bayram kunlari ───────────────────────────────────────────
    # Google'ning ochiq bayramlar kalendari (ICS). Manzil sozlamada turadi:
    # boshqa mamlakat yoki korxonaning o'z kalendari kerak bo'lsa kodni
    # o'zgartirmasdan almashtiriladi.
    holiday_ics_url = models.URLField(
        'Bayramlar kalendari (ICS)', max_length=300, blank=True,
        default='https://calendar.google.com/calendar/ical/'
                'uz.uz%23holiday%40group.v.calendar.google.com/public/basic.ics',
        help_text="Google Calendar'ning ochiq ICS manzili",
    )
    holidays_synced_at = models.DateTimeField(null=True, blank=True)

    # To'lov
    default_price_per_kwh = models.PositiveIntegerField("Standart narx (so'm/kVt·s)", default=1200)
    default_parking_fee_per_min = models.PositiveIntegerField("Parkovka tarifi (so'm/daq)", default=500)
    min_topup = models.PositiveIntegerField("Minimal to'ldirish (so'm)", default=10000)
    max_topup = models.PositiveIntegerField("Maksimal to'ldirish (so'm)", default=5000000)

    # ── Sessiya va parkovka qoidalari ────────────────────────────
    min_balance_to_start = models.PositiveIntegerField(
        "Zaryadlash uchun minimal balans (so'm)", default=0,
        help_text="Balans shundan kam bo'lsa sessiya boshlanmaydi",
    )
    max_session_minutes = models.PositiveSmallIntegerField(
        'Sessiyaning eng uzun davomiyligi (daq)', default=0,
        help_text="0 — cheklanmagan. Unutilgan sessiya kun bo'yi hisoblanib ketmasin",
    )
    parking_grace_minutes = models.PositiveSmallIntegerField(
        'Parkovka imtiyoz vaqti (daq)', default=0,
        help_text='Zaryad tugagach shu vaqt ichida parkovka haqi olinmaydi',
    )

    # Stansiyalarning ish vaqti — bayram kunlari `Holiday` da
    work_all_day = models.BooleanField(
        'Kunu tun ishlaydi', default=True,
        help_text="O'chirilsa quyidagi soatlar amal qiladi",
    )
    work_start = models.TimeField('Ish boshlanishi', default='08:00')
    work_end = models.TimeField('Ish tugashi', default='22:00')

    # Bildirishnoma
    push_enabled = models.BooleanField('Push bildirishnomalar', default=True)
    notify_charging_complete = models.BooleanField('Zaryad tugaganda xabar', default=True)
    notify_parking_started = models.BooleanField('Parkovka boshlanganda xabar', default=True)
    notify_low_balance = models.BooleanField('Balans kamayganda xabar', default=True)

    # Xavfsizlik
    # RFID kartalar: yoqilsa faqat ro'yxatdagi tasdiqlangan kartalar ishlaydi.
    # Standart holatda o'chiq — yangi kartalar avval "tasdiqlanmagan" bo'lib
    # ro'yxatga tushadi, operator ularni ko'rib chiqadi va keyin bu bayroqni
    # yoqadi. Darhol yoqilsa ishlab turgan stansiyada kartalar ishlamay qolardi.
    require_known_rfid = models.BooleanField(
        "Faqat tasdiqlangan RFID kartalar", default=False,
        help_text="Yoqilsa, ro'yxatda yo'q yoki tasdiqlanmagan karta rad etiladi",
    )
    otp_ttl_minutes = models.PositiveSmallIntegerField('OTP amal qilish muddati (daq)', default=5)
    otp_max_attempts = models.PositiveSmallIntegerField('OTP urinishlar chegarasi', default=5)
    session_timeout_minutes = models.PositiveSmallIntegerField(
        'Panel sessiyasi muddati (daq)', default=120, validators=[MinValueValidator(5)]
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tizim sozlamalari'
        verbose_name_plural = 'Tizim sozlamalari'

    def __str__(self):
        return 'Tizim sozlamalari'

    def save(self, *args, **kwargs):
        # Singleton: doim bitta yozuv (pk=1) bo'ladi
        from .current import clear_cached

        self.pk = 1
        super().save(*args, **kwargs)
        # So'rov ichidagi kesh eskirdi — saqlagandan keyin o'sha so'rovda
        # yangi qiymat ko'rinishi kerak
        clear_cached()

    @classmethod
    def load(cls):
        """Sozlamalar yozuvi.

        Bitta so'rov davomida bir marta o'qiladi (`current.py`), so'rov
        tugagach kesh tashlanadi.

        Ilgari u xotirada 5 daqiqa saqlanardi. Ikki jiddiy muammo bor edi:

        1. Xotira JARAYONGA tegishli. Server bir nechta jarayonda ishlaydi
           (Daphne/gunicorn), saqlash esa faqat o'z jarayonidagi nusxani
           yangilardi — qolganlari 5 daqiqagacha eski qiymatni ko'rsatib
           turardi. "Saqladim, lekin o'zgarmadi" shundan kelib chiqardi.
        2. Bir obyekt hamma so'rovlarga qaytarilardi. Forma tekshiruv
           paytida uni JOYIDA o'zgartiradi, ya'ni bir so'rovdagi tugallanmagan
           tahrir boshqasiga ko'rinib qolishi mumkin edi.

        So'rovlar ORASIDA saqlanmaydi: aks holda boshqa jarayondagi
        o'zgarish ko'rinmay qolardi.
        """
        from .current import get_cached, set_cached

        cached = get_cached()
        if cached is not None:
            return cached

        obj, _ = cls.objects.get_or_create(pk=1)
        set_cached(obj)
        return obj


class UserNotification(models.Model):
    """Foydalanuvchiga yuborilgan bildirishnoma.

    Mobil ilovadagi "Bildirishnomalar" ekrani ilgari lentani sessiya/bron/
    tranzaksiyalardan o'zi yig'ardi — ya'ni biz foydalanuvchiga hech narsa
    AYTA olmasdik, faqat u qilgan ishlarni ko'rsatardik. Bu jadval shu
    bo'shliqni to'ldiradi: panel yoki tizim xabar yozib qo'yadi, ilova esa
    uni `/api/notifications/` orqali o'qiydi.
    """

    class Kind(models.TextChoices):
        STATION_DOWN = 'station_down', 'Stansiya ishlamayapti'
        STATION_UP = 'station_up', 'Stansiya tuzatildi'
        SYSTEM = 'system', 'Tizim xabari'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications',
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.SYSTEM)
    title = models.CharField(max_length=150)
    body = models.CharField(max_length=400)

    # Xabar qaysi stansiya haqida — ilova undan detal sahifasiga o'tadi.
    # Stansiya o'chirilsa xabar matni qolaveradi, havola yo'qoladi.
    station = models.ForeignKey(
        'stations.Station', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='notifications',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    # ── Telefonga yetkazish ──────────────────────────────────────
    # Xabar bazaga yozilishi — uni foydalanuvchi KO'RDI degani emas: ilova
    # ochilmasa u xabardan bexabar qoladi. Shuning uchun yuborish holati
    # alohida saqlanadi va navbat orqali qayta urinib ko'riladi.
    pushed_at = models.DateTimeField('Telefonga yuborilgan', null=True, blank=True)
    push_attempts = models.PositiveSmallIntegerField(default=0)
    push_error = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = 'Bildirishnoma'
        verbose_name_plural = 'Bildirishnomalar'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', '-created_at'])]

    def __str__(self):
        return f'{self.user} — {self.title}'

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


# Shartnoma matnida ishlatiladigan o'rin egallovchilar. Ro'yxat panelda
# operatorga ko'rsatiladi, shuning uchun izohlari bilan birga turadi.
CONTRACT_PLACEHOLDERS = [
    ('ijrochi', 'Bizning tashkilot nomi'),
    ('ijrochi_rahbari', 'Bizning rahbar F.I.Sh.'),
    ('buyurtmachi', 'Korporativ mijoz nomi'),
    ('buyurtmachi_rahbari', 'Mijoz rahbari F.I.Sh.'),
    ('narx', "1 kVt·soat narxi (so'm)"),
    ('parkovka', "Parkovka tarifi (so'm/daq)"),
    ('kartalar_soni', 'Mijozga biriktirilgan kartalar soni'),
    ('shahar', 'Shartnoma tuzilgan joy'),
]


class ContractSection(models.Model):
    """Korporativ shartnoma shablonining bitta bo'limi (masalan, «SHARTNOMA PREDMETI»).

    Nima uchun bazada, kodda emas: shartnoma matni yuristning talabi yoki
    qonun o'zgarishi bilan tez-tez tahrirlanadi. Kodda tursa har o'zgarish
    uchun dasturchi va deploy kerak bo'lardi — operator uni panelning
    «Sozlamalar > Shartnoma» bo'limida o'zi tahrirlaydi.

    Bo'lim raqami saqlanmaydi — u faol bo'limlar tartibidan hisoblanadi.
    Shunda o'rtadagi bo'lim o'chirilsa qolganlari o'zi qayta raqamlanadi.

    Matn formati (`body`) — bitta oddiy qoida:
      • har bir satr — alohida band (1.1, 1.2, …);
      • «- » bilan boshlangan satr — oldingi bandning ichki bandi (3.1.1, 3.1.2, …).
    """

    title = models.CharField("Bo'lim sarlavhasi", max_length=200)
    body = models.TextField(
        'Bandlar',
        help_text="Har bir satr — alohida band. «- » bilan boshlangan satr "
                  "oldingi bandning ichki bandi bo'ladi.",
    )
    order = models.PositiveSmallIntegerField('Tartib', default=0)
    is_active = models.BooleanField(
        "Shartnomaga kiritilsin", default=True,
        help_text="O'chirilsa bo'lim saqlanadi, lekin hujjatga tushmaydi",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Shartnoma bo\'limi'
        verbose_name_plural = 'Shartnoma bo\'limlari'
        ordering = ['order', 'id']

    def __str__(self):
        return self.title

    def items(self):
        """Bandlarni `(ichki_bandmi, matn)` juftliklari ko'rinishida qaytaradi."""
        result = []
        for line in self.body.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('-'):
                result.append((True, line.lstrip('-').strip()))
            else:
                result.append((False, line))
        return result

    @property
    def item_count(self) -> int:
        return len(self.items())

    # ── Standart matn ───────────────────────────────────────────
    @classmethod
    def ensure_defaults(cls):
        """Bo'limlar bo'sh bo'lsa standart shartnoma matnini yaratadi.

        Operator matnni buzib qo'ysa yoki noldan boshlamoqchi bo'lsa,
        hammasini o'chirib bu funksiyani qayta chaqirish yetarli.
        """
        if cls.objects.exists():
            return cls.objects.all()
        for order, (title, body) in enumerate(DEFAULT_CONTRACT_SECTIONS, 1):
            cls.objects.create(title=title, body=body, order=order)
        return cls.objects.all()


DEFAULT_CONTRACT_SECTIONS = [
    (
        'SHARTNOMA PREDMETI',
        "Ijrochi Buyurtmachining elektromobillarini o'zining zaryadlash stansiyalarida "
        "zaryadlash xizmatini ko'rsatadi, Buyurtmachi esa ko'rsatilgan xizmat uchun "
        "ushbu shartnoma shartlariga muvofiq haq to'laydi.\n"
        "Xizmatdan foydalanish Ijrochi tomonidan berilgan RFID kartalar va/yoki mobil "
        "ilova orqali amalga oshiriladi.\n"
        "Buyurtmachiga biriktirilgan kartalar ro'yxati ushbu shartnomaning ajralmas "
        "qismi bo'lgan 1-ilovada keltirilgan."
    ),
    (
        "XIZMAT NARXI VA HISOB-KITOB TARTIBI",
        "Zaryadlash xizmatining narxi 1 (bir) kVt·soat uchun {narx} so'mni tashkil etadi.\n"
        "Zaryadlash tugagandan so'ng avtomobil ulagichni band qilib turgan vaqt uchun "
        "har bir daqiqasiga {parkovka} so'm miqdorida parkovka haqi hisoblanadi.\n"
        "Hisob-kitob oldindan to'lov (avans) asosida amalga oshiriladi. Buyurtmachi "
        "Ijrochining hisob raqamiga mablag' o'tkazadi, xizmat qiymati esa har bir "
        "zaryadlash sessiyasidan so'ng shu mablag'dan yechiladi.\n"
        "Avans mablag'i tugagan taqdirda kartalar bo'yicha xizmat ko'rsatish to'xtatiladi "
        "va keyingi to'lovdan so'ng qayta tiklanadi.\n"
        "Ijrochi har oyning oxirida ko'rsatilgan xizmatlar bo'yicha bajarilgan ishlar "
        "dalolatnomasi va hisob-fakturani taqdim etadi.\n"
        "Narxlar Ijrochi tomonidan o'zgartirilishi mumkin. Bu haqda Buyurtmachi kamida "
        "10 (o'n) kalendar kun oldin xabardor qilinadi."
    ),
    (
        'TOMONLARNING HUQUQ VA MAJBURIYATLARI',
        "Ijrochi majburiyatlari:\n"
        "- zaryadlash stansiyalarining uzluksiz ishlashini ta'minlash;\n"
        "- Buyurtmachiga kelishilgan miqdorda RFID kartalar berish;\n"
        "- Buyurtmachining shaxsiy kabinetida sarflangan energiya va mablag' bo'yicha "
        "ma'lumotni real vaqtda taqdim etish;\n"
        "- nosozlik yuzaga kelganda uni imkon qadar qisqa muddatda bartaraf etish.\n"
        "Buyurtmachi majburiyatlari:\n"
        "- xizmat haqini ushbu shartnomada belgilangan tartibda to'lash;\n"
        "- kartalardan faqat o'z avtomobillarini zaryadlash uchun foydalanish;\n"
        "- karta yo'qolgan yoki o'g'irlangan taqdirda darhol Ijrochini xabardor qilish "
        "yoki kartani mobil ilova orqali mustaqil bloklash;\n"
        "- zaryadlash stansiyalaridan foydalanish qoidalariga rioya qilish.\n"
        "Tomonlarning huquqlari:\n"
        "- Ijrochi to'lov muddati buzilgan taqdirda xizmat ko'rsatishni vaqtincha "
        "to'xtatib turishga haqli;\n"
        "- Buyurtmachi istalgan vaqtda kartalar sonini o'zgartirishni yozma murojaat "
        "orqali so'rashga haqli."
    ),
    (
        'TOMONLARNING JAVOBGARLIGI',
        "Tomonlar ushbu shartnoma bo'yicha majburiyatlarini bajarmagan yoki lozim "
        "darajada bajarmagan taqdirda O'zbekiston Respublikasi qonunchiligiga muvofiq "
        "javobgar bo'ladilar.\n"
        "Karta uchinchi shaxs tomonidan ishlatilganligi uchun javobgarlik Buyurtmachi "
        "zimmasida bo'ladi, agar u karta yo'qolgani haqida Ijrochini xabardor qilmagan bo'lsa.\n"
        "Yengib bo'lmas kuch holatlari (fors-major) yuz berganda tomonlar javobgarlikdan "
        "ozod qilinadi."
    ),
    (
        'SHARTNOMA MUDDATI VA BOSHQA SHARTLAR',
        "Ushbu shartnoma imzolangan kundan kuchga kiradi va «__» ____________ 20__ "
        "yilgacha amal qiladi.\n"
        "Tomonlardan biri shartnoma muddati tugashiga 30 (o'ttiz) kun qolganda uni bekor "
        "qilish haqida yozma xabar bermasa, shartnoma keyingi bir yilga avtomatik "
        "uzaytirilgan hisoblanadi.\n"
        "Kelib chiqadigan nizolar muzokaralar yo'li bilan, kelishuvga erishilmagan "
        "taqdirda sud tartibida hal etiladi.\n"
        "Shartnoma ikki nusxada tuzilgan bo'lib, har ikkala nusxa bir xil yuridik kuchga ega."
    ),
]


class Holiday(models.Model):
    """Dam olish (bayram) kuni — kalendarda ajratib ko'rsatiladi.

    Nima uchun bazada saqlanadi, har safar Google'dan olinmaydi: kalendar
    panelning har bir sana maydonida ochiladi va tashqi so'rov sekin ham,
    ishonchsiz ham bo'lardi (internet yo'q bo'lsa kalendar umuman
    chizilmasdi). Google'dan ma'lumot vaqti-vaqti bilan yangilanadi.

    `source` muhim: Google ro'yxati O'zbekistondagi ko'chirilgan ish
    kunlarini har doim ham bilmaydi, shuning uchun operator qo'lda
    qo'shgan kunlar sinxronlashda o'chirilmasligi kerak.
    """

    class Source(models.TextChoices):
        GOOGLE = 'google', 'Google Calendar'
        MANUAL = 'manual', "Qo'lda kiritilgan"

    date = models.DateField('Sana', unique=True)
    name = models.CharField('Nomi', max_length=150)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Bayram kuni'
        verbose_name_plural = 'Bayram kunlari'
        ordering = ['date']

    def __str__(self):
        return f'{self.date:%d.%m.%Y} — {self.name}'


class PaymentProvider(models.Model):
    """To'lov tashkiloti (Payme, Click, Uzum va boshqalar).

    Nima uchun alohida model, sozlamadagi bayroq emas: yangi to'lov
    tizimi qo'shilganda kodni o'zgartirish va deploy qilish kerak bo'lardi.
    Har bir tashkilotning o'z identifikatorlari ham bor — ular bayroq
    bilan birga sig'masdi.

    Kalitlar bazada saqlanadi va panelda ochiq ko'rsatilmaydi: ular pul
    o'tkazmalarini tasdiqlash uchun ishlatiladi, ya'ni parol darajasidagi
    ma'lumot.
    """

    name = models.CharField('Nomi', max_length=100)
    code = models.SlugField(
        'Kod', max_length=40, unique=True,
        help_text="Tizimdagi nomi: payme, click, uzum. Integratsiya shunga qaraydi",
    )
    merchant_id = models.CharField(
        'Merchant / Kassa ID', max_length=100, blank=True,
        help_text="To'lov tashkiloti bergan identifikator",
    )
    secret_key = models.CharField(
        'Maxfiy kalit', max_length=200, blank=True,
        help_text="Panelda to'liq ko'rsatilmaydi",
    )
    endpoint_url = models.URLField('Manzil (endpoint)', max_length=300, blank=True)
    is_active = models.BooleanField(
        'Yoqilgan', default=True,
        help_text="O'chirilsa mobil ilovada bu usul ko'rinmaydi",
    )
    order = models.PositiveSmallIntegerField('Tartib', default=0)
    note = models.CharField('Izoh', max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "To'lov tashkiloti"
        verbose_name_plural = "To'lov tashkilotlari"
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    @property
    def masked_key(self) -> str:
        """Kalitning faqat oxirgi to'rt belgisi — to'g'ri kalit turganini
        tekshirish uchun yetarli, o'g'irlash uchun esa emas."""
        if not self.secret_key:
            return ''
        return '•' * 8 + self.secret_key[-4:]

    @property
    def is_configured(self) -> bool:
        """Ishlashi uchun yetarli ma'lumot bormi."""
        return bool(self.merchant_id and self.secret_key)


class SettingsChange(models.Model):
    """Sozlama o'zgarishlari jurnali.

    Narx yoki «Qat'iy rejim» kabi sozlama butun tizimga ta'sir qiladi.
    Muammo chiqqanda «kim va qachon o'zgartirdi?» degan savolga javob
    bo'lishi kerak — aks holda sababni topish uchun taxmin qilishga
    to'g'ri keladi.
    """

    section = models.CharField("Bo'lim", max_length=40)
    field = models.CharField('Maydon', max_length=60)
    label = models.CharField('Nomi', max_length=150)
    old_value = models.CharField('Eski qiymat', max_length=255, blank=True)
    new_value = models.CharField('Yangi qiymat', max_length=255, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sozlama o'zgarishi"
        verbose_name_plural = "Sozlama o'zgarishlari"
        ordering = ['-changed_at']
        indexes = [models.Index(fields=['-changed_at'])]

    def __str__(self):
        return f'{self.label}: {self.old_value} -> {self.new_value}'


class NotificationTemplate(models.Model):
    """Bildirishnoma matni — panelda tahrirlanadi.

    Nima uchun bazada, kodda emas: xabar matni tez-tez o'zgaradi (uslub,
    qo'shimcha izoh, tilni tekislash), har safar dasturchi va deploy kerak
    bo'lardi. Endi operator uni o'zi yozadi.

    Matnda o'rin egallovchilar ishlatiladi: `{stansiya}`, `{summa}`.
    Ular yuborish paytida haqiqiy qiymatga almashadi; noma'lum nom o'z
    holicha qoladi — xato hujjatda ko'rinadi va tuzatiladi.
    """

    class Event(models.TextChoices):
        STATION_DOWN = 'station_down', 'Stansiya ishlamay qoldi'
        STATION_UP = 'station_up', 'Stansiya tuzatildi'
        CHARGING_COMPLETE = 'charging_complete', 'Zaryad tugadi'
        PARKING_STARTED = 'parking_started', 'Parkovka boshlandi'
        LOW_BALANCE = 'low_balance', 'Balans kamaydi'
        SESSION_TIMEOUT = 'session_timeout', 'Sessiya vaqti tugadi'
        SYSTEM = 'system', 'Umumiy xabar'

    event = models.CharField('Hodisa', max_length=30, choices=Event.choices, unique=True)
    title = models.CharField('Sarlavha', max_length=150)
    body = models.CharField('Matn', max_length=400)
    is_active = models.BooleanField(
        'Yuborilsin', default=True,
        help_text="O'chirilsa bu hodisa bo'yicha xabar yozilmaydi",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Bildirishnoma shabloni'
        verbose_name_plural = 'Bildirishnoma shablonlari'
        ordering = ['event']

    def __str__(self):
        return self.get_event_display()

    # Har hodisada qaysi o'rin egallovchilar mavjudligi — panelda
    # ko'rsatiladi, chunki `{summa}` ni stansiya xabariga yozib bo'lmaydi
    PLACEHOLDERS = {
        Event.STATION_DOWN: ['stansiya', 'ulagich', 'sabab'],
        Event.STATION_UP: ['stansiya', 'ulagich'],
        Event.CHARGING_COMPLETE: ['stansiya', 'kvt', 'summa', 'davomiylik'],
        Event.PARKING_STARTED: ['stansiya', 'tarif', 'daqiqa'],
        Event.LOW_BALANCE: ['balans', 'minimal'],
        Event.SESSION_TIMEOUT: ['stansiya', 'daqiqa'],
        Event.SYSTEM: ['ilova'],
    }

    @property
    def placeholders(self):
        return self.PLACEHOLDERS.get(self.event, [])

    def render(self, values=None):
        """Sarlavha va matnni qiymatlar bilan to'ldiradi."""
        import re

        values = values or {}

        def fill(text):
            return re.sub(
                r'\{(\w+)\}',
                lambda m: str(values.get(m.group(1), m.group(0))),
                text or '',
            )

        return fill(self.title), fill(self.body)

    def sample(self):
        """Namuna qiymatlar bilan ko'rinishi — operator natijani darrov ko'radi."""
        return self.render(SAMPLE_VALUES)

    @classmethod
    def ensure_defaults(cls):
        """Shablonlar bo'sh bo'lsa standart matnlarni yaratadi."""
        for event, title, body in DEFAULT_NOTIFICATIONS:
            cls.objects.get_or_create(
                event=event, defaults={'title': title, 'body': body})
        return cls.objects.all()

    @classmethod
    def for_event(cls, event):
        """Hodisa shabloni. Yo'q bo'lsa standartidan yaratiladi.

        `None` qaytishi — operator bu hodisani o'chirib qo'ygani, ya'ni
        xabar yozilmasligi kerak.
        """
        cls.ensure_defaults()
        template = cls.objects.filter(event=event).first()
        return template if template and template.is_active else None


# Namuna qiymatlar — shablonni tekshirish uchun
SAMPLE_VALUES = {
    'stansiya': 'Chilonzor AZS',
    'ulagich': 'A ulagich',
    'sabab': 'kabel shikastlangan',
    'kvt': '24.50',
    'summa': '29 400.00',
    'davomiylik': '1 soat 12 daq',
    'tarif': '500',
    'daqiqa': '15',
    'balans': '4 200.00',
    'minimal': '10 000.00',
    'ilova': 'VoltMax',
}

DEFAULT_NOTIFICATIONS = [
    (NotificationTemplate.Event.STATION_DOWN,
     '{stansiya} vaqtincha ishlamayapti',
     '{ulagich}: {sabab}'),
    (NotificationTemplate.Event.STATION_UP,
     '{stansiya} yana ishlamoqda',
     '{ulagich} tuzatildi. Zaryadlashni davom ettirishingiz mumkin.'),
    (NotificationTemplate.Event.CHARGING_COMPLETE,
     'Zaryadlash tugadi',
     "{stansiya}: {kvt} kVt·soat olindi, {summa} so'm yechildi ({davomiylik})."),
    (NotificationTemplate.Event.PARKING_STARTED,
     'Parkovka hisoblana boshladi',
     "{stansiya}: zaryad tugadi. Har daqiqa uchun {tarif} so'm olinadi — "
     "avtomobilni bo'shatishni unutmang."),
    (NotificationTemplate.Event.LOW_BALANCE,
     'Balans kamayib qoldi',
     "Hamyoningizda {balans} so'm qoldi. Zaryadlashni davom ettirish uchun "
     "hisobni to'ldiring."),
    (NotificationTemplate.Event.SESSION_TIMEOUT,
     "Zaryadlash avtomatik to'xtatildi",
     "{stansiya}: sessiya {daqiqa} daqiqadan oshdi va to'xtatildi. "
     "Avtomobilni bo'shatishni unutmang — parkovka haqi hisoblanishi mumkin."),
    (NotificationTemplate.Event.SYSTEM,
     '{ilova} xabari',
     'Batafsil ma\'lumot ilovada.'),
]


class ActivityLog(models.Model):
    """Panelda bajarilgan amallar jurnali.

    Sozlama o'zgarishlari alohida yoziladi (`SettingsChange`) — u maydon
    darajasida «eski → yangi» ni saqlaydi. Bu jadval esa AMALLAR uchun:
    karta bloklandi, hamyon to'ldirildi, sessiya majburan to'xtatildi,
    hisob to'langan deb belgilandi.

    Nima uchun kerak: tizimda pul harakati ko'p — onlayn to'lov,
    qaytarish, korporativ hisoblar. Nizo chiqqanda «kim va qachon
    qildi?» degan savolga javob bo'lishi kerak, aks holda taxmin qilishga
    to'g'ri keladi.

    Yozuv hech qachon asosiy amalni to'xtatmaydi: jurnalga yozib
    bo'lmasa, xato logga tushadi va amal davom etadi.
    """

    class Action(models.TextChoices):
        CARD = 'card', 'RFID karta'
        WALLET = 'wallet', 'Hamyon'
        INVOICE = 'invoice', "To'lov hisobi"
        COMPANY = 'company', 'Korporativ mijoz'
        SESSION = 'session', 'Sessiya'
        STATION = 'station', 'Stansiya'
        MAINTENANCE = 'maintenance', 'Profilaktika'
        DEVICE = 'device', 'Qurilma buyrug\'i'
        OTHER = 'other', 'Boshqa'

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Kim')
    action = models.CharField('Bo\'lim', max_length=20, choices=Action.choices,
                              default=Action.OTHER)
    title = models.CharField('Amal', max_length=150)
    detail = models.CharField('Tafsilot', max_length=400, blank=True)

    # Qaysi yozuv ustida — havola qurish uchun (masalan `/rfid/12/`)
    target_url = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Amal yozuvi'
        verbose_name_plural = 'Amallar jurnali'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]

    def __str__(self):
        return f'{self.title} — {self.actor or "tizim"}'


class PartnerPayout(models.Model):
    """Hamkorga oylik hisob-kitob.

    Stansiya hamkorga tegishli, tushum esa bizga keladi: haydovchi
    hamyonidan pul yechiladi. Oy oxirida hamkorga uning ulushini
    o'tkazish kerak — `Partner.commission_percent` biz ushlab qoladigan
    foiz, qolgani hamkorniki.

    Nima uchun alohida yozuv, har safar hisoblab chiqarish emas: to'lov
    qilingandan keyin komissiya foizi o'zgarsa, eski davr ham qayta
    hisoblanib ketardi va hisobot o'zgarib qolardi. Yozuv esa o'sha
    paytdagi holatni muzlatib qo'yadi.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', "To'lanmagan"
        PAID = 'paid', "To'langan"

    partner = models.ForeignKey(Partner, on_delete=models.CASCADE,
                                related_name='payouts', verbose_name='Hamkor')
    year = models.PositiveSmallIntegerField('Yil')
    month = models.PositiveSmallIntegerField('Oy')

    # Hisob o'sha paytdagi holat bilan muzlatiladi
    gross = models.PositiveIntegerField("Umumiy tushum (so'm)", default=0)
    commission_percent = models.PositiveSmallIntegerField('Komissiya (%)', default=0)
    commission = models.PositiveIntegerField("Bizning ulush (so'm)", default=0)
    amount = models.PositiveIntegerField("Hamkorga (so'm)", default=0)
    sessions = models.PositiveIntegerField('Sessiyalar', default=0)
    kwh = models.FloatField('Energiya (kVt·s)', default=0)

    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_ref = models.CharField("To'lov topshiriqnomasi №", max_length=50, blank=True)
    note = models.CharField('Izoh', max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Hamkor hisob-kitobi'
        verbose_name_plural = 'Hamkorlar hisob-kitobi'
        ordering = ['-year', '-month', 'partner__name']
        constraints = [
            # Bir hamkorga bir oy uchun bitta yozuv: aks holda ikki marta
            # to'lab yuborish mumkin bo'lardi
            models.UniqueConstraint(fields=['partner', 'year', 'month'],
                                    name='unique_partner_period'),
        ]

    def __str__(self):
        return f'{self.partner.name} — {self.year}.{self.month:02d}'

    @property
    def is_paid(self) -> bool:
        return self.status == self.Status.PAID
