# -*- coding: utf-8 -*-
"""Ikki bosqichli kirish (TOTP) — panel uchun.

Parol qanchalik kuchli bo'lmasin, u BITTA to'siq: oshkor bo'lsa (fishing,
qayta ishlatilgan parol, zararli dastur) boshqa hech narsa qolmaydi.
Panel esa butun tarmoqni, hamma hamyonni va to'lov kalitlarini
boshqaradi.

Ikkinchi to'siq — telefondagi ilova (Google Authenticator, Aegis va
boshqalar) har 30 soniyada beradigan olti xonali kod. Uni bilish uchun
telefonning O'ZI kerak.

Algoritm standart (RFC 6238) va standart kutubxona bilan yozilgan:
qo'shimcha bog'liqlik kiritishga arzimaydi, kod esa ellik qatordan
iborat va tekshirilishi oson.

Zaxira kodlari ham beriladi: telefon yo'qolsa yoki almashtirilsa,
operator tizimdan butunlay chiqib qolmasligi kerak.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

# Kod har shuncha soniyada almashadi (standart qiymat)
PERIOD = 30
DIGITS = 6

# Soat farqiga yon berish: telefon va server vaqti bir necha soniya
# farq qilishi odatiy hol. ±1 oyna — bu ±30 soniya.
DRIFT_WINDOWS = 1

BACKUP_CODE_COUNT = 8


def new_secret() -> str:
    """Yangi maxfiy kalit (base32, ilovalar shu formatni kutadi)."""
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def _code_at(secret: str, counter: int) -> str:
    """Berilgan oyna uchun kod (HOTP, RFC 4226)."""
    padding = '=' * (-len(secret) % 8)
    key = base64.b32decode(secret.upper() + padding, casefold=True)

    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** DIGITS)).zfill(DIGITS)


def current_code(secret: str, at=None) -> str:
    return _code_at(secret, int((at or time.time()) // PERIOD))


def verify(secret: str, code: str, at=None) -> bool:
    """Kod to'g'rimi.

    Solishtirish doimiy vaqtda: `==` birinchi mos kelmagan raqamda
    to'xtaydi va javob vaqti kod haqida ma'lumot berardi.
    """
    code = (code or '').strip().replace(' ', '')
    if not code.isdigit() or len(code) != DIGITS or not secret:
        return False

    counter = int((at or time.time()) // PERIOD)
    for shift in range(-DRIFT_WINDOWS, DRIFT_WINDOWS + 1):
        if secrets.compare_digest(_code_at(secret, counter + shift), code):
            return True
    return False


def provisioning_uri(secret: str, account: str, issuer: str = 'VoltMax') -> str:
    """Telefon ilovasi o'qiydigan `otpauth://` manzili."""
    label = quote(f'{issuer}:{account}')
    return (f'otpauth://totp/{label}?secret={secret}'
            f'&issuer={quote(issuer)}&digits={DIGITS}&period={PERIOD}')


def qr_svg(uri: str):
    """`otpauth://` manzilini QR kod (SVG) qilib qaytaradi.

    Kutubxona bo'lmasa `None` qaytadi va sahifa kalitni qo'lda kiritish
    uchun ko'rsatadi — ixtiyoriy bog'liqlik butun sahifani buzmasligi
    kerak.
    """
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return None

    try:
        image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage,
                            box_size=10, border=2)
        from io import BytesIO

        buffer = BytesIO()
        image.save(buffer)
        return buffer.getvalue().decode('utf-8')
    except Exception:       # noqa: BLE001 — QR bo'lmasa ham sozlash mumkin
        return None


def new_backup_codes(count: int = BACKUP_CODE_COUNT):
    """Bir martalik zaxira kodlari.

    Telefon yo'qolsa yoki almashtirilsa operator tizimdan butunlay
    chiqib qolmasligi kerak — aks holda uni tiklash uchun serverga
    kirish talab qilinardi.
    """
    return [f'{secrets.randbelow(10**9):09d}' for _ in range(count)]


