# -*- coding: utf-8 -*-
"""Foydalanuvchi avatari — panel xodimi uchun ham, ilova mijozi uchun ham.

Bitta model ikkalasini qamraydi: mobil foydalanuvchi ham, xodim ham
`User` — ular orasida farq faqat `is_staff` da.

RASM QAYTA ISHLANADI, xom holda saqlanmaydi. Telefondagi surat 4-8 MB
bo'ladi va u:
  * har ochilganda shuncha trafik yeydi (mijoz mobil internetda);
  * saqlashda joy egallaydi;
  * EXIF ichida SURATGA OLINGAN JOY koordinatalari bo'lishi mumkin —
    avatar bilan birga uy manzilini tarqatib yuborish yaxshi emas.

Shuning uchun rasm kvadratga qirqiladi, 512px ga kichraytiriladi va
JPEG sifatida QAYTA YOZILADI — bu EXIF ni ham tozalaydi.
"""
import io

from django.core.exceptions import ValidationError

# Kattaroq o'lcham avatar uchun keraksiz: u eng katta joyda ham
# 100-200px bo'lib ko'rsatiladi, 512 esa Retina ekranlar uchun zaxira
SIZE = 512
QUALITY = 85

# Qayta ishlashdan OLDINGI chegara. Bu xotira himoyasi: juda katta
# faylni ochishga urinish serverni cho'ktirishi mumkin.
MAX_UPLOAD_MB = 10

ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'HEIF', 'HEIC'}


def process(uploaded):
    """Yuklangan faylni avatarga aylantiradi.

    `(fayl_nomi, baytlar)` qaytaradi yoki `ValidationError` tashlaydi.
    """
    from PIL import Image, ImageOps

    if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise ValidationError(
            f'Rasm juda katta — {MAX_UPLOAD_MB} MB dan oshmasin')

    try:
        image = Image.open(uploaded)
        image.verify()          # buzuq faylni shu yerda ushlaymiz
        uploaded.seek(0)
        image = Image.open(uploaded)
    except Exception as error:      # noqa: BLE001 — Pillow xilma-xil xato beradi
        raise ValidationError('Fayl rasm emas yoki buzilgan') from error

    if image.format and image.format.upper() not in ALLOWED_FORMATS:
        raise ValidationError(f'{image.format} formati qo\'llab-quvvatlanmaydi')

    # Telefon suratlari EXIF da "qaysi tomoni yuqori" ni saqlaydi.
    # Hisobga olinmasa avatar yonboshlab ko'rinadi.
    image = ImageOps.exif_transpose(image)

    # Shaffoflik JPEG da qora bo'lib chiqadi — oq fon qo'yamiz
    if image.mode in ('RGBA', 'LA', 'P'):
        image = image.convert('RGBA')
        background = Image.new('RGB', image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    else:
        image = image.convert('RGB')

    # Markazdan kvadrat: avatar doira ichida ko'rsatiladi, cho'zilgan
    # rasm esa yomon ko'rinadi
    image = ImageOps.fit(image, (SIZE, SIZE), method=Image.LANCZOS,
                         centering=(0.5, 0.5))

    buffer = io.BytesIO()
    # `exif` berilmaydi — qayta yozish uni tozalaydi va suratga olingan
    # joy koordinatalari saqlanmaydi
    image.save(buffer, format='JPEG', quality=QUALITY, optimize=True)
    return 'avatar.jpg', buffer.getvalue()
