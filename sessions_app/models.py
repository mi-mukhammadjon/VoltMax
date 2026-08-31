from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from stations.models import Station, Connector

# Haqiqiy OCPP telemetriyasi hali ulanmagan — shu doim bir xil taxminlar bilan
# vaqt asosida "jonli" qiymatlarni hisoblab beradi (percent/kVt-soat/narx).
BATTERY_CAPACITY_KWH = 60
DEFAULT_PARKING_FEE_PER_MIN = 500


class ChargingSession(models.Model):
    class Status(models.TextChoices):
        CHARGING = 'charging', 'Zaryadlanmoqda'
        COMPLETED = 'completed', 'Tugallandi'
        STOPPED = 'stopped', "To'xtatildi"
        ERROR = 'error', 'Xatolik'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='charging_sessions')
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='sessions')
    connector = models.ForeignKey(Connector, on_delete=models.SET_NULL, null=True, related_name='sessions')

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CHARGING)
    started_at = models.DateTimeField(auto_now_add=True)
    stopped_at = models.DateTimeField(null=True, blank=True)

    # Sessiya boshlanganda "suratga olingan" qiymatlar — stansiya keyin o'zgarsa ham
    # sessiya tarixi buzilmaydi.
    start_percent = models.PositiveIntegerField()
    power_kw = models.PositiveIntegerField()
    price_per_kwh = models.PositiveIntegerField()

    # Narx qanday chiqqani — sessiya tarixida saqlanadi. Aksiya keyin
    # o'chirilsa yoki tarif o'zgarsa ham eski chek o'zgarmasligi kerak:
    # "nima uchun 900 so'm edi" degan savolga javob shu yerdan chiqadi.
    base_price_per_kwh = models.PositiveIntegerField(
        "Chegirmasiz narx", null=True, blank=True,
    )
    offer = models.ForeignKey(
        'management.Offer', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sessions', verbose_name='Aksiya',
    )
    price_label = models.CharField(
        'Narx izohi', max_length=200, blank=True,
        help_text="Masalan: Tungi tarif · Bahorgi aksiya",
    )
    voltage_v = models.FloatField(default=400.0)
    parking_fee_per_min = models.PositiveIntegerField(default=DEFAULT_PARKING_FEE_PER_MIN)
    connector_label = models.CharField(max_length=10, default='A')

    # Qaysi mashina zaryadlangani. Havola foydalanuvchi mashinasini o'chirsa
    # yo'qoladi, shuning uchun nomi va VIN'i sessiyaga KO'CHIRIB yoziladi —
    # tarix va hisobotlar buzilmasligi kerak.
    vehicle = models.ForeignKey(
        'accounts.Vehicle', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sessions',
    )
    vehicle_label = models.CharField(max_length=150, blank=True)
    vehicle_vin = models.CharField('VIN', max_length=17, blank=True)

    # To'xtatilganda hisoblangan yakuniy qiymatlar shu yerga "muzlatiladi".
    # `final_cost` — UMUMIY summa: energiya + pullik parkovka.
    final_percent = models.PositiveIntegerField(null=True, blank=True)
    final_kwh_charged = models.FloatField(null=True, blank=True)
    final_cost = models.PositiveIntegerField(null=True, blank=True)
    final_parking_minutes = models.PositiveIntegerField(null=True, blank=True)
    final_parking_cost = models.PositiveIntegerField(null=True, blank=True)

    # Parkovka sessiya davomida daqiqama-daqiqa yechiladi (bill_parking buyrug'i).
    # Shu ikki maydon "qancha daqiqa allaqachon hisoblangan" va "qancha pul
    # yechilgan"ni saqlaydi — sessiya tugaganda ular ikki marta yechilmasligi uchun.
    parking_billed_minutes = models.PositiveIntegerField(default=0)
    parking_billed_amount = models.PositiveIntegerField(default=0)

    # ── Haqiqiy charger (OCPP) telemetriyasi ──────────────────────────────
    # is_live=True bo'lsa, kwh_charged/current_percent yuqoridagi simulyatsiya
    # o'rniga shu real hisoblagich (Wh) qiymatlaridan hisoblanadi.
    # OCPP'ning transactionId'si sifatida shu sessiyaning o'z `id`si ishlatiladi
    # (StartTransaction javobida qaytariladi) — alohida maydon shart emas.
    is_live = models.BooleanField(default=False, help_text='Haqiqiy charger orqali (OCPP) boshlangan sessiyami')
    id_tag = models.CharField(max_length=50, blank=True, help_text='OCPP Authorize/StartTransaction idTag')
    meter_start_wh = models.PositiveIntegerField(null=True, blank=True, help_text="Boshlanishdagi hisoblagich (Wh)")
    live_meter_wh = models.PositiveIntegerField(null=True, blank=True, help_text="Oxirgi MeterValues hisoblagich (Wh)")
    meter_stop_wh = models.PositiveIntegerField(null=True, blank=True, help_text="Tugashdagi hisoblagich (Wh)")

    # Zaryadlash NIMA UCHUN tugagani — OCPP StopTransaction.reason. Bu javob
    # ko'p narsani hal qiladi: foydalanuvchi o'zi to'xtatdimi, kabel uzildimi,
    # tok o'chdimi yoki qurilma nosozlik sababli to'xtadimi.
    stop_reason = models.CharField(
        max_length=30, blank=True, verbose_name='Tugash sababi',
        help_text='OCPP StopTransaction reason (EVDisconnected, PowerLoss, Remote, ...)',
    )

    class Meta:
        verbose_name = 'Zaryadlash sessiyasi'
        verbose_name_plural = 'Zaryadlash sessiyalari'
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.user.username} — {self.station.name} ({self.status})'

    @property
    def elapsed_seconds(self) -> int:
        end = self.stopped_at or timezone.now()
        return max(0, int((end - self.started_at).total_seconds()))

    @property
    def kwh_charged(self) -> float:
        if self.final_kwh_charged is not None:
            return self.final_kwh_charged
        if self.is_live and self.meter_start_wh is not None and self.live_meter_wh is not None:
            return round(max(0, self.live_meter_wh - self.meter_start_wh) / 1000, 3)
        energy = self.power_kw * (self.elapsed_seconds / 3600)
        max_energy = BATTERY_CAPACITY_KWH * (100 - self.start_percent) / 100
        return round(min(energy, max_energy), 3)

    @property
    def current_percent(self) -> int:
        if self.final_percent is not None:
            return self.final_percent
        added = (self.kwh_charged / BATTERY_CAPACITY_KWH) * 100
        return min(100, round(self.start_percent + added))

    @property
    def saved_amount(self) -> int:
        """Aksiya va tarif tufayli tejalgan summa (so'm).

        Chegirma faqat narxda ko'rinsa, foydalanuvchi qancha yutganini
        bilmaydi — tejash aynan raqam bilan ko'rsatilgani ishonch beradi.
        """
        if not self.base_price_per_kwh:
            return 0
        return max(0, round(self.kwh_charged * (self.base_price_per_kwh - self.price_per_kwh)))

    @property
    def energy_cost(self) -> int:
        """Faqat iste'mol qilingan energiya uchun summa (parkovkasiz)."""
        if self.final_cost is not None:
            return max(0, self.final_cost - (self.final_parking_cost or 0))
        return round(self.kwh_charged * self.price_per_kwh)

    @property
    def parking_minutes(self) -> int:
        """Zaryad tugagandan keyin avtomobil ulagichni band qilib turgan daqiqalar.

        Jonli holatda ulagichdan (stations.Connector.parking_since) o'qiladi —
        u ham OCPP signalini, ham simulyatsiyani qamrab oladi."""
        if self.final_parking_minutes is not None:
            return self.final_parking_minutes
        if self.status != self.Status.CHARGING or self.connector is None:
            return 0
        return self.connector.parking_minutes

    @property
    def parking_cost(self) -> int:
        if self.final_parking_cost is not None:
            return self.final_parking_cost
        return self.parking_minutes * self.parking_fee_per_min

    @property
    def cost_so_far(self) -> int:
        """Foydalanuvchi to'laydigan umumiy summa: energiya + pullik parkovka."""
        if self.final_cost is not None:
            return self.final_cost
        return self.energy_cost + self.parking_cost

    @property
    def full_at(self):
        """Batareya 100% ga to'ladigan (yoki to'lgan) taxminiy vaqt.

        Simulyatsiya formulasining teskarisi: `current_percent` 100 ga yetadigan
        payt. Charger ulanmagan stansiyalarda parkovka rejimi shu vaqtdan
        boshlab hisoblanadi (stations.Connector.parking_since)."""
        if self.power_kw <= 0:
            return None
        needed_kwh = BATTERY_CAPACITY_KWH * (100 - self.start_percent) / 100
        return self.started_at + timedelta(seconds=needed_kwh / self.power_kw * 3600)

    @property
    def remaining_seconds(self) -> int:
        if self.status != self.Status.CHARGING:
            return 0
        remaining_kwh = BATTERY_CAPACITY_KWH * (100 - self.current_percent) / 100
        if self.power_kw <= 0:
            return 0
        return round(remaining_kwh / self.power_kw * 3600)

    @property
    def current_amps(self) -> float:
        if self.voltage_v <= 0:
            return 0.0
        return round(self.power_kw * 1000 / self.voltage_v, 2)

    def stop(self):
        """Sessiyani yakunlaydi: yakuniy qiymatlarni muzlatadi, hamyondan yechib
        tranzaksiya yozadi va ulagichni bo'shatadi. Mock (qo'lda to'xtatish),
        real charger (OCPP StopTransaction) va dashboard'dagi "Majburan
        to'xtatish" — barchasi shu yagona yo'l orqali ishlaydi."""
        from stations.models import Connector
        from wallet.models import WalletBalance, Transaction

        # Idempotentlik: sessiya allaqachon yakunlangan bo'lsa hech narsa qilmaymiz.
        # Bu shart, chunki to'xtatish uchta yo'ldan kelishi mumkin — panel
        # ("majburan uzish"), charger'ning StopTransaction xabari va mobil
        # ilovadagi tugma. Himoyasiz holda hamyondan ikki marta pul yechilardi.
        if self.status != self.Status.CHARGING:
            return

        # Parkovka avval muzlatiladi: `cost_so_far` uni umumiy summaga qo'shadi,
        # ulagich tozalangandan keyin esa daqiqalarni boshqa hisoblab bo'lmaydi.
        # `max(...)` — charger "Available" yuborib ulagichni tozalab yuborgan
        # bo'lsa, allaqachon hisoblangan daqiqalar yo'qolib ketmasligi uchun.
        self.final_parking_minutes = max(self.parking_minutes, self.parking_billed_minutes)
        self.final_parking_cost = self.final_parking_minutes * self.parking_fee_per_min

        self.final_percent = self.current_percent
        self.final_kwh_charged = self.kwh_charged
        self.final_cost = self.cost_so_far
        self.status = self.Status.STOPPED
        self.stopped_at = timezone.now()
        self.save()

        # Parkovkaning bir qismi sessiya davomida allaqachon yechilgan bo'lishi
        # mumkin — faqat qolgan farqni olamiz.
        already_paid = self.parking_billed_amount or 0
        charge_now = max(0, self.final_cost - already_paid)

        wallet, _ = WalletBalance.objects.get_or_create(user=self.user)
        wallet.amount = max(0, wallet.amount - charge_now)
        wallet.save(update_fields=['amount'])
        # Parkovka bo'lgan bo'lsa, foydalanuvchi chekda nima uchun ko'proq
        # yechilganini ko'rishi kerak — tavsif ikkala qismni ham ko'rsatadi.
        from dashboard.templatetags.money import format_som

        description = f'{self.station.name} — zaryadlash'
        if self.final_parking_cost:
            description += (
                f' + parkovka {self.final_parking_minutes} daq'
                f" ({format_som(self.final_parking_cost)} so'm)"
            )
        if already_paid:
            description += f" — {format_som(already_paid)} so'm avval yechilgan"

        # MUHIM: tranzaksiya summasi hamyondan HAQIQATAN yechilgan miqdor
        # bo'lishi kerak. Bu yerda `final_cost` yozilsa, parkovkaning avval
        # yechilgan qismi ledger'da ikki marta ko'rinib, balans bilan mos
        # kelmay qolardi.
        if charge_now:
            Transaction.objects.create(
                user=self.user, type=Transaction.Type.CHARGE_PAYMENT, amount=charge_now,
                description=description,
            )

        if self.connector_id:
            # .update() emas .save() — Connector post_save signali (stations/signals.py)
            # shu orqali ishga tushib, mobil ilovaga real-vaqt xabar yuboradi.
            connector = self.connector or Connector.objects.filter(id=self.connector_id).first()
            if connector:
                connector.status = Connector.Status.AVAILABLE
                connector.charging_percent = None
                # Parkovka hisoblagichi tozalanadi — summa yuqorida allaqachon
                # muzlatilib, hamyondan yechilgan.
                connector.parking_started_at = None
                connector.save(update_fields=['status', 'charging_percent', 'parking_started_at'])


