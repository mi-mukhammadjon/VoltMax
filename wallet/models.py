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
