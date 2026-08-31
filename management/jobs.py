# -*- coding: utf-8 -*-
"""Davriy vazifalarning holati — ular HAQIQATAN ishlayaptimi.

Vazifalar (parkovka hisobi, push, muddati o'tgan sessiyalar, bronlar)
faqat logga yozardi. Ya'ni panelga qarab "push ketyaptimi" degan savolga
javob olib bo'lmasdi: servis Railway'da umuman ishga tushmagan bo'lsa
ham panel bemalol "hammasi joyida" ko'rinishida turaverardi.

Jimgina ishlamaslik eng yomon holat — buni aksiyalar bilan bir marta
ko'rganmiz: panelda bor, hisobda yo'q.

Bu yerda har vazifa uchun BITTA qator turadi va har tsiklda yangilanadi.
Tarix saqlanmaydi: jadval o'smaydi, tozalash kerak emas, savolga esa
javob beradi — "oxirgi marta qachon ishladi va nima bo'ldi".
"""
from django.db import models
from django.utils import timezone


class JobStatus(models.Model):
    """Bitta davriy vazifaning oxirgi holati."""

    name = models.CharField('Vazifa', max_length=40, unique=True)

    last_run_at = models.DateTimeField('Oxirgi ishlagani', null=True, blank=True)
    last_ok_at = models.DateTimeField('Oxirgi muvaffaqiyat', null=True, blank=True)
    last_summary = models.CharField('Natija', max_length=255, blank=True)
    last_error = models.CharField('Xato', max_length=255, blank=True)

    # Ketma-ket nechta marta yiqilgani. Bitta xato tasodif bo'lishi mumkin,
    # ketma-ket uchtasi — nosozlik.
    fail_streak = models.PositiveIntegerField('Ketma-ket xato', default=0)
    runs = models.PositiveIntegerField('Jami ishlagani', default=0)

    class Meta:
        verbose_name = 'Vazifa holati'
        verbose_name_plural = 'Vazifalar holati'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} — {self.last_run_at:%d.%m %H:%M}' if self.last_run_at else self.name

    @classmethod
    def record(cls, name, summary='', error=''):
        """Bitta tsikl natijasini yozadi.

        HECH QACHON xato tashlamaydi: holat yozuvi tufayli vazifaning
        o'zi to'xtab qolishi mantiqsiz bo'lardi — u asosiy ish, bu esa
        kuzatuv.
        """
        try:
            now = timezone.now()
            row, _ = cls.objects.get_or_create(name=name)
            row.last_run_at = now
            row.last_summary = (summary or '')[:255]
            row.last_error = (error or '')[:255]
            row.runs += 1
            if error:
                row.fail_streak += 1
            else:
                row.fail_streak = 0
                row.last_ok_at = now
            row.save()
            return row
        except Exception:       # noqa: BLE001 — kuzatuv asosiy ishni to'xtatmasin
            return None

    @property
    def seconds_since_run(self):
        if self.last_run_at is None:
            return None
        return int((timezone.now() - self.last_run_at).total_seconds())
