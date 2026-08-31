# -*- coding: utf-8 -*-
"""Vaqtga bog'liq tarif oynasi.

Bu fayl `stations/models.py` oxiriga import qilinadi — model shu ilovaga
tegishli bo'lib qolaveradi, lekin uzun `models.py` yana o'nlab qator
uzaymaydi.
"""
from datetime import timedelta

from django.db import models
from django.utils import timezone


class TariffWindow(models.Model):
    """Kunning ma'lum soatlarida amal qiladigan boshqa narx.

    Nima uchun kerak: kechki peakda tarmoqqa yuk eng katta, tunda esa
    stansiyalar bo'sh turadi. Tungi narxni pasaytirish haydovchini tunga
    suradi — bu ham tarmoq uchun, ham stansiya bandligi uchun foydali.

    Narx MUTLAQ qiymatda saqlanadi (foiz emas): operator "tunda 900 so'm"
    deb o'ylaydi, "standartdan 25% arzon" deb emas. Standart narx keyin
    o'zgarsa, tungi narx o'z-o'zidan siljib ketmaydi — bu yaxshi, chunki
    aks holda e'lon qilingan tarif jimgina o'zgarardi.
    """

    class DayKind(models.TextChoices):
        EVERY = 'every', 'Har kuni'
        WORKDAY = 'workday', 'Ish kunlari'
        WEEKEND = 'weekend', 'Dam olish va bayram'

    name = models.CharField('Nomi', max_length=100, help_text='Masalan: Tungi tarif')

    # Bo'sh — barcha stansiyalarda. Aynan bitta stansiyaga qo'yilgan oyna
    # umumiysidan ustun turadi (`stations.pricing` ga qarang).
    station = models.ForeignKey(
        'stations.Station', on_delete=models.CASCADE, null=True, blank=True,
        related_name='tariff_windows', verbose_name='Stansiya',
        help_text="Bo'sh — barcha stansiyalarda amal qiladi",
    )

    start_time = models.TimeField('Boshlanishi')
    end_time = models.TimeField('Tugashi')
    day_kind = models.CharField(
        'Kunlar', max_length=10, choices=DayKind.choices, default=DayKind.EVERY,
    )

    price_per_kwh = models.PositiveIntegerField("Narx (so'm/kVt·s)")
    is_active = models.BooleanField('Faol', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Tarif oynasi'
        verbose_name_plural = 'Tarif oynalari'
        ordering = ['start_time', 'name']

    def __str__(self):
        return f'{self.name} ({self.start_time:%H:%M}–{self.end_time:%H:%M})'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from stations.pricing import clear_catalogue

        clear_catalogue()

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        from stations.pricing import clear_catalogue

        clear_catalogue()
        return result

    # ── Amal qiladimi ─────────────────────────────────────────────
    @property
    def crosses_midnight(self) -> bool:
        return self.start_time > self.end_time

    def covers_time(self, moment) -> bool:
        """Soat shu oynaga tushadimi.

        Yarim tundan o'tuvchi oyna (22:00 → 06:00) alohida qaraladi:
        oddiy `start <= t <= end` bunday oralig'i uchun HAR DOIM yolg'on
        bo'lardi va tungi tarif hech qachon ishlamasdi.
        """
        if self.crosses_midnight:
            return moment >= self.start_time or moment <= self.end_time
        return self.start_time <= moment <= self.end_time

    def covers_day(self, day, holidays=None) -> bool:
        """Kun turi mos keladimi. Bayram — dam olish kuni deb qaraladi.

        `holidays` — oldindan o'qilgan bayram sanalari to'plami. Stansiyalar
        ro'yxatida narx har bir qator uchun hisoblanadi, shuning uchun bu
        yerda alohida so'rov qilish jadvalni ortiqcha yuklardi.
        """
        if self.day_kind == self.DayKind.EVERY:
            return True

        if holidays is None:
            from management.models import Holiday

            is_holiday = Holiday.objects.filter(date=day).exists()
        else:
            is_holiday = day in holidays

        weekend = day.weekday() >= 5 or is_holiday
        return weekend if self.day_kind == self.DayKind.WEEKEND else not weekend

    def covers(self, moment=None, holidays=None) -> bool:
        moment = moment or timezone.localtime()
        if not self.is_active:
            return False
        # Yarim tundan o'tuvchi oynada TUN yarmi ertangi kunga tegishli,
        # lekin kun turi oyna BOSHLANGAN kun bo'yicha olinadi: juma kechasi
        # boshlangan "ish kunlari" tarifi shanba tongida ham davom etadi.
        day = moment.date()
        if self.crosses_midnight and moment.time() <= self.end_time:
            day -= timedelta(days=1)
        return self.covers_time(moment.time()) and self.covers_day(day, holidays)