class SessionMeterReading(models.Model):
    """Sessiya davomida chargerdan kelgan bitta o'lchov (OCPP MeterValues).

    Nima uchun alohida jadval: `ChargingSession` faqat OXIRGI qiymatni saqlaydi
    (`live_meter_wh`), ya'ni "hozir qancha" degan savolga javob beradi. Panelda
    esa "vaqt o'tishi bilan qanday o'zgardi" kerak — kuchlanish cho'kkanmi,
    tok qachon pasaygan. Buning uchun har bir o'lchov saqlanishi shart.

    Barcha maydonlar ixtiyoriy: charger qaysi o'lchovlarni yuborishi uning
    sozlamasiga bog'liq (MeterValuesSampledData) — birortasi bo'lmasa ham
    yozuv qolgan qiymatlar bilan saqlanadi.
    """

    session = models.ForeignKey(
        ChargingSession, on_delete=models.CASCADE, related_name='readings',
    )
    recorded_at = models.DateTimeField(default=timezone.now, db_index=True)

    voltage_v = models.FloatField(null=True, blank=True, help_text='Kuchlanish, V')
    current_a = models.FloatField(null=True, blank=True, help_text='Tok, A')
    power_kw = models.FloatField(null=True, blank=True, help_text='Quvvat, kVt')
    energy_wh = models.FloatField(null=True, blank=True, help_text='Hisoblagich, Wh')
    soc_percent = models.FloatField(null=True, blank=True, help_text='Batareya foizi')

    # Uch fazali AC chargerlarda har faza alohida keladi (phase: L1-N, L2-N…).
    # Fazalar orasidagi nomutanosiblik nosozlik belgisi bo'lishi mumkin.
    voltage_l1_v = models.FloatField(null=True, blank=True, help_text='L1 kuchlanishi, V')
    voltage_l2_v = models.FloatField(null=True, blank=True, help_text='L2 kuchlanishi, V')
    voltage_l3_v = models.FloatField(null=True, blank=True, help_text='L3 kuchlanishi, V')

    temperature_c = models.FloatField(null=True, blank=True, help_text='Harorat, °C')
    frequency_hz = models.FloatField(null=True, blank=True, help_text='Chastota, Hz')
    # Charger avtomobilga TAKLIF qilgan chegara — haqiqiy tokdan farq qilsa,
    # cheklov avtomobil tomonidan ekanini bildiradi
    current_offered_a = models.FloatField(null=True, blank=True, help_text='Taklif qilingan tok, A')
    power_offered_kw = models.FloatField(null=True, blank=True, help_text='Taklif qilingan quvvat, kVt')

    class Meta:
        verbose_name = "O'lchov"
        verbose_name_plural = "O'lchovlar"
        ordering = ['recorded_at']
        indexes = [models.Index(fields=['session', 'recorded_at'])]

    def __str__(self):
        return f'#{self.session_id} @ {self.recorded_at:%H:%M:%S}'


