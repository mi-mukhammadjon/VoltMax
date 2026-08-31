from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Avg
from django.utils import timezone
from django.utils.functional import cached_property

# Charger haqiqiy hayotda shu oraliqda kamida bitta xabar (Heartbeat yoki boshqa)
# yubormasa, "oflayn" deb hisoblanadi. BootNotification'da chargerga aytiladigan
# heartbeatInterval (ocpp_gateway/consumers.py) dan katta bo'lishi kerak.
ONLINE_THRESHOLD = timedelta(seconds=180)


class Station(models.Model):
    """Bitta EV zaryadlash stansiyasi — VoltMax mobil ilovasining Station tipiga mos."""

    class ChargerType(models.TextChoices):
        AC = 'AC', 'AC'
        DC = 'DC', 'DC'

    class Status(models.TextChoices):
        AVAILABLE = 'available', "Bo'sh"
        BUSY = 'busy', 'Band'
        OFFLINE = 'offline', 'Ishlamayapti'

    name = models.CharField(max_length=150)
    address = models.CharField(max_length=255)
    latitude = models.FloatField()
    longitude = models.FloatField()

    charger_type = models.CharField(max_length=2, choices=ChargerType.choices, default=ChargerType.DC)
    power_kw = models.PositiveIntegerField(help_text='Stansiyaning umumiy quvvati (kVt)')
    # Standart narx STANSIYADA saqlanmaydi — u markazlashgan holda
    # Sozlamalar > To'lov > "Standart narx" dan olinadi (SiteSettings).
    # Bu yerda faqat shu stansiyaga xos chegirma narxi turadi; bo'sh bo'lsa
    # stansiya standart narxda ishlaydi. Shu sabab markaziy narx o'zgarsa,
    # chegirmasiz barcha stansiyalar darhol yangi narxga o'tadi.
    discount_price_per_kwh = models.PositiveIntegerField(
        "Chegirmali narx (so'm/kVt·s)", null=True, blank=True,
        help_text="Bo'sh qoldirilsa — sozlamalardagi standart narx qo'llanadi",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AVAILABLE)
    rating = models.FloatField(null=True, blank=True)
    photo = models.ImageField(upload_to='stations/%Y/%m/', null=True, blank=True)

    # Haqiqiy charger OCPP orqali ulanganda o'zini shu ID bilan tanishtiradi:
    # wss://<host>/ws/ocpp/<ocpp_id>/. Bo'sh bo'lsa — stansiya hali jismoniy
    # charger'ga ulanmagan (faqat qo'lda/mock boshqariladi).
    ocpp_id = models.CharField(
        max_length=100, unique=True, null=True, blank=True,
        help_text="Charger o'zini WebSocket ulanishda shu ID bilan tanishtiradi (masalan: CP-001)",
    )
    ocpp_last_seen_at = models.DateTimeField(null=True, blank=True)

    # Stansiya egasi bo'lgan tashkilot (panel > Hamkorlar). Bo'sh — VoltMax'ning o'zi.
    partner = models.ForeignKey(
        'management.Partner', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='stations', verbose_name='Hamkor',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Stansiya'
        verbose_name_plural = 'Stansiyalar'
        ordering = ['name']

    def __str__(self):
        return self.name

    # ── Narx ──────────────────────────────────────────────────────
    # Quyidagi uchta xossa eski maydon nomlarini saqlab qoladi, shuning uchun
    # serializer, shablon va sessiya kodi o'zgarishsiz ishlayveradi.

    @property
    def standard_price_per_kwh(self) -> int:
        """Sozlamalardagi markaziy narx (barcha stansiyalar uchun bir xil)."""
        from management.models import SiteSettings

        return SiteSettings.load().default_price_per_kwh

    @property
    def price_per_kwh(self) -> int:
        """Foydalanuvchi to'laydigan joriy narx: chegirma bo'lsa u, aks holda standart."""
        return self.discount_price_per_kwh or self.standard_price_per_kwh

    @property
    def original_price_per_kwh(self):
        """Chegirma ustidan chizib ko'rsatiladigan narx (chegirma yo'q bo'lsa None)."""
        return self.standard_price_per_kwh if self.has_discount else None

    @property
    def has_discount(self) -> bool:
        return (
            self.discount_price_per_kwh is not None
            and self.discount_price_per_kwh < self.standard_price_per_kwh
        )

    @property
    def is_online(self) -> bool:
        if not self.ocpp_id or not self.ocpp_last_seen_at:
            return False
        return timezone.now() - self.ocpp_last_seen_at < ONLINE_THRESHOLD

    @property
    def average_rating(self):
        """Haqiqiy sharhlar mavjud bo'lsa ularning o'rtachasi, aks holda dashboard'da
        qo'lda kiritilgan boshlang'ich `rating` qiymati (yangi stansiyalar uchun)."""
        avg = self.reviews.aggregate(avg=Avg('rating'))['avg']
        return round(avg, 1) if avg is not None else self.rating

    @property
    def review_count(self) -> int:
        return self.reviews.count()


class Connector(models.Model):
    """Stansiyadagi bitta ulagich (masalan "A" yoki "B")."""

    class Status(models.TextChoices):
        AVAILABLE = 'available', "Bo'sh"
        CHARGING = 'charging', 'Zaryadlanmoqda'
        # Bron bo'yicha qurilma darajasida ushlab turilgan (OCPP ReserveNow).
        # Ulagich jismonan bo'sh, lekin faqat bron egasi boshlay oladi.
        RESERVED = 'reserved', 'Bron qilingan'
        OFFLINE = 'offline', 'Ishlamayapti'

    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='connectors')
    label = models.CharField(max_length=10, help_text='Masalan: A, B')
    type = models.CharField(max_length=2, choices=Station.ChargerType.choices, default=Station.ChargerType.DC)
    power_kw = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AVAILABLE)
    charging_percent = models.PositiveIntegerField(
        null=True, blank=True, help_text="Faqat status='charging' bo'lganda — real vaqtda telemetriyadan keladi"
    )
    # OCPP StatusNotification/StartTransaction xabarlaridagi raqamli connectorId
    # shu maydon orqali ushbu Connector'ga bog'lanadi (masalan: 1, 2).
    ocpp_connector_id = models.PositiveIntegerField(
        null=True, blank=True, help_text="Chargerdagi raqamli ulagich ID (OCPP connectorId), masalan: 1"
    )

    # Zaryadlash tugagan, lekin kabel hali avtomobildan uzilmagan — bu paytda
    # ulagich boshqa foydalanuvchi uchun bo'shamaydi, shuning uchun daqiqalik
    # parkovka to'lovi hisoblanadi. OCPP'dagi SuspendedEV/Finishing holatlarida
    # (ocpp_gateway/consumers.py) o'rnatiladi, Available kelganda tozalanadi.
    parking_started_at = models.DateTimeField(
        null=True, blank=True, help_text='Pullik parkovka rejimi boshlangan vaqt (kabel uzilmagan)'
    )

    # Qurilma darajasidagi quvvat chegarasi (OCPP SetChargingProfile).
    # Bo'sh — chegara qo'yilmagan, ulagich to'liq quvvatda ishlaydi.
    power_limit_kw = models.PositiveIntegerField(
        'Quvvat chegarasi (kVt)', null=True, blank=True,
        help_text="Qurilmaga yuborilgan chegara. Bo'sh — cheklovsiz.",
    )
    offline_reason = models.CharField(
        max_length=200, blank=True,
        help_text="status='offline' bo'lganda foydalanuvchiga ko'rsatiladigan sabab (OCPP errorCode yoki qo'lda)",
    )

    class Meta:
        verbose_name = 'Ulagich'
        verbose_name_plural = 'Ulagichlar'
        ordering = ['label']
        unique_together = [('station', 'label'), ('station', 'ocpp_connector_id')]

    def __str__(self):
        return f'{self.station.name} — {self.label}'

    # ── Mobil ilova uchun hosilaviy holat maydonlari ──────────────────────
    # Bular ConnectorSerializer orqali yuboriladi va ilovada ulagich bosilganda
    # chiqadigan holat oynasini to'ldiradi (band foizi / parkovka / xato sababi).

    @cached_property
    def active_session(self):
        """Shu ulagichdagi tugallanmagan sessiya (bo'lmasa None).

        `cached_property` — serializer bitta ulagich uchun bir necha hosilaviy
        maydonni o'qiydi, ular bir xil sessiyaga tayanadi."""
        from sessions_app.models import ChargingSession

        return (
            ChargingSession.objects
            .filter(connector_id=self.id, status=ChargingSession.Status.CHARGING)
            .order_by('-started_at')
            .first()
        )

    @cached_property
    def parking_since(self):
        """Parkovka rejimi qachon boshlangani. Ikki manba bor:

        1. Haqiqiy charger — OCPP SuspendedEV/Finishing kelganda
           `parking_started_at` to'g'ridan-to'g'ri yoziladi.
        2. Simulyatsiya (charger ulanmagan stansiyalar) — sessiya 100% ga
           yetgan bo'lsa, batareya to'lgan payt sessiyadan hisoblanadi.
        """
        if self.status != self.Status.CHARGING:
            return None
        if self.parking_started_at:
            return self.parking_started_at
        session = self.active_session
        if session and session.current_percent >= 100:
            return session.full_at
        return None

    @property
    def parking_mode(self) -> bool:
        return self.parking_since is not None

    @property
    def parking_minutes(self) -> int:
        """Haq olinadigan parkovka daqiqalari.

        Imtiyoz vaqti (Sozlamalar > To'lov) chegirib tashlanadi: zaryad
        tugagach avtomobilni darhol olib ketish har doim ham mumkin emas,
        birinchi daqiqalardan pul olish esa nizoga sabab bo'ladi.
        """
        from stations.rules import parking_minutes as billable

        return billable(self.parking_since)

    @property
    def parking_fee_per_min(self):
        """Parkovka tarifi — sessiya boshlanganda muzlatilgan qiymat, sessiya
        topilmasa tizim standarti. Parkovka rejimida bo'lmasa None."""
        from sessions_app.models import DEFAULT_PARKING_FEE_PER_MIN

        if not self.parking_mode:
            return None
        session = self.active_session
        return session.parking_fee_per_min if session else DEFAULT_PARKING_FEE_PER_MIN

    @property
    def estimated_free_in_minutes(self):
        """Band ulagich taxminan necha daqiqada bo'shaydi. Parkovka rejimida
        bashorat qilib bo'lmaydi (avtomobil egasiga bog'liq) — None qaytadi."""
        if self.status != self.Status.CHARGING or self.parking_mode:
            return None
        session = self.active_session
        if session is None:
            return None
        return max(1, round(session.remaining_seconds / 60))


