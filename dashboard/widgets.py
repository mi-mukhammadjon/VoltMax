"""Pul kiritish maydoni.

`<input type="number">` bo'shliqli qiymatni qabul qilmaydi (brauzer uni
yaroqsiz deb hisoblaydi), shuning uchun pul maydonlari matn inputiga
o'tkaziladi. Vergul ham, nuqta ham kasr ajratgichi sifatida qabul qilinadi;
ming ajratgichlarini interfeys o'zi qo'yadi:

    <input type="text" inputmode="decimal" class="money-input" value="123 000.00">

Ekranda ajratgichlar bilan ko'rinadi, serverga esa toza son bo'lib keladi —
`value_from_datadict` bo'shliqlarni olib tashlaydi. Klaviatura mobil qurilmada
ham raqamli bo'lib ochiladi (`inputmode`).
"""

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import forms

NBSP = ' '   # uzuluvchi bo'lmagan bo'shliq

# Oxiridagi kasr qismi: ".00", ".5" — undan oldingi nuqtalar ajratgich
DECIMAL_TAIL = re.compile(r'\.\d{1,2}$')


def strip_separators(value):
    """Kiritilgan matndan toza sonni ajratib oladi.

    Vergul ham, nuqta ham KASR ajratgichi hisoblanadi — "1500,50" va
    "1500.50" bir xil o'qiladi. Ming ajratgichi sifatida faqat bo'shliq
    ishlatiladi (uni interfeys o'zi qo'yadi).
    """
    if not isinstance(value, str):
        return value

    # Har xil bo'shliqlar — ming ajratgichi, olib tashlanadi
    for space in (NBSP, ' ', ' ', ' '):
        value = value.replace(space, '')

    # Vergulni nuqtaga keltiramiz; birinchisidan keyingilari e'tiborsiz
    value = value.replace(',', '.')
    head, sep, tail = value.partition('.')
    return head + sep + tail.replace('.', '') if sep else head


def format_money(value):
    """`1500` -> `1 500.00`"""
    if value in (None, ''):
        return ''
    try:
        amount = float(strip_separators(str(value)))
    except (TypeError, ValueError):
        return value
    return f'{amount:,.2f}'.replace(',', NBSP)


class MoneyInput(forms.TextInput):
    """Summa uchun matn inputi — ajratgichlar bilan ko'rsatadi, toza son qaytaradi."""

    def __init__(self, attrs=None):
        defaults = {
            'inputmode': 'decimal',
            'autocomplete': 'off',
            'class': 'money-input',
            'placeholder': '1 500',
            # Nuqta/vergul ming ajratgichi sifatida qabul qilinishini eslatamiz
            'title': "Kasr uchun nuqta yoki vergul ishlatishingiz mumkin (1500,50 = 1500.50)",
        }
        if attrs:
            defaults.update(attrs)
        super().__init__(defaults)

    def format_value(self, value):
        return format_money(value)

    def value_from_datadict(self, data, files, name):
        """Formaga toza son qaytaradi.

        Summalar bazada butun so'mda saqlanadi (tiyin ishlatilmaydi), shuning
        uchun kasr kiritilsa eng yaqin butun songa yaxlitlanadi:
        1 500.50 -> 1 501, 1 500.49 -> 1 500.
        """
        raw = strip_separators(super().value_from_datadict(data, files, name))
        if not isinstance(raw, str) or '.' not in raw:
            return raw
        try:
            return str(int(Decimal(raw).quantize(Decimal('1'), rounding=ROUND_HALF_UP)))
        except (InvalidOperation, ValueError):
            return raw


