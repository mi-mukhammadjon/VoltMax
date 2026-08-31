# -*- coding: utf-8 -*-
"""Profil rasmi — panelda ham, ilovada ham.

Bitta model ikkalasini qamraydi: mobil foydalanuvchi ham, xodim ham
`User`.

Rasm XOM HOLDA saqlanmaydi. Telefondagi surat 4-8 MB bo'ladi va u:
  * har ochilganda shuncha trafik yeydi (mijoz mobil internetda);
  * saqlashda joy egallaydi;
  * EXIF ichida SURATGA OLINGAN JOY koordinatalari bo'lishi mumkin —
    avatar bilan birga uy manzilini tarqatib yuborish yaxshi emas.

Asosiy savollar:
  1. Rasm kvadratga qirqilib, kichrayadimi?
  2. EXIF tozalanadimi?
  3. Rasm bo'lmagan fayl rad etiladimi?
  4. Eski rasm almashtirilganda O'CHADIMI (joy behuda band bo'lmasin)?
  5. Begona odam boshqa hisobning rasmini o'zgartira oladimi?
"""
import io
import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'voltmax.settings')
django.setup()

from PIL import Image  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core.exceptions import ValidationError  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import override_settings  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from accounts.avatars import MAX_UPLOAD_MB, SIZE  # noqa: E402
from accounts.models import UserProfile, avatar_url_for  # noqa: E402

failures = 0


def check(label, condition, extra=''):
    global failures
    print(f'{"OK  " if condition else "XATO"}  {label:56s} {extra}')
    if not condition:
        failures += 1


def _cleanup():
    for profile in UserProfile.objects.filter(user__username__startswith='__av'):
        profile.clear_avatar()
    UserProfile.objects.filter(user__username__startswith='__av').delete()
    User.objects.filter(username__startswith='__av').delete()


def picture(size=(1200, 800), mode='RGB', fmt='JPEG', colour=(20, 160, 90)):
    buffer = io.BytesIO()
    Image.new(mode, size, colour).save(buffer, fmt)
    buffer.seek(0)
    return SimpleUploadedFile(f'surat.{fmt.lower()}', buffer.getvalue(),
                              content_type=f'image/{fmt.lower()}')


