import random
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone

OTP_TTL_MINUTES = 5


class OTPCode(models.Model):
    """Telefon raqamga yuborilgan bir martalik tasdiqlash kodi."""
    phone = models.CharField(max_length=20, db_index=True)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)
    # Noto'g'ri urinishlar soni. Chegarasiz bo'lsa 6 xonali kodni terib
    # chiqish mumkin: daqiqasiga 5 ta so'rov cheklovi bunga to'sqinlik
    # qilmaydi, chunki urinish uzoq davom etishi mumkin.
    attempts = models.PositiveSmallIntegerField(default=0)
    # Kod QAYSI kanal bilan ketgani. "Kod kelmadi" degan shikoyat
    # kelganda operator qayerga qarashni bilishi kerak: Telegram
    # hisobigami yoki SMS balansiga.
    sent_via = models.CharField(
        "Qaysi kanal bilan", max_length=20, blank=True,
        choices=[('telegram', 'Telegram'), ('sms', 'SMS')],
    )

    class Meta:
        verbose_name = 'OTP kod'
        verbose_name_plural = 'OTP kodlar'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.phone} — {self.code}'

    @property
    def is_expired(self):
        """Muddat SOZLAMADAN olinadi (Sozlamalar > Xavfsizlik).

        Ilgari u kodda qattiq yozilgan edi: operator panelda qiymatni
        o'zgartirardi, tizim esa unga qaramasdi.
        """
        return timezone.now() > self.created_at + timedelta(minutes=self.ttl_minutes)

    @property
    def ttl_minutes(self) -> int:
        from management.models import SiteSettings

        return SiteSettings.load().otp_ttl_minutes or OTP_TTL_MINUTES

    @property
    def is_locked(self) -> bool:
        """Urinishlar chegarasi tugadimi."""
        from management.models import SiteSettings

        limit = SiteSettings.load().otp_max_attempts
        return bool(limit) and self.attempts >= limit

    def wrong_attempt(self):
        """Noto'g'ri urinishni sanaydi va chegara tugaganini qaytaradi."""
        self.attempts += 1
        self.save(update_fields=['attempts'])
        return self.is_locked

    @staticmethod
    def generate(phone: str) -> 'OTPCode':
        code = f'{random.randint(0, 99999):05d}'
        return OTPCode.objects.create(phone=phone, code=code)