class PendingPromo(models.Model):
    """Masofadan boshlashda kiritilgan promo-kodni vaqtincha saqlaydi.

    Nima uchun kerak: haqiqiy charger'da sessiyani ILOVA yaratmaydi.
    Ilova RemoteStartTransaction yuboradi va 202 qaytadi, sessiyani esa
    charger StartTransaction bilan javob berganda OCPP shlyuzi yaratadi.
    Oradagi bu sakrashda promo-kod yo'qolardi — foydalanuvchi kodni
    kiritardi, chegirma esa qo'llanmasdi.

    Kod bazada saqlanadi (xotirada emas): veb va OCPP alohida jarayonlar,
    hatto alohida serverda ishlashi mumkin.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pending_promos')
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='+')
    code = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    # Charger javob bermasa yozuv osilib qolmasligi kerak: eskisi
    # keyingi urinishda ishlatilsa, foydalanuvchi kiritmagan chegirma
    # qo'llanib ketardi.
    TTL_MINUTES = 15

    class Meta:
        verbose_name = 'Kutilayotgan promo-kod'
        verbose_name_plural = 'Kutilayotgan promo-kodlar'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.code}'

    @classmethod
    def remember(cls, user, station, code):
        cls.objects.filter(user=user, station=station).delete()
        return cls.objects.create(user=user, station=station, code=code)

    @classmethod
    def take(cls, user, station):
        """Kodni oladi va o'chiradi — bir marta ishlatiladi."""
        cutoff = timezone.now() - timedelta(minutes=cls.TTL_MINUTES)
        cls.objects.filter(created_at__lt=cutoff).delete()

        row = cls.objects.filter(user=user, station=station,
                                 created_at__gte=cutoff).first()
        if row is None:
            return ''
        code = row.code
        row.delete()
        return code