@override_settings(ALLOWED_HOSTS=['testserver'])
def main():
    _cleanup()

    try:
        user = User.objects.create(username='__av_driver__', first_name='Aziz')
        profile = UserProfile.for_user(user)

        # ── 1. Qayta ishlash ────────────────────────────────────
        check('avatarsiz profil bo\'sh', avatar_url_for(user) is None)

        profile.set_avatar(picture())
        profile.avatar.open()
        image = Image.open(profile.avatar)

        check('kvadratga qirqildi', image.size == (SIZE, SIZE), image.size)
        check('JPEG ga o\'girildi', image.format == 'JPEG', image.format)
        check('rangli rejim RGB', image.mode == 'RGB', image.mode)
        check('manzil paydo bo\'ldi', avatar_url_for(user) is not None,
              avatar_url_for(user))

        # Hajm sezilarli kichrayishi kerak
        size_kb = profile.avatar.size / 1024
        check('hajmi kichraydi', size_kb < 200, f'{size_kb:.1f} KB')

        # ── 2. EXIF tozalanadi ──────────────────────────────────
        # Suratga olingan joy koordinatalari avatar bilan birga
        # tarqalib ketmasligi kerak
        profile.avatar.open()
        cleaned = Image.open(profile.avatar)
        exif = cleaned.getexif()
        check('EXIF tozalandi', not dict(exif), dict(exif))

        # ── 3. Shaffof rasm ─────────────────────────────────────
        # Shaffoflik JPEG da qora bo'lib chiqadi — oq fon qo'yiladi
        profile.set_avatar(picture(mode='RGBA', fmt='PNG', colour=(255, 0, 0, 0)))
        profile.avatar.open()
        flat = Image.open(profile.avatar).convert('RGB')
        check('shaffof joy oq bo\'ldi', flat.getpixel((10, 10)) == (255, 255, 255),
              flat.getpixel((10, 10)))

        # ── 4. Eski fayl o'chadi ────────────────────────────────
        # Har almashtirishda yangi fayl qolib ketsa, saqlash joyi
        # bekorga to'lib borardi. Nomni solishtirish yetarli emas:
        # eski o'chirilgach nom QAYTA ISHLATILADI — shuning uchun
        # papkadagi fayllar SONI sanaladi.
        storage = profile.avatar.storage
        folder = profile.avatar.name.rsplit('/', 1)[0]
        before = len(storage.listdir(folder)[1])

        profile.set_avatar(picture(colour=(10, 10, 200)))
        after = len(storage.listdir(folder)[1])

        check('almashtirishda ortiqcha fayl qolmadi', after == before,
              f'{before} -> {after}')
        check('yangi fayl bor', storage.exists(profile.avatar.name))

        # ── 5. Yaroqsiz fayl ────────────────────────────────────
        broken = SimpleUploadedFile('x.jpg', b'bu rasm emas',
                                    content_type='image/jpeg')
        try:
            profile.set_avatar(broken)
            check('rasm bo\'lmagan fayl rad etildi', False)
        except ValidationError as error:
            check('rasm bo\'lmagan fayl rad etildi', True, error.messages[0])

        huge = SimpleUploadedFile('big.jpg', b'x' * (MAX_UPLOAD_MB * 1024 * 1024 + 10),
                                  content_type='image/jpeg')
        try:
            profile.set_avatar(huge)
            check('juda katta fayl rad etildi', False)
        except ValidationError as error:
            check('juda katta fayl rad etildi', True, error.messages[0])

        check('rad etilgach eski rasm joyida', bool(profile.avatar))

        # ── 6. API ──────────────────────────────────────────────
        client = Client()
        client.defaults['HTTP_AUTHORIZATION'] = (
            f'Bearer {RefreshToken.for_user(user).access_token}')

        payload = client.get('/api/auth/profile/').json()
        check('profilda avatar manzili bor', payload.get('avatarUrl'),
              payload)
        check('manzil to\'liq (host bilan)',
              str(payload.get('avatarUrl')).startswith('http'),
              payload.get('avatarUrl'))

        uploaded = client.post('/api/auth/avatar/', {'avatar': picture()})
        check('API orqali yuklandi', uploaded.status_code == 201,
              uploaded.status_code)

        rejected = client.post('/api/auth/avatar/', {
            'avatar': SimpleUploadedFile('x.jpg', b'yolgon',
                                         content_type='image/jpeg')})
        check('API yaroqsiz faylni rad etdi', rejected.status_code == 400,
              rejected.status_code)

        removed = client.delete('/api/auth/avatar/')
        profile.refresh_from_db()
        check('API orqali o\'chirildi',
              removed.status_code == 200 and not profile.avatar)

        # ── 7. Begona hisob ─────────────────────────────────────
        stranger = User.objects.create(username='__av_begona__')
        stranger_client = Client()
        stranger_client.defaults['HTTP_AUTHORIZATION'] = (
            f'Bearer {RefreshToken.for_user(stranger).access_token}')

        stranger_client.post('/api/auth/avatar/', {'avatar': picture()})
        profile.refresh_from_db()
        check('begona hisobning rasmi tegilmadi', not profile.avatar)
        check('o\'z rasmi saqlandi',
              bool(UserProfile.objects.get(user=stranger).avatar))

        check('kirmagan foydalanuvchi rad etildi',
              Client().post('/api/auth/avatar/').status_code == 401)

        # ── 8. Panel ────────────────────────────────────────────
        staff = User.objects.create_user(username='__av_xodim__',
                                         password='QuyoshliKun-92',
                                         is_staff=True, is_superuser=True)
        panel = Client()
        panel.force_login(staff)

        panel.post('/profile/', {'section': 'avatar', 'avatar': picture()})
        staff_profile = UserProfile.objects.get(user=staff)
        check('panelda yuklandi', bool(staff_profile.avatar))

        page = panel.get('/profile/').content.decode('utf-8')
        check('sahifada rasm ko\'rindi', '<img src="' in page
              and 'avatars/' in page)
        check('o\'chirish tugmasi paydo bo\'ldi', 'Rasmni o' in page)

        panel.post('/profile/', {'section': 'avatar', 'remove': '1'})
        staff_profile.refresh_from_db()
        check('panelda o\'chirildi', not staff_profile.avatar)

        page = panel.get('/profile/').content.decode('utf-8')
        check('rasmsiz holatda bosh harflar', 'profile-avatar' in page
              and 'avatars/' not in page)

    finally:
        _cleanup()

    print('\n' + ('HAMMASI OK' if not failures else f'*** {failures} TA XATO ***'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