class StationAmenity(models.Model):
    """Stansiyadagi qo'shimcha mukofot/qulaylik (masalan bepul moy almashtirish)."""

    class Icon(models.TextChoices):
        OIL = 'oil', 'Moy'
        WIFI = 'wifi', 'Wi-Fi'
        COFFEE = 'coffee', 'Kofe'
        LOUNGE = 'lounge', 'Dam olish xonasi'

    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='amenities')
    icon = models.CharField(max_length=10, choices=Icon.choices)
    title = models.CharField(max_length=150)
    subtitle = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = 'Qulaylik'
        verbose_name_plural = 'Qulayliklar'

    def __str__(self):
        return f'{self.station.name} — {self.title}'


class Review(models.Model):
    """Foydalanuvchining stansiyaga qoldirgan yulduzcha bahosi va sharhi."""

    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='station_reviews')
    rating = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Sharh'
        verbose_name_plural = 'Sharhlar'
        ordering = ['-created_at']
        unique_together = [('station', 'user')]

    def __str__(self):
        return f'{self.station.name} — {self.user.username} ({self.rating}★)'


class MaintenanceIssue(models.Model):
    """Qurilmadagi nosozlik yozuvi — profilaktika bo'limining asosi.

    Nima uchun alohida jadval kerak: `Connector.status = 'offline'` faqat
    HOZIRGI holatni bildiradi. U tuzalgan zahoti ma'lumot yo'qoladi —
    qачон buzilgani, sababi, kim tuzatgani, foydalanuvchilar xabardor
    qilinganmi degan savollarga javob qolmaydi.

    Yozuvlar asosan avtomatik ochiladi (OCPP StatusNotification'dagi
    `Faulted`/`Unavailable`, yoki chargerdan aloqa uzilishi) va holat
    tiklanganda avtomatik yopiladi. Panel orqali qo'lda ham ochish/yopish
    mumkin — masalan operator o'zi ta'mirga qo'yganda.
    """

    class Kind(models.TextChoices):
        CONNECTOR = 'connector', 'Ulagich nosozligi'
        STATION = 'station', 'Charger bilan aloqa yo\'q'

    class Status(models.TextChoices):
        OPEN = 'open', 'Ochiq'
        RESOLVED = 'resolved', 'Tuzatilgan'

    class Source(models.TextChoices):
        OCPP = 'ocpp', 'Qurilmadan'
        MANUAL = 'manual', 'Qo\'lda'

    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='issues')
    # Bo'sh bo'lsa — muammo butun charger darajasida (aloqa yo'q)
    connector = models.ForeignKey(
        Connector, on_delete=models.CASCADE, related_name='issues', null=True, blank=True,
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.OCPP)

    # Foydalanuvchiga ko'rsatiladigan sabab (OCPP errorCode tarjimasi yoki qo'lda)
    reason = models.CharField(max_length=200)
    # Xom OCPP kodi — texnik tahlil uchun saqlanadi
    error_code = models.CharField(max_length=50, blank=True)

    opened_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resolved_issues',
    )
    resolution_note = models.CharField(max_length=300, blank=True)

    # Foydalanuvchilarga xabar yuborilgan vaqt — bir muammo bo'yicha ikki marta
    # bezovta qilmaslik uchun
    notified_at = models.DateTimeField(null=True, blank=True)
    resolved_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Nosozlik'
        verbose_name_plural = 'Nosozliklar'
        ordering = ['-opened_at']
        indexes = [models.Index(fields=['status', '-opened_at'])]
        constraints = [
            # Bir ulagich uchun bir vaqtda faqat bitta ochiq yozuv bo'lsin —
            # aks holda har StatusNotification yangi yozuv yaratardi.
            models.UniqueConstraint(
                fields=['connector'], condition=models.Q(status='open'),
                name='unique_open_issue_per_connector',
            ),
            models.UniqueConstraint(
                fields=['station'], condition=models.Q(status='open', connector__isnull=True),
                name='unique_open_issue_per_station',
            ),
        ]

    def __str__(self):
        target = self.connector.label if self.connector else 'charger'
        return f'{self.station.name} — {target}: {self.reason}'

    @property
    def target_label(self) -> str:
        return f'Ulagich {self.connector.label}' if self.connector else 'Charger'

    @property
    def duration(self):
        """Muammo qancha davom etgani (yopilmagan bo'lsa — hozirgacha)."""
        return (self.resolved_at or timezone.now()) - self.opened_at

    @property
    def duration_hours(self) -> int:
        return int(self.duration.total_seconds() // 3600)


class ChargerInfo(models.Model):
    """Qurilma pasporti — BootNotification'da charger o'zi haqida aytadigan hamma narsa.

    Ilgari bu ma'lumot faqat logga yozilib, keyin yo'qolardi. Endi saqlanadi,
    chunki amalda kerak bo'ladi: qaysi model o'rnatilgan, proshivka versiyasi
    nechada (nosozlik ma'lum versiyada chiqishi mumkin), SIM karta qaysi
    (ICCID orqali operatorga murojaat qilinadi), hisoblagich seriyasi qanaqa
    (metrologiya tekshiruvida so'raladi).

    Station bilan bir-birga: bitta stansiya = bitta jismoniy charger.
    """

    station = models.OneToOneField(Station, on_delete=models.CASCADE, related_name='info')

    vendor = models.CharField(max_length=100, blank=True, verbose_name='Ishlab chiqaruvchi')
    model = models.CharField(max_length=100, blank=True, verbose_name='Model')
    serial_number = models.CharField(max_length=100, blank=True, verbose_name='Seriya raqami')
    charge_box_serial = models.CharField(max_length=100, blank=True, verbose_name='Korpus seriyasi')
    firmware_version = models.CharField(max_length=100, blank=True, verbose_name='Proshivka')

    # Mobil aloqa moduli — qurilma SIM karta orqali ulangan bo'lsa
    iccid = models.CharField(max_length=40, blank=True, verbose_name='SIM ICCID')
    imsi = models.CharField(max_length=40, blank=True, verbose_name='SIM IMSI')

    meter_type = models.CharField(max_length=100, blank=True, verbose_name='Hisoblagich turi')
    meter_serial = models.CharField(max_length=100, blank=True, verbose_name='Hisoblagich seriyasi')

    # Qayta yuklanishlar soni — tez-tez o'sib borsa qurilma beqaror ishlayapti
    boot_count = models.PositiveIntegerField(default=0, verbose_name='Yuklanishlar soni')
    first_boot_at = models.DateTimeField(null=True, blank=True)
    last_boot_at = models.DateTimeField(null=True, blank=True)

    # Proshivka yangilash va diagnostika holati (FirmwareStatusNotification /
    # DiagnosticsStatusNotification)
    firmware_status = models.CharField(max_length=40, blank=True)
    firmware_status_at = models.DateTimeField(null=True, blank=True)
    diagnostics_status = models.CharField(max_length=40, blank=True)
    diagnostics_status_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Qurilma pasporti'
        verbose_name_plural = 'Qurilma pasportlari'

    def __str__(self):
        return f'{self.station.name} — {self.vendor} {self.model}'.strip()

    @property
    def title(self) -> str:
        parts = [p for p in (self.vendor, self.model) if p]
        return ' '.join(parts) or "Noma'lum qurilma"


class ChargerConfiguration(models.Model):
    """Chargerdan GetConfiguration bilan o'qilgan sozlama kaliti.

    OCPP'da har bir charger o'z sozlamalarini kalit-qiymat ko'rinishida
    beradi (`HeartbeatInterval`, `MeterValueSampleInterval` va h.k.). Ular
    qurilmaning O'ZIDA saqlanadi — bizdagi nusxa faqat oxirgi o'qilgan holat,
    shuning uchun `fetched_at` bilan birga ko'rsatiladi.

    `is_readonly=True` bo'lsa qiymatni o'zgartirib bo'lmaydi (charger shunday
    deb javob bergan).
    """

    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='configuration')
    key = models.CharField(max_length=100)
    value = models.CharField(max_length=500, blank=True)
    is_readonly = models.BooleanField(default=False)
    # Charger "bunday kalitni bilmayman" degan kalitlar ham saqlanadi —
    # operator nima qo'llab-quvvatlanmasligini ko'rishi kerak
    is_unknown = models.BooleanField(default=False)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Qurilma sozlamasi'
        verbose_name_plural = 'Qurilma sozlamalari'
        ordering = ['key']
        unique_together = [('station', 'key')]

    def __str__(self):
        return f'{self.station.name} — {self.key}={self.value}'


