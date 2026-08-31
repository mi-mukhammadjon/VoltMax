from django.conf import settings
from django.db import models

from stations.models import Station, Connector


class Booking(models.Model):
    """Foydalanuvchi oldindan band qilgan zaryadlash vaqti — "Bronlarim" ekrani.
    Hozircha faqat vaqt/ulagichni "ushlab turish" ma'nosida — real charger uchun
    reservation OCPP xabari (ReserveNow) hali ulanmagan, shu sabab bron shunchaki
    rejalashtirish yozuvi sifatida saqlanadi."""

    class Status(models.TextChoices):
        CONFIRMED = 'confirmed', 'Tasdiqlangan'
        CANCELLED = 'cancelled', "Bekor qilindi"
        COMPLETED = 'completed', 'Tugallandi'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings')
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name='bookings')
    connector = models.ForeignKey(Connector, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')

    scheduled_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=60)
    estimated_cost = models.PositiveIntegerField(default=0, help_text="so'mda, taxminiy")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    # Qurilmaning O'ZIDA qo'yilgan bron raqami (OCPP ReserveNow.reservationId).
    # Bo'sh bo'lsa bron faqat bizning bazamizda — ya'ni boshqa odam kelib
    # ulagichdan foydalanib ketishi mumkin.
    ocpp_reservation_id = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Bron'
        verbose_name_plural = 'Bronlar'
        ordering = ['-scheduled_at']

    def __str__(self):
        return f'{self.user.username} — {self.station.name} ({self.scheduled_at:%d.%m.%Y %H:%M})'
