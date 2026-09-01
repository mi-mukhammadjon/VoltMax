from django.conf import settings
from django.contrib.auth.models import User
from django.db import models


class WalletBalance(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    amount = models.PositiveIntegerField(default=0, help_text="so'mda")

    class Meta:
        verbose_name = 'Hamyon balansi'
        verbose_name_plural = 'Hamyon balanslari'

    def __str__(self):
        return f'{self.user.username} — {self.amount} so\'m'


class Transaction(models.Model):
    class Type(models.TextChoices):
        TOPUP = 'topup', "To'ldirish"
        CHARGE_PAYMENT = 'charge_payment', "Zaryadlash to'lovi"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transactions')
    type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.PositiveIntegerField(help_text="so'mda, har doim musbat")
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Tranzaksiya'
        verbose_name_plural = 'Tranzaksiyalar'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.get_type_display()} — {self.amount}'


class PaymentOrder(models.Model):
    """Onlayn to'lov buyurtmasi (Payme, Click va h.k.).

    Nima uchun alohida yozuv: to'lov tizimi bilan suhbat bir necha qadamdan
    iborat va u BIZNING serverga qайta-qayta murojaat qiladi (tekshirish,
    yaratish, tasdiqlash, bekor qilish). Har bir qadamda «qaysi to'lov haqida
    gap ketyapti?» degan savolga javob kerak — buyurtma raqami shu javob.

    Eng muhim talab — IDEMPOTENTLIK: to'lov tizimi bir xil so'rovni bir necha
    marta yuborishi mumkin (tarmoq uzilsa qayta uradi). Shuning uchun pul
    faqat `state` `PAID` ga O'TGANDA bir marta qo'shiladi va bu qulf ostida
    bajariladi.
    """

    class State(models.IntegerChoices):
        CREATED = 0, 'Yaratildi'          # ilova havolani oldi, to'lov hali yo'q
        WAITING = 1, 'Kutilmoqda'         # to'lov tizimi tranzaksiya ochdi
        PAID = 2, "To'landi"
        CANCELLED = -1, 'Bekor qilindi'
        REFUNDED = -2, 'Qaytarildi'       # to'langandan keyin bekor qilingan

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payment_orders')
    provider = models.ForeignKey(
        'management.PaymentProvider', on_delete=models.PROTECT,
        related_name='orders', verbose_name="To'lov tizimi")
    amount = models.PositiveIntegerField("Summa (so'm)")
    state = models.IntegerField(choices=State.choices, default=State.CREATED)

    # To'lov tizimidagi identifikatorlar. Payme: transaction id (matn),
    # Click: click_trans_id. Ular bo'yicha takroriy so'rov topiladi.
    external_id = models.CharField('Tashqi ID', max_length=64, blank=True, db_index=True)
    # Avtomatik to'ldirish natijasimi. Chegaralarni hisoblashda va
    # foydalanuvchiga ko'rsatishda ajratish kerak: odam o'zi bosgan
    # to'lov bilan o'zi bilmagan to'lov bir xil ko'rinmasligi shart.
    is_auto = models.BooleanField("Avtomatik", default=False)
    # Click ikki bosqichli: avval `prepare`, keyin `complete`
    prepare_id = models.CharField(max_length=64, blank=True)

    # Payme vaqtni millisekundda yuboradi va uni QAYTARISHNI talab qiladi
    create_time = models.BigIntegerField(default=0)
    perform_time = models.BigIntegerField(default=0)
    cancel_time = models.BigIntegerField(default=0)
    cancel_reason = models.IntegerField(null=True, blank=True)

    # Hamyondagi yozuv bilan bog'lanish: to'lovdan tranzaksiyani ham,
    # tranzaksiyadan to'lovni ham topib bo'ladi
    transaction = models.OneToOneField(
        Transaction, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payment_order')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "To'lov buyurtmasi"
        verbose_name_plural = "To'lov buyurtmalari"
        ordering = ['-created_at']
        indexes = [models.Index(fields=['provider', '-created_at'])]

    def __str__(self):
        return f'#{self.pk} — {self.amount} ({self.get_state_display()})'

    @property
    def amount_tiyin(self) -> int:
        """Payme summani tiyinda yuboradi (1 so'm = 100 tiyin)."""
        return self.amount * 100

    @property
    def is_open(self) -> bool:
        return self.state in (self.State.CREATED, self.State.WAITING)

    def mark_paid(self, *, external_id='', perform_time=0):
        """To'lovni yakunlaydi va pulni hamyonga qo'shadi.

        Idempotent: allaqachon to'langan bo'lsa hech narsa o'zgarmaydi va
        `False` qaytadi. To'lov tizimi bir so'rovni bir necha marta yuborishi
        odatiy hol — tarmoq uzilsa u qayta uradi.
        """
        from django.db import transaction as db_transaction

        with db_transaction.atomic():
            fresh = PaymentOrder.objects.select_for_update().get(pk=self.pk)
            if fresh.state == self.State.PAID:
                return False
            if fresh.state in (self.State.CANCELLED, self.State.REFUNDED):
                return False

            wallet, _ = WalletBalance.objects.select_for_update().get_or_create(
                user_id=fresh.user_id)
            wallet.amount += fresh.amount
            wallet.save(update_fields=['amount'])

            record = Transaction.objects.create(
                user_id=fresh.user_id, type=Transaction.Type.TOPUP,
                amount=fresh.amount,
                description=f"Hisobni to'ldirish — {fresh.provider.name}"[:255],
            )

            fresh.state = self.State.PAID
            fresh.transaction = record
            fresh.perform_time = perform_time
            if external_id:
                fresh.external_id = external_id[:64]
            fresh.save(update_fields=['state', 'transaction', 'perform_time',
                                      'external_id', 'updated_at'])

        self.refresh_from_db()
        return True

    def cancel(self, *, reason=None, cancel_time=0):
        """Bekor qiladi. To'langan bo'lsa pul hamyondan qaytarib olinadi.

        To'lov tizimi to'langan tranzaksiyani ham bekor qilishi mumkin
        (qaytarish). Bunda mablag' hamyondan yechiladi — aks holda pul
        ikki joyda qolardi.
        """
        from django.db import transaction as db_transaction

        with db_transaction.atomic():
            fresh = PaymentOrder.objects.select_for_update().get(pk=self.pk)
            if fresh.state in (self.State.CANCELLED, self.State.REFUNDED):
                return False

            was_paid = fresh.state == self.State.PAID
            if was_paid:
                wallet, _ = WalletBalance.objects.select_for_update().get_or_create(
                    user_id=fresh.user_id)
                # Balans manfiy bo'lib ketmasin: pul allaqachon sarflangan
                # bo'lishi mumkin, qarz esa alohida masala
                wallet.amount = max(0, wallet.amount - fresh.amount)
                wallet.save(update_fields=['amount'])

            fresh.state = self.State.REFUNDED if was_paid else self.State.CANCELLED
            fresh.cancel_reason = reason
            fresh.cancel_time = cancel_time
            fresh.save(update_fields=['state', 'cancel_reason', 'cancel_time',
                                      'updated_at'])

        self.refresh_from_db()
        return True


class SavedCard(models.Model):
    """Foydalanuvchi biriktirgan karta.

    KARTA RAQAMI BU YERDA YO'Q va hech qachon bo'lmaydi. Saqlanadigan
    narsa — provayder bergan token va foydalanuvchi kartani tanib olishi
    uchun oxirgi to'rt raqam. Token esa shifrlangan holda
    (`wallet/card_crypto.py`).

    Token — pul yechish huquqi, ya'ni u parolga teng. Farqi shundaki,
    to'lov kaliti bitta va uni almashtirsa bo'ladi; kartalar minglab va
    ularning har biri alohida odamning puli.
    """

    class State(models.IntegerChoices):
        # Provayder kartani qabul qildi, lekin SMS kod hali kiritilmagan
        PENDING = 0, 'Tasdiqlanmagan'
        ACTIVE = 1, 'Faol'
        # Muddati tugagan yoki bank rad etgan — foydalanuvchi qaytadan
        # biriktirishi kerak
        DEAD = 2, 'Ishlamaydi'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cards')
    provider = models.ForeignKey(
        'management.PaymentProvider', on_delete=models.PROTECT, related_name='cards')

    # Provayderning tokeni — SHIFRLANGAN holda
    token_encrypted = models.TextField('Token (shifrlangan)', blank=True)
    # Tasdiqlash bosqichida provayder beradigan vaqtinchalik havola
    verify_ref = models.CharField(max_length=120, blank=True)

    masked_pan = models.CharField('Karta', max_length=24)
    brand = models.CharField('Turi', max_length=20, blank=True)
    expires = models.CharField('Amal muddati', max_length=5, blank=True,
                               help_text='MM/YY')

    state = models.IntegerField(choices=State.choices, default=State.PENDING)
    is_default = models.BooleanField("Asosiy karta", default=False)

    verified_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Biriktirilgan karta'
        verbose_name_plural = 'Biriktirilgan kartalar'
        ordering = ['-is_default', '-created_at']

    def __str__(self):
        return f'{self.user.username} — {self.masked_pan}'

    @property
    def token(self) -> str:
        from .card_crypto import decrypt

        return decrypt(self.token_encrypted)

    @token.setter
    def token(self, value: str):
        from .card_crypto import encrypt

        self.token_encrypted = encrypt(value)

    @property
    def is_usable(self) -> bool:
        return self.state == self.State.ACTIVE and bool(self.token_encrypted)

    def make_default(self):
        """Shu kartani asosiy qiladi. Qolganlaridan belgi olinadi."""
        SavedCard.objects.filter(user=self.user).exclude(pk=self.pk).update(
            is_default=False)
        if not self.is_default:
            self.is_default = True
            self.save(update_fields=['is_default'])
        return self


class AutoTopUp(models.Model):
    """Balans pasayganda kartadan avtomatik to'ldirish.

    Nima uchun kerak: zaryadlash paytida pul tugasa sessiya to'xtaydi va
    odam yarim zaryadlangan mashina bilan qoladi — ko'pincha yerto'la
    parkovkada, aloqasiz joyda.

    Nima uchun CHEGARALAR bilan: avtomatik pul yechish ishonchni eng tez
    yo'qotadigan narsa. Har yechim ko'rinib turishi, chegaradan
    oshmasligi va istalgan paytda o'chirilishi kerak.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE,
                                related_name='auto_topup')
    card = models.ForeignKey(SavedCard, on_delete=models.CASCADE,
                             related_name='auto_topups')

    is_active = models.BooleanField('Yoqilgan', default=True)
    threshold = models.PositiveIntegerField(
        "Chegara (so'm)", default=20000,
        help_text='Balans shundan pasaysa to‘ldiriladi')
    amount = models.PositiveIntegerField(
        "Har safar (so'm)", default=50000)

    # Ikki chegara: bittasi xatoni, ikkinchisi suiiste'molni to'sadi
    daily_limit = models.PositiveIntegerField("Kunlik chegara (so'm)", default=200000)
    monthly_limit = models.PositiveIntegerField("Oylik chegara (so'm)", default=1000000)

    last_run_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    fail_streak = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # Ketma-ket shuncha xatodan keyin o'z-o'zidan o'chadi: ishlamaydigan
    # karta bilan har daqiqada urinish bankdan bloklashga olib keladi
    MAX_FAILS = 3

    class Meta:
        verbose_name = 'Avtomatik to‘ldirish'
        verbose_name_plural = 'Avtomatik to‘ldirish'

    def __str__(self):
        return f'{self.user.username} — {self.amount} so‘m'

    def spent_since(self, since):
        """Berilgan paytdan beri avtomatik yechilgan summa."""
        return sum(
            row.amount for row in PaymentOrder.objects.filter(
                user=self.user, state=PaymentOrder.State.PAID,
                is_auto=True, created_at__gte=since)
        )

    def blocked_reason(self):
        """Hozir ishlashiga to'sqinlik qiladigan sabab (yoki `None`)."""
        from django.utils import timezone

        if not self.is_active:
            return "o'chirilgan"
        if not self.card.is_usable:
            return 'karta ishlamaydi'
        if self.fail_streak >= self.MAX_FAILS:
            return f'ketma-ket {self.fail_streak} ta xato'

        now = timezone.localtime()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)

        if self.spent_since(day_start) + self.amount > self.daily_limit:
            return 'kunlik chegara'
        if self.spent_since(month_start) + self.amount > self.monthly_limit:
            return 'oylik chegara'
        return None
