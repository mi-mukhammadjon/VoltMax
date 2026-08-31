# -*- coding: utf-8 -*-
"""Panel loginini parol tanlashdan himoya qiladi.

Mobil ilovaning OTP'si allaqachon himoyalangan edi (urinishlar chegarasi,
muddat, throttle), xodimlar logini esa umuman ochiq turardi: cheksiz
parol sinab ko'rish mumkin edi. Panel orqali esa butun tarmoq, hamma
hamyon va to'lov kalitlari boshqariladi.

Uch narsa qilinadi:

  1. Muvaffaqiyatsiz urinishlar SANALADI va chegara tugagach kirish
     vaqtincha yopiladi (chegara va muddat sozlamada).
  2. Har urinish YOZILADI — muvaffaqiyatlisi ham. Ilgari hujumni
     payqashning ham iloji yo'q edi: hech qayerda iz qolmasdi.
  3. Blok LOGIN + IP juftligi bo'yicha qo'yiladi.

Nima uchun juftlik bo'yicha: faqat login bo'yicha bloklansa, begona odam
"admin" ni ataylab bloklab, haqiqiy operatorni ishga qo'ymay qo'yishi
mumkin edi. Faqat IP bo'yicha bloklansa, bitta ofisdan ishlaydigan butun
jamoa bir kishining xatosi uchun javob berardi.
"""
from datetime import timedelta

from django.db import models
from django.utils import timezone


class LoginAttempt(models.Model):
    """Panelga kirish urinishi."""

    username = models.CharField('Login', max_length=150, db_index=True)
    ip = models.GenericIPAddressField('IP', null=True, blank=True)
    successful = models.BooleanField('Muvaffaqiyatli', default=False)
    user_agent = models.CharField('Brauzer', max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Kirish urinishi'
        verbose_name_plural = 'Kirish urinishlari'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['username', 'ip', 'created_at'])]

    def __str__(self):
        mark = 'OK' if self.successful else 'XATO'
        return f'{mark} {self.username} @ {self.ip} — {self.created_at:%d.%m %H:%M}'


def client_ip(request):
    """So'rov kelgan manzil.

    Railway va shunga o'xshash platformalarda so'rov proksi orqali keladi,
    shuning uchun `REMOTE_ADDR` har doim platformaning o'z manzili bo'ladi.
    Haqiqiy manzil `X-Forwarded-For` ning BIRINCHI qiymatida turadi.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()[:45] or None
    return request.META.get('REMOTE_ADDR') or None


def _settings():
    from management.models import SiteSettings

    return SiteSettings.load()


def recent_failures(username, ip, since=None):
    """Blok oynasidagi ketma-ket muvaffaqiyatsiz urinishlar soni.

    Muvaffaqiyatli kirishdan KEYINGI urinishlar sanaladi: to'g'ri parol
    kiritilgach hisob nolga tushadi, aks holda kechagi xato bugungi
    kirishga xalaqit berardi.
    """
    settings_obj = _settings()
    window = timedelta(minutes=settings_obj.panel_lockout_minutes or 15)
    since = since or (timezone.now() - window)

    rows = LoginAttempt.objects.filter(
        username=username, ip=ip, created_at__gte=since).order_by('-created_at')

    count = 0
    for row in rows:
        if row.successful:
            break
        count += 1
    return count


def is_locked(username, ip):
    """Kirish yopiqmi. `(yopiqmi, qolgan_daqiqa)` qaytaradi."""
    settings_obj = _settings()
    limit = settings_obj.panel_max_attempts
    if not limit:
        return False, 0

    minutes = settings_obj.panel_lockout_minutes or 15
    window_start = timezone.now() - timedelta(minutes=minutes)
    if recent_failures(username, ip, since=window_start) < limit:
        return False, 0

    # Blok OXIRGI xatodan boshlab hisoblanadi: har yangi urinish muddatni
    # uzaytiradi, ya'ni tinmay urinish hech narsa bermaydi
    last = LoginAttempt.objects.filter(
        username=username, ip=ip, successful=False).order_by('-created_at').first()
    if last is None:
        return False, 0

    unlock_at = last.created_at + timedelta(minutes=minutes)
    remaining = int((unlock_at - timezone.now()).total_seconds() // 60) + 1
    return (True, max(1, remaining)) if unlock_at > timezone.now() else (False, 0)


def record(request, username, successful):
    """Urinishni yozadi. HECH QACHON xato tashlamaydi.

    Yozuv tufayli kirishning o'zi buzilishi mantiqsiz bo'lardi: kuzatuv
    asosiy ishni to'xtatmasligi kerak.
    """
    try:
        return LoginAttempt.objects.create(
            username=(username or '')[:150],
            ip=client_ip(request),
            successful=successful,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:200],
        )
    except Exception:       # noqa: BLE001
        return None


def uses_default_password():
    """Standart parol ("voltmax2026") hali ham ishlatilayaptimi.

    U hujjatlarda ochiq yozilgan, ya'ni parol emas — taklifnoma. Tizim
    holati sahifasi buni alohida ko'rsatadi.
    """
    from django.contrib.auth.models import User

    risky = []
    for user in User.objects.filter(is_staff=True):
        try:
            if user.check_password('voltmax2026'):
                risky.append(user.username)
        except Exception:       # noqa: BLE001 — buzuq hash tekshiruvni to'xtatmasin
            continue
    return risky