class ImageDropInput(forms.ClearableFileInput):
    """Rasm yuklash maydoni — joriy rasm ko'rinadi, o'chirish bir bosishda.

    Django'ning standart ko'rinishi "Currently: .../x.png [ ] Clear" degan
    matn va belgilash qutisidan iborat: rasm ko'rinmaydi, o'chirish esa
    qutini belgilab, keyin saqlashni talab qiladi.

    Bu yerda ko'rinish almashtiriladi, lekin SERVER TARAFI o'zgarmaydi —
    `ClearableFileInput` ning `<name>-clear` mexanizmi saqlanib qoladi, faqat
    belgilash qutisi o'rniga yashirin maydon turadi va uni tugma to'ldiradi.
    Shu sababli formalarda qo'shimcha maydon yoki `clean()` mantiq kerak emas.
    """

    template_name = 'dashboard/widgets/image_input.html'

    def __init__(self, attrs=None):
        defaults = {'class': 'id-input', 'accept': 'image/*'}
        if attrs:
            defaults.update(attrs)
        super().__init__(defaults)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        widget = context['widget']

        # `value.name` — bazadagi to'liq yo'l ('stations/2026/08/hero.png').
        # Foydalanuvchiga faqat fayl nomi ko'rsatiladi.
        raw_name = getattr(value, 'name', '') or ''
        widget['basename'] = raw_name.rsplit('/', 1)[-1]
        return context


class PhoneInput(forms.TextInput):
    """Telefon raqami maydoni.

    Yozilgani sari `+998 (90) 123-45-67` ko'rinishiga keladi (app.js), lekin
    serverga kanonik holda beriladi — `value_from_datadict` formatlashni
    olib tashlaydi. Shunda bazada bir xil raqam har xil yozilib qolmaydi.
    """

    input_type = 'tel'

    def __init__(self, attrs=None):
        defaults = {
            'class': 'phone-input',
            'inputmode': 'tel',
            'autocomplete': 'tel',
            'placeholder': '+998 (90) 123-45-67',
            'maxlength': 19,          # +998 (90) 123-45-67
        }
        defaults.update(attrs or {})
        super().__init__(defaults)

    def format_value(self, value):
        from .phones import format_phone

        return format_phone(value) or None

    def value_from_datadict(self, data, files, name):
        from .phones import normalize_phone

        return normalize_phone(super().value_from_datadict(data, files, name))


class BankAccountInput(forms.TextInput):
    """Bank hisob raqami maydoni.

    Yozilgani sari `20208 000 5 00123612 001` ko'rinishiga keladi (app.js),
    serverga esa faqat raqamlar bo'lib keladi — bo'laklar bazaga tushmaydi.
    Aks holda bir xil hisob raqami ikki xil yozilib qolardi va tekshiruv ham
    bo'shliqlarga urilib xato berardi.
    """

    def __init__(self, attrs=None):
        defaults = {
            'class': 'account-input',
            'inputmode': 'numeric',
            'autocomplete': 'off',
            'placeholder': '20208 000 5 00123612 001',
            'maxlength': 24,          # 20 raqam + 4 bo'shliq
        }
        defaults.update(attrs or {})
        super().__init__(defaults)

    def format_value(self, value):
        from .banking import format_account

        return format_account(value) or None

    def value_from_datadict(self, data, files, name):
        from .banking import normalize_account

        return normalize_account(super().value_from_datadict(data, files, name))


class InnInput(forms.TextInput):
    """STIR maydoni — `305 123 456`.

    Hisob raqamidagi kabi: ekranda bo'laklangan, bazada faqat raqamlar.
    """

    def __init__(self, attrs=None):
        defaults = {
            'class': 'inn-input',
            'inputmode': 'numeric',
            'autocomplete': 'off',
            'placeholder': '305 123 456',
            'maxlength': 11,          # 9 raqam + 2 bo'shliq
        }
        defaults.update(attrs or {})
        super().__init__(defaults)

    def format_value(self, value):
        from .banking import format_inn

        return format_inn(value) or None

    def value_from_datadict(self, data, files, name):
        from .banking import normalize_inn

        return normalize_inn(super().value_from_datadict(data, files, name))