class ChargerLog(models.Model):
    """Qurilmadan kelgan xom xabarlar jurnali.

    Nima uchun: nosozlik tahlilida "charger aynan nima yubordi" degan savolga
    javob kerak bo'ladi, model maydonlariga esa hamma narsa sig'maydi (masalan
    `vendorErrorCode`, `info`, `transactionData`). Bu yerda payload o'zgarishsiz
    saqlanadi.

    Jurnal cheksiz o'smasligi kerak — `prune()` eski yozuvlarni tozalaydi
    (`manage.py sync_devices` chaqiradi).
    """

    class Kind(models.TextChoices):
        BOOT = 'boot', 'Yuklanish'
        STATUS = 'status', 'Holat xabari'
        STOP = 'stop', 'Sessiya tugadi'
        FIRMWARE = 'firmware', 'Proshivka'
        DIAGNOSTICS = 'diagnostics', 'Diagnostika'
        ERROR = 'error', 'Nosozlik'
        OTHER = 'other', 'Boshqa'

    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='logs')
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.OTHER)
    action = models.CharField(max_length=50, blank=True, help_text='OCPP action nomi')
    summary = models.CharField(max_length=200, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Qurilma jurnali'
        verbose_name_plural = 'Qurilma jurnali'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['station', '-created_at'])]

    def __str__(self):
        return f'{self.station.name} — {self.action} @ {self.created_at:%d.%m %H:%M}'

    @classmethod
    def prune(cls, keep_days=30, keep_per_station=500):
        """Eski yozuvlarni o'chiradi. Ikki chegara: yosh va soni.

        Faqat vaqt bo'yicha tozalash yetarli emas — tez-tez xabar yuboradigan
        charger bir kunda ham jadvalni to'ldirib yuborishi mumkin.
        """
        cutoff = timezone.now() - timedelta(days=keep_days)
        removed = cls.objects.filter(created_at__lt=cutoff).delete()[0]

        for station_id in cls.objects.values_list('station_id', flat=True).distinct():
            keep_ids = list(
                cls.objects.filter(station_id=station_id)
                .order_by('-created_at')
                .values_list('id', flat=True)[:keep_per_station]
            )
            removed += cls.objects.filter(station_id=station_id).exclude(id__in=keep_ids).delete()[0]
        return removed