# ── Bazadagi yozuv ──────────────────────────────────────────────
# Model shu faylda: TOTP mantig'i va uning saqlanishi bir joyda tursin.
from django.conf import settings as django_settings  # noqa: E402
from django.db import models  # noqa: E402
from django.utils import timezone  # noqa: E402


class TwoFactor(models.Model):
    """Xodimning ikki bosqichli kirish sozlamasi.

    `confirmed_at` — foydalanuvchi kodni bir marta to'g'ri kiritgan payt.
    Tasdiqlanmaguncha talab qilinmaydi: aks holda kalit yaratilib, ilovaga
    qo'shilmagan bo'lsa operator o'z panelidan chiqib qolardi.
    """

    user = models.OneToOneField(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='two_factor', verbose_name='Xodim',
    )
    secret = models.CharField('Maxfiy kalit', max_length=64)
    confirmed_at = models.DateTimeField('Tasdiqlangan', null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    # Zaxira kodlari ochiq saqlanmaydi: baza oshkor bo'lsa ular parolga
    # teng bo'lardi. Faqat SHA-256 yig'indisi turadi.
    backup_hashes = models.JSONField('Zaxira kodlari', default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Ikki bosqichli kirish'
        verbose_name_plural = 'Ikki bosqichli kirish'

    def __str__(self):
        state = 'yoqilgan' if self.is_active else 'tasdiqlanmagan'
        return f'{self.user} — {state}'

    @property
    def is_active(self) -> bool:
        return self.confirmed_at is not None

    @property
    def backup_left(self) -> int:
        return len(self.backup_hashes or [])

    # ── Kodlar ──────────────────────────────────────────────────
    @staticmethod
    def _hash(code):
        digits = ''.join(ch for ch in str(code) if ch.isdigit())
        return hashlib.sha256(digits.encode('utf-8')).hexdigest()

    def set_backup_codes(self):
        """Yangi zaxira kodlari yaratadi va OCHIQ ko'rinishini qaytaradi.

        Ochiq ko'rinish faqat shu payt beriladi — keyin uni tiklashning
        iloji yo'q, chunki bazada yig'indisi turadi.
        """
        codes = new_backup_codes()
        self.backup_hashes = [self._hash(code) for code in codes]
        return codes

    def use_backup_code(self, code) -> bool:
        """Zaxira kodini ishlatadi — bir marta.

        Ishlatilgani ro'yxatdan o'chiriladi: aks holda o'g'irlangan kod
        cheksiz ishlatilardi.
        """
        digest = self._hash(code)
        hashes = list(self.backup_hashes or [])
        for stored in hashes:
            if secrets.compare_digest(stored, digest):
                hashes.remove(stored)
                self.backup_hashes = hashes
                self.save(update_fields=['backup_hashes'])
                return True
        return False

    def verify_code(self, code) -> bool:
        """Kodni tekshiradi: avval ilova kodi, keyin zaxira kodi.

        Nomi `check` emas: u Django modelining o'z metodi (tizim
        tekshiruvlari uchun) va uni bosib bo'lmaydi.
        """
        if verify(self.secret, code):
            self.last_used_at = timezone.now()
            self.save(update_fields=['last_used_at'])
            return True
        if self.use_backup_code(code):
            self.last_used_at = timezone.now()
            self.save(update_fields=['last_used_at'])
            return True
        return False


def required_for(user) -> bool:
    """Shu xodimdan ikki bosqichli kirish TALAB QILINADIMI.

    Sozlama yoqilgan bo'lsa administratorlar (superuser) uchun majburiy:
    ular sozlamalarni, to'lov kalitlarini va hisob-kitobni boshqaradi.
    Menejer uchun ixtiyoriy — u kundalik ish bilan shug'ullanadi.
    """
    from management.models import SiteSettings

    if not user or not user.is_authenticated or not user.is_staff:
        return False
    return bool(SiteSettings.load().require_2fa_for_admins) and user.is_superuser