class Vehicle(models.Model):
    """Foydalanuvchining "Mening transport vositalarim" ro'yxatidagi elektromobili."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vehicles')
    name = models.CharField(max_length=100, help_text='Foydalanuvchi bergan nom, masalan "Kundalik mashinam"')
    make = models.CharField(max_length=100, blank=True, help_text='Ishlab chiqaruvchi, masalan Chevrolet')
    model = models.CharField(max_length=100, blank=True, help_text='Model, masalan Bolt EV')
    year = models.PositiveIntegerField(null=True, blank=True)
    battery_capacity_kwh = models.PositiveIntegerField(null=True, blank=True)
    # VIN — kuzov raqami, 17 belgi. Standart bo'yicha I, O va Q ishlatilmaydi
    # (1 va 0 bilan adashmasligi uchun), shuning uchun ular qabul qilinmaydi.
    vin = models.CharField(
        'VIN', max_length=17, blank=True,
        help_text='Kuzov raqami — 17 belgi. Sessiya tarixida ham saqlanadi.',
    )
    is_default = models.BooleanField(default=False, help_text="Zaryadlash sessiyalarida standart tanlanadigan mashina")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Transport vositasi'
        verbose_name_plural = 'Transport vositalari'
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.name}'

    @property
    def title(self) -> str:
        """Sessiya tarixiga yoziladigan qisqa nom: "Chevrolet Bolt EV" yoki nomi."""
        parts = [p for p in (self.make, self.model) if p]
        return ' '.join(parts) or self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Vehicle.objects.filter(user=self.user).exclude(pk=self.pk).update(is_default=False)


class Company(models.Model):
    """Korporativ mijoz — taksi park, dostavka xizmati, korxona avtoparki.

    Nima uchun kerak: bunday mijozda 10-50 ta avtomobil bo'ladi va har
    haydovchiga alohida hisob ochish ma'nosiz. Kompaniyaga bir nechta karta
    biriktiriladi, hamma sessiya BITTA hamyondan yechiladi va oyoxiri bitta
    hisobot chiqadi.

    Texnik yechim: kompaniyaning o'z "hisob foydalanuvchisi" bo'ladi
    (`billing_user`). Shu tufayli hamyon, tranzaksiyalar, sessiya tarixi va
    hisobotlar mavjud mexanizm bilan ishlayveradi — hech narsani ikki marta
    yozish shart emas.
    """

    name = models.CharField('Nomi', max_length=150, unique=True)
    contact_name = models.CharField("Mas'ul shaxs", max_length=150, blank=True)
    contact_phone = models.CharField('Telefon', max_length=20, blank=True)
    # Hujjatlar (hisob-faktura, dalolatnoma, shartnoma) shu manzilga
    # yuboriladi. Ilgari operator ularni qo'lda yuklab olib, qo'lda
    # jo'natardi — oyning oxirida bu bir necha soatlik ish edi.
    contact_email = models.EmailField('Elektron pochta', max_length=200, blank=True)
    # ── Yuridik va bank rekvizitlari ──────────────────────────────
    # Korporativ mijozga hisob-faktura va shartnoma yozish uchun kerak.
    # O'zbekistonda to'lov topshiriqnomasida shu ma'lumotlar talab qilinadi.
    inn = models.CharField('STIR', max_length=20, blank=True)
    legal_name = models.CharField(
        "To'liq yuridik nomi", max_length=250, blank=True,
        help_text='Shartnomadagi rasmiy nom, masalan: "VoltMax Servis" MChJ',
    )
    legal_address = models.CharField('Yuridik manzil', max_length=300, blank=True)
    director = models.CharField('Rahbar', max_length=150, blank=True)
    oked = models.CharField('OKED', max_length=20, blank=True)
    vat_code = models.CharField(
        'QQS kodi', max_length=20, blank=True,
        help_text="QQS to'lovchisi bo'lsa — registratsiya kodi",
    )

    bank_name = models.CharField('Bank nomi', max_length=200, blank=True)
    bank_account = models.CharField(
        'Hisob raqami', max_length=30, blank=True,
        help_text='20 xonali hisob raqami',
    )
    bank_mfo = models.CharField('MFO', max_length=10, blank=True)

    is_active = models.BooleanField('Faol', default=True)

    # Kompaniya nomidan pul yechiladigan texnik hisob. Avtomatik yaratiladi.
    billing_user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='company',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Korporativ mijoz'
        verbose_name_plural = 'Korporativ mijozlar'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def wallet(self):
        """Hamyon yozuvi. Panel havolalari `WalletBalance.pk` ni talab qiladi —
        foydalanuvchi id'si emas, shuning uchun obyektning o'zi kerak."""
        return getattr(self.billing_user, 'wallet', None)

    @property
    def balance(self) -> int:
        wallet = self.wallet
        return wallet.amount if wallet else 0

    @property
    def has_bank_details(self) -> bool:
        """Hisob-faktura yozish uchun yetarli rekvizit bormi."""
        return bool(self.inn and self.bank_account and self.bank_mfo)

    @property
    def invoice_name(self) -> str:
        return self.legal_name or self.name

    @classmethod
    def create_with_account(cls, **fields):
        """Kompaniya va uning hisob foydalanuvchisini birga yaratadi.

        Hisob foydalanuvchisi tizimga kira olmaydi (`is_active=False`) — u
        faqat hamyon va tranzaksiyalar uchun idish.
        """
        from django.contrib.auth.models import User
        from wallet.models import WalletBalance

        base = f"company-{fields['name']}".lower().replace(' ', '-')[:140]
        username, suffix = base, 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f'{base}-{suffix}'

        billing_user = User.objects.create(username=username, is_active=False)
        WalletBalance.objects.create(user=billing_user, amount=0)
        return cls.objects.create(billing_user=billing_user, **fields)


class RfidCard(models.Model):
    """Zaryadlashni boshlash uchun RFID karta (OCPP idTag).

    Nima uchun kerak: chargerlar kartani serverdan so'raydi (Authorize) yoki
    aloqa yo'q bo'lsa o'zidagi ro'yxatdan qaraydi. Ro'yxat bo'lmasa har qanday
    karta qabul qilinadi — ya'ni istalgan odam bepul zaryadlay oladi.

    Karta foydalanuvchiga biriktirilsa, u bilan boshlangan sessiya o'sha
    foydalanuvchi hisobidan yechiladi. Biriktirilmagan karta — xizmat kartasi
    (usta, texnik xizmat) sifatida ishlatiladi.
    """

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Faol'
        BLOCKED = 'blocked', 'Bloklangan'
        # Qurilma birinchi marta ko'rgan, lekin hali tasdiqlanmagan karta.
        # Ro'yxatga o'zi qo'shiladi, shunda operator uni ko'rib chiqadi.
        PENDING = 'pending', 'Tasdiqlanmagan'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name='rfid_cards', verbose_name='Egasi',
        help_text="Bo'sh qoldirilsa — xizmat kartasi",
    )
    id_tag = models.CharField(
        'Karta raqami (idTag)', max_length=20, unique=True,
        help_text='Kartaning OCPP identifikatori — chargerda o\'qilgani',
    )
    # Korporativ karta — pul kompaniyaning hamyonidan yechiladi.
    # `user` va `company` ikkalasi ham bo'lishi mumkin: karta kimda ekani
    # ma'lum bo'ladi, lekin hisob kompaniyaga tushadi.
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cards', verbose_name='Korporativ mijoz',
    )
    label = models.CharField('Nomi', max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    # Kartani foydalanuvchining O'ZI bloklaganmi (ilovadan, yo'qotganda).
    # Operator bloklagan kartani foydalanuvchi ocha olmasligi kerak.
    blocked_by_owner = models.BooleanField(default=False)
    expires_at = models.DateTimeField('Amal qilish muddati', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)
    # Karta qaysi stansiyada birinchi ko'ringani — tasdiqlashda yordam beradi
    first_seen_station = models.ForeignKey(
        'stations.Station', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )

    # ── Sarf chegarasi ────────────────────────────────────────────
    # Korporativ mijoz kartani haydovchiga beradi va u hamyon tugaguncha
    # cheksiz zaryadlay olardi. Chegara kartaning O'ZIDA turadi, chunki
    # kompaniyada kartalar ko'p va ularning har biriga boshqa ishonch
    # darajasi beriladi: xizmat mashinasi bilan direktor mashinasi bir
    # xil emas.
    daily_limit = models.PositiveIntegerField(
        "Kunlik chegara (so'm)", null=True, blank=True,
        help_text="Bo'sh — kunlik chegara yo'q",
    )
    monthly_limit = models.PositiveIntegerField(
        "Oylik chegara (so'm)", null=True, blank=True,
        help_text="Bo'sh — oylik chegara yo'q",
    )

    class Meta:
        verbose_name = 'RFID karta'
        verbose_name_plural = 'RFID kartalar'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.id_tag} — {self.label or self.user or "xizmat kartasi"}'

    @property
    def billing_user(self):
        """Sessiya KIMNING hisobiga yozilishi.

        Korporativ karta bo'lsa — kompaniyaning hisobi, aks holda kartaning
        egasi. Ikkalasi ham yo'q bo'lsa `None` (xizmat kartasi).
        """
        if self.company_id and self.company.is_active:
            return self.company.billing_user
        return self.user

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def effective_status(self) -> str:
        """Ko'rsatiladigan HAQIQIY holat.

        `status` maydoni "faol" bo'lsa ham muddati tugagan karta ishlamaydi —
        `ocpp_status()` unga `Expired` qaytaradi. Ro'yxatda esa "Faol" deb
        turgani chalg'itadi, shuning uchun ko'rinish shu xossadan olinadi.
        """
        if self.status == self.Status.BLOCKED:
            return 'blocked'
        if self.is_expired:
            return 'expired'
        return self.status

    @property
    def effective_status_display(self) -> str:
        return {
            'blocked': 'Bloklangan',
            'expired': 'Muddati tugagan',
            'pending': 'Tasdiqlanmagan',
            'active': 'Faol',
        }[self.effective_status]

    def ocpp_status(self) -> str:
        """Authorize javobidagi `idTagInfo.status`.

        OCPP 1.6 qiymatlari: Accepted, Blocked, Expired, Invalid, ConcurrentTx.
        """
        if self.status == self.Status.BLOCKED:
            return 'Blocked'
        if self.is_expired:
            return 'Expired'
        if self.status == self.Status.PENDING:
            # Tasdiqlanmagan karta sozlamaga qarab hal qilinadi (accounts.rfid)
            return 'Pending'
        return 'Accepted'

    # ── Sarf hisobi ───────────────────────────────────────────────
    def spent_between(self, since, until=None) -> int:
        """Shu karta bilan berilgan davrda sarflangan summa (so'm).

        Ketayotgan sessiya ham qo'shiladi. Aks holda chegara aylanib
        o'tilardi: uzoq sessiya davomida hisob o'smasdi va haydovchi
        chegaradan bemalol oshib ketardi.
        """
        from sessions_app.models import ChargingSession

        if not self.id_tag:
            return 0

        rows = ChargingSession.objects.filter(id_tag=self.id_tag)
        total = 0

        finished = rows.exclude(status=ChargingSession.Status.CHARGING).filter(
            stopped_at__gte=since)
        if until is not None:
            finished = finished.filter(stopped_at__lt=until)
        total += sum(session.final_cost or 0 for session in finished)

        # Ketayotgan sessiyaning ayni paytdagi summasi hali yozilmagan
        for session in rows.filter(status=ChargingSession.Status.CHARGING):
            if session.started_at >= since and (until is None or session.started_at < until):
                total += session.energy_cost

        return total

    @property
    def spent_today(self) -> int:
        start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.spent_between(start)

    @property
    def spent_this_month(self) -> int:
        start = timezone.localtime().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.spent_between(start)

    @property
    def limit_state(self):
        """Chegaralar holati — panelda ko'rsatish uchun.

        Ro'yxat: har biri `(nomi, sarflandi, chegara)`. Chegara qo'yilmagan
        bo'lsa umuman qaytarilmaydi — bo'sh ustun operatorni chalg'itadi.
        """
        rows = []
        if self.daily_limit:
            rows.append(('Bugun', self.spent_today, self.daily_limit))
        if self.monthly_limit:
            rows.append(('Shu oy', self.spent_this_month, self.monthly_limit))
        return rows


class CompanyInvoice(models.Model):
    """Korporativ mijozga yozilgan to'lov hisobi (schyot-faktura).

    Nima uchun kerak: korporativ mijoz karta yoki Payme orqali emas, bank
    o'tkazmasi bilan to'laydi — buxgalteriyasiga to'lov qilish uchun rasmiy
    hisob kerak. Pul kelgach operator hisobni «to'langan» deb belgilaydi va
    ayni shu paytda mablag' kompaniya hamyoniga tushadi.

    Nima uchun hamyonni to'g'ridan-to'g'ri to'ldirmaymiz: bank o'tkazmasi
    hisob YOZILGANDAN keyin bir necha kun o'tib keladi. Hisob shu oraliqni
    ko'rsatadi — kim qancha to'lashi kerakligi ro'yxatda turadi. Pul kelgani
    esa to'lov topshiriqnomasi raqami bilan qayd etiladi, shunda bankdagi
    o'tkazma bilan hamyondagi tranzaksiya solishtiriladi.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', "To'lov kutilmoqda"
        PAID = 'paid', "To'langan"
        CANCELLED = 'cancelled', 'Bekor qilingan'

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name='invoices',
        verbose_name='Korporativ mijoz',
    )
    number = models.CharField('Hisob raqami', max_length=20, unique=True)
    amount = models.PositiveIntegerField("Summa (so'm)")
    purpose = models.CharField(
        "To'lov maqsadi", max_length=255,
        default="Elektromobillarni zaryadlash xizmati uchun avans to'lovi",
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    issued_at = models.DateField('Yozilgan sana', default=timezone.localdate)

    # To'lov kelgach to'ldiriladi
    paid_at = models.DateTimeField('Qayd etilgan vaqt', null=True, blank=True)
    payment_ref = models.CharField(
        "To'lov topshiriqnomasi №", max_length=50, blank=True,
        help_text='Bank o\'tkazmasidagi hujjat raqami',
    )
    payment_date = models.DateField("Bankdagi o'tkazma sanasi", null=True, blank=True)
    # Hamyondagi tranzaksiya bilan bog'lanish: hisobdan tranzaksiyani ham,
    # tranzaksiyadan hisobni ham topib bo'ladi (buxgalteriya solishtiruvi)
    transaction = models.OneToOneField(
        'wallet.Transaction', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoice',
    )

    note = models.CharField('Izoh', max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "To'lov hisobi"
        verbose_name_plural = "To'lov hisoblari"
        ordering = ['-issued_at', '-id']
        indexes = [models.Index(fields=['company', '-issued_at'])]

    def __str__(self):
        return f'№{self.number} — {self.company.name}'

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING

    @classmethod
    def next_number(cls) -> str:
        """Yil ichida ketma-ket raqam: 2026-0001.

        Raqam yil bilan boshlanadi — buxgalteriyada hisoblar yil bo'yicha
        jurnal qilinadi va yangi yilda raqamlash noldan boshlanadi.
        """
        year = timezone.localdate().year
        last = (cls.objects
                .filter(number__startswith=f'{year}-')
                .order_by('-number').first())
        sequence = int(last.number.split('-')[1]) + 1 if last else 1
        return f'{year}-{sequence:04d}'

    def mark_paid(self, *, payment_ref='', payment_date=None, user=None):
        """To'lovni qayd etadi va mablag'ni kompaniya hamyoniga qo'shadi.

        Bitta atomik amal: hamyon ham, tranzaksiya ham, hisob holati ham
        birga o'zgaradi. Aks holda pul qo'shilib, hisob «kutilmoqda»
        bo'lib qolishi mumkin edi — keyin ikkinchi marta to'lanardi.
        """
        from django.db import transaction as db_transaction
        from wallet.models import Transaction, WalletBalance

        with db_transaction.atomic():
            # Qayta to'lashdan himoya: holatni qulflab tekshiramiz
            fresh = CompanyInvoice.objects.select_for_update().get(pk=self.pk)
            if fresh.status != self.Status.PENDING:
                return False

            wallet, _ = WalletBalance.objects.select_for_update().get_or_create(
                user=self.company.billing_user)
            wallet.amount += self.amount
            wallet.save(update_fields=['amount'])

            description = f"Bank o'tkazmasi — hisob №{self.number}"
            if payment_ref:
                description += f' (t/t №{payment_ref})'
            record = Transaction.objects.create(
                user=self.company.billing_user, type=Transaction.Type.TOPUP,
                amount=self.amount, description=description[:255],
            )

            fresh.status = self.Status.PAID
            fresh.paid_at = timezone.now()
            fresh.payment_ref = payment_ref[:50]
            fresh.payment_date = payment_date or timezone.localdate()
            fresh.transaction = record
            fresh.save(update_fields=['status', 'paid_at', 'payment_ref',
                                      'payment_date', 'transaction'])
        self.refresh_from_db()
        return True


class DeviceToken(models.Model):
    """Foydalanuvchining telefoni — push xabar shu manzilga yuboriladi.

    Bir odamda bir nechta qurilma bo'lishi mumkin (telefon, planshet), shu
    sababli alohida jadval. Token ilovada yaratiladi va o'zgarishi mumkin
    (ilova qayta o'rnatilganda), shuning uchun u kalit sifatida ishlatiladi:
    bir xil token boshqa foydalanuvchida paydo bo'lsa, egasi almashtiriladi
    — aks holda xabar avvalgi egaga ketaverardi.
    """

    class Platform(models.TextChoices):
        ANDROID = 'android', 'Android'
        IOS = 'ios', 'iOS'
        OTHER = 'other', 'Boshqa'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='devices')
    token = models.CharField('Push token', max_length=255, unique=True)
    platform = models.CharField(max_length=10, choices=Platform.choices,
                                default=Platform.OTHER)
    is_active = models.BooleanField(default=True)
    # Yuborishda "qurilma yo'q" javobi kelsa token o'chiriladi: eskirgan
    # tokenlarga urinish navbatni behuda band qiladi
    failed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Qurilma tokeni'
        verbose_name_plural = 'Qurilma tokenlari'
        ordering = ['-last_seen_at']

    def __str__(self):
        return f'{self.user} — {self.get_platform_display()}'

    @classmethod
    def register(cls, user, token, platform=''):
        """Tokenni saqlaydi yoki egasini yangilaydi."""
        token = (token or '').strip()
        if not token:
            return None

        obj, _ = cls.objects.update_or_create(
            token=token[:255],
            defaults={
                'user': user,
                'platform': platform if platform in cls.Platform.values else cls.Platform.OTHER,
                'is_active': True,
                'failed_at': None,
            },
        )
        return obj


class UserProfile(models.Model):
    """Foydalanuvchining qo'shimcha ma'lumoti — hozircha avatar.

    Bitta model IKKALASINI qamraydi: panel xodimi ham, ilova mijozi ham
    `User`. Alohida jadval `auth_user` ga tegmaslik uchun: Django ning
    o'z modelini almashtirishning yo'li bor, lekin u loyiha boshida
    qilinadi — keyin ko'chirish og'ir.

    Yozuv kerak bo'lganda o'zi yaratiladi (`for_user`): har foydalanuvchi
    uchun oldindan yaratib qo'yish jadvalni bekorga to'ldirardi.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='profile', verbose_name='Foydalanuvchi',
    )
    avatar = models.ImageField(
        'Avatar', upload_to='avatars/%Y/%m/', null=True, blank=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Foydalanuvchi profili'
        verbose_name_plural = 'Foydalanuvchi profillari'

    def __str__(self):
        return f'{self.user.username} profili'

    @classmethod
    def for_user(cls, user):
        profile, _ = cls.objects.get_or_create(user=user)
        return profile

    @property
    def avatar_url(self):
        """Avatar manzili yoki `None`.

        Fayl saqlashdan o'chirilgan bo'lsa (R2 ga o'tishda, tozalashda)
        `.url` xato tashlaydi — sahifa shu sababli qulamasligi kerak.
        """
        if not self.avatar:
            return None
        try:
            return self.avatar.url
        except Exception:       # noqa: BLE001
            return None

    def set_avatar(self, uploaded):
        """Yuklangan faylni qayta ishlab saqlaydi."""
        from django.core.files.base import ContentFile

        from .avatars import process

        name, content = process(uploaded)
        # Eskisi o'chiriladi: aks holda har almashtirishda saqlashda
        # yangi fayl qolib, joy behuda band bo'lardi
        self.clear_avatar(save=False)
        self.avatar.save(name, ContentFile(content), save=True)
        return self

    def clear_avatar(self, save=True):
        if self.avatar:
            try:
                self.avatar.delete(save=False)
            except Exception:       # noqa: BLE001 — fayl allaqachon yo'q bo'lishi mumkin
                pass
            self.avatar = None
            if save:
                self.save(update_fields=['avatar', 'updated_at'])
        return self


def avatar_url_for(user):
    """Foydalanuvchining avatari — yozuv bo'lmasa `None`.

    Alohida funksiya: shablon va serializerlarda `profile` bor-yo'qligini
    har safar tekshirib o'tirmaslik uchun.
    """
    profile = getattr(user, 'profile', None)
    return profile.avatar_url if profile else None
