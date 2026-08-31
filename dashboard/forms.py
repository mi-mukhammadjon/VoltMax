from django import forms
from accounts.models import Company, RfidCard
from stations.models import Station, Connector, StationAmenity
from .widgets import (
    BankAccountInput, ImageDropInput, InnInput, MoneyInput, PhoneInput,
)


class LoginForm(forms.Form):
    username = forms.CharField(widget=forms.TextInput(attrs={'autofocus': True}))
    password = forms.CharField(widget=forms.PasswordInput)


class StationForm(forms.ModelForm):
    """Stansiya formasi.

    Holat maydoni yo'q: stansiya bo'sh/band/ishlamayapti ekani qo'lda
    tanlanmaydi, u qurilmaning haqiqiy holatidan hisoblanadi
    (`stations.services.sync_station_status`). Nosozlikni qo'lda belgilash
    Profilaktika bo'limida — u yerda sabab ham, tarix ham saqlanadi.

    Standart narx bu yerda so'ralmaydi — u markazlashgan (Sozlamalar > To'lov).
    Chegirma esa ixtiyoriy: "Chegirma qo'llash" belgilanmaguncha narx maydoni
    yashirin turadi, shunda oddiy stansiya qo'shish bir necha maydonga qisqaradi.
    """

    apply_discount = forms.BooleanField(
        label="Chegirma qo'llash", required=False,
        help_text="Belgilanmasa stansiya standart narxda ishlaydi",
    )

    class Meta:
        model = Station
        fields = [
            'name', 'address', 'latitude', 'longitude',
            'charger_type', 'power_kw', 'discount_price_per_kwh',
            'rating', 'photo', 'ocpp_id', 'partner',
        ]
        widgets = {
            # Koordinatalar qo'lda kiritilmaydi — xaritadan tanlanadi (station-map.js)
            'latitude': forms.HiddenInput(attrs={'id': 'id_latitude'}),
            'longitude': forms.HiddenInput(attrs={'id': 'id_longitude'}),
            'rating': forms.NumberInput(attrs={'step': '0.1', 'min': 0, 'max': 5}),
            'ocpp_id': forms.TextInput(attrs={'placeholder': "bo'sh — hali jismoniy chargerga ulanmagan"}),
            'discount_price_per_kwh': MoneyInput(),
            'photo': ImageDropInput(),
        }
        labels = {
            'charger_type': 'Zaryadlagich turi',
            'power_kw': 'Quvvat (kVt)',
            'discount_price_per_kwh': "Chegirmali narx (so'm/kVt·s)",
            'ocpp_id': 'OCPP Charge Point ID',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['discount_price_per_kwh'].required = False

        # Standart narx markazlashgan — operator uni stansiya formasida emas,
        # Sozlamalar > To'lov bo'limida o'zgartiradi. Bu yerda faqat eslatma.
        from management.models import SiteSettings

        self.standard_price = SiteSettings.load().default_price_per_kwh
        self.fields['discount_price_per_kwh'].help_text = (
            f"Standart narx — {self.standard_price:,} so'm/kVt·s "
            f"(Sozlamalar > To'lov bo'limida o'zgartiriladi)"
        ).replace(',', ' ')

        # Tahrirlashda: narx belgilangan bo'lsa belgilash qutisi yoqilgan holda ochiladi
        if not self.is_bound:
            self.fields['apply_discount'].initial = (
                self.instance.pk is not None and self.instance.discount_price_per_kwh is not None
            )
        self.fields['rating'].required = False
        self.fields['photo'].required = False
        self.fields['ocpp_id'].required = False

    def clean(self):
        data = super().clean()
        price = data.get('discount_price_per_kwh')

        if not data.get('apply_discount'):
            # Belgilanmagan bo'lsa narx saqlanmaydi — stansiya standart narxga qaytadi
            data['discount_price_per_kwh'] = None
            return data

        if price in (None, ''):
            self.add_error('discount_price_per_kwh', "Chegirma narxini kiriting")
        elif price >= self.standard_price:
            self.add_error(
                'discount_price_per_kwh',
                f"Chegirma narxi standart narxdan past bo'lishi kerak "
                f"({self.standard_price:,} so'm)".replace(',', ' '),
            )
        return data


class ConnectorForm(forms.ModelForm):
    """Ulagichning O'ZGARMAS xossalari: yorlig'i, turi, quvvati, OCPP raqami.

    Holat va ishlamaslik sababi bu yerda so'ralmaydi. Ular qurilmadan keladi
    (OCPP StatusNotification) yoki Profilaktika bo'limida qo'lda qo'yiladi —
    u yerda sabab, vaqt va kim o'zgartirgani ham saqlanadi. Formada tanlagich
    turganda operator qo'ygan qiymat qurilmanikiga zid bo'lib qolardi va
    o'zgarishdan hech qanday iz qolmasdi.

    Stansiya kontekst uchun kerak (bitta stansiya ichida yorliq va connectorId
    takrorlanmasligi tekshiriladi), shuning uchun `station=` bilan beriladi;
    tahrirlashda esa mavjud yozuvdan olinadi.
    """

    class Meta:
        model = Connector
        fields = ['label', 'type', 'power_kw', 'ocpp_connector_id']
        widgets = {
            'label': forms.TextInput(attrs={'placeholder': 'A', 'maxlength': 10}),
            'power_kw': forms.NumberInput(attrs={'min': 1, 'max': 1000, 'placeholder': '60'}),
            'ocpp_connector_id': forms.NumberInput(attrs={'min': 1, 'placeholder': 'masalan: 1'}),
        }
        labels = {
            'label': "Yorlig'i",
            'type': 'Turi',
            'power_kw': 'Quvvat (kVt)',
            'ocpp_connector_id': 'OCPP connectorId',
        }
        help_texts = {
            'label': "Foydalanuvchi ko'radigan qisqa belgi: A, B, C",
            'ocpp_connector_id': "Chargerdagi raqamli ulagich (1, 2 …). "
                                 "Bo'sh qoldirilsa qurilma bilan bog'lanmaydi.",
        }

    def __init__(self, *args, station=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ocpp_connector_id'].required = False

        # Yangi ulagichda stansiya tashqaridan, tahrirlashda — yozuvning o'zidan
        self.station = station or (self.instance.station if self.instance.station_id else None)

    def clean_label(self):
        return (self.cleaned_data['label'] or '').strip()

    def clean_ocpp_connector_id(self):
        value = self.cleaned_data.get('ocpp_connector_id')
        # OCPP 1.6 da connectorId=0 ulagich emas, CHARGERNING O'ZI. Bunday
        # qiymat qo'yilsa, qurilma xabarlari hech qachon bu yozuvga tushmasdi.
        if value == 0:
            raise forms.ValidationError(
                "0 — chargerning o'zi uchun ajratilgan. Ulagichlar 1 dan boshlanadi."
            )
        return value

    def clean(self):
        data = super().clean()
        if self.station is None:
            return data

        siblings = Connector.objects.filter(station=self.station)
        if self.instance.pk:
            siblings = siblings.exclude(pk=self.instance.pk)

        # Bazadagi unique_together IntegrityError beradi — bu yerda esa
        # foydalanuvchi tushunadigan xato chiqadi.
        label = data.get('label')
        if label and siblings.filter(label__iexact=label).exists():
            self.add_error('label', f"Bu stansiyada \"{label}\" yorlig'i band")

        ocpp_id = data.get('ocpp_connector_id')
        if ocpp_id and siblings.filter(ocpp_connector_id=ocpp_id).exists():
            self.add_error(
                'ocpp_connector_id',
                f'Bu stansiyada connectorId {ocpp_id} boshqa ulagichga biriktirilgan',
            )

        # Ulagich quvvati stansiyanikidan oshib ketishi mumkin emas — bu odatda
        # xato kiritish belgisi (60 kVt o'rniga 600 yozilishi).
        power = data.get('power_kw')
        if power and self.station.power_kw and power > self.station.power_kw:
            self.add_error(
                'power_kw',
                f"Stansiya quvvati {self.station.power_kw} kVt — "
                f"ulagich undan yuqori bo'la olmaydi",
            )
        return data


class StationAmenityForm(forms.ModelForm):
    class Meta:
        model = StationAmenity
        fields = ['icon', 'title', 'subtitle']
        labels = {
            'icon': 'Ikonka',
            'title': 'Sarlavha',
            'subtitle': 'Qo\'shimcha matn',
        }


# ═══════════════════════════════════════════════════════════════
#  Panel bo'limlari: hamkorlar, aksiyalar, kontent, sozlamalar,
#  xodimlar va rollar
# ═══════════════════════════════════════════════════════════════

from django.contrib.auth.models import Group, Permission, User
from management.models import (
    Banner, ContractSection, FaqItem, Holiday, LegalPage,
    NotificationTemplate, Offer, Partner, PaymentProvider, SiteSettings,
)

_DATETIME_INPUT = forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')


class PartnerForm(forms.ModelForm):
    class Meta:
        model = Partner
        fields = [
            'name', 'legal_name', 'contact_person', 'phone', 'email',
            'address', 'commission_percent', 'is_active',
        ]
        widgets = {
            'phone': PhoneInput(),
            'commission_percent': forms.NumberInput(attrs={'min': 0, 'max': 100}),
        }


class OfferForm(forms.ModelForm):
    class Meta:
        model = Offer
        fields = [
            'title', 'description', 'discount_type', 'discount_value',
            'promo_code', 'stations', 'starts_at', 'ends_at', 'is_active',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'promo_code': forms.TextInput(attrs={'placeholder': 'VOLT2026'}),
            'starts_at': _DATETIME_INPUT,
            'ends_at': _DATETIME_INPUT,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['stations'].required = False
        self.fields['ends_at'].required = False
        # datetime-local input HTML5 formatini kutadi
        for name in ('starts_at', 'ends_at'):
            self.fields[name].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']

    def clean(self):
        data = super().clean()
        starts, ends = data.get('starts_at'), data.get('ends_at')
        if starts and ends and ends <= starts:
            self.add_error('ends_at', "Tugash vaqti boshlanish vaqtidan keyin bo'lishi kerak")
        if data.get('discount_type') == Offer.DiscountType.PERCENT and (data.get('discount_value') or 0) > 100:
            self.add_error('discount_value', "Foiz 100 dan oshmasligi kerak")
        return data


class BannerForm(forms.ModelForm):
    class Meta:
        model = Banner
        fields = ['title', 'subtitle', 'image', 'link_url', 'order', 'is_active']
        widgets = {'image': ImageDropInput()}


class FaqItemForm(forms.ModelForm):
    class Meta:
        model = FaqItem
        fields = ['category', 'question', 'answer', 'order', 'is_active']
        widgets = {'answer': forms.Textarea(attrs={'rows': 4})}


class LegalPageForm(forms.ModelForm):
    class Meta:
        model = LegalPage
        fields = ['title', 'body']
        widgets = {'body': forms.Textarea(attrs={'rows': 16})}


# ── Sozlamalar ──────────────────────────────────────────────────
# Har tab bir nechta BO'LIMdan iborat, har bo'lim alohida saqlanadi.
# Bitta katta forma bo'lganda tasodifiy o'zgargan maydon ham birga
# yozilib ketardi va nima o'zgargani bilinmasdi.
class SettingsGeneralForm(forms.ModelForm):
    """Ilovaning o'zi haqidagi sozlamalar."""

    class Meta:
        model = SiteSettings
        fields = ['app_name', 'support_phone', 'support_telegram']
        widgets = {'support_phone': PhoneInput()}


class SettingsModeForm(forms.ModelForm):
    """Texnik ishlar rejimi — butun tizimga ta'sir qiladi, shuning uchun
    alohida bo'limda va tasdiq bilan.

    `data-confirm`: yoqishdan oldin brauzer so'raydi (app.js). Bunday
    sozlama tasodifan bosilib qolsa, buni darrov payqash qiyin — mobil
    ilovadagi ogohlantirish esa hamma foydalanuvchiga chiqadi.
    """

    class Meta:
        model = SiteSettings
        fields = ['maintenance_mode']
        widgets = {
            'maintenance_mode': forms.CheckboxInput(attrs={
                'data-confirm': "Texnik ishlar rejimi yoqilsa mobil ilovada "
                                "hamma foydalanuvchiga ogohlantirish chiqadi. "
                                "Yoqilsinmi?",
            }),
        }


class SettingsOrgForm(forms.ModelForm):
    """Tashkilot rekvizitlari — shartnoma va hisob-fakturada BIZNING tomon."""

    class Meta:
        model = SiteSettings
        fields = [
            'org_legal_name', 'org_inn', 'org_address', 'org_director',
            'org_bank_name', 'org_bank_account', 'org_bank_mfo',
        ]
        widgets = {
            'org_bank_account': BankAccountInput(),
            'org_inn': InnInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Rekvizitlar shartnoma yozilgunicha to'ldirilmasligi mumkin
        for name in self.fields:
            self.fields[name].required = False

    def clean_org_inn(self):
        return _check_inn(self.cleaned_data.get('org_inn'))

    def clean_org_bank_account(self):
        # Xato hisob raqami shartnoma va hisob-fakturaga tushib ketardi,
        # to'lov esa boshqa hisobga ketardi — buni keyin qaytarish oylab
        # davom etadi. Shuning uchun tekshiruv kiritishning O'ZIDA.
        return _check_account(self.cleaned_data.get('org_bank_account'))


class SettingsPriceForm(forms.ModelForm):
    """Tariflar — o'zgarishi barcha stansiyalarga darhol ta'sir qiladi."""

    class Meta:
        model = SiteSettings
        fields = ['default_price_per_kwh', 'default_parking_fee_per_min',
                  'parking_grace_minutes']
        widgets = {
            'default_price_per_kwh': MoneyInput(),
            'default_parking_fee_per_min': MoneyInput(),
        }


class SettingsTopupForm(forms.ModelForm):
    """Hamyonni to'ldirish chegaralari."""

    class Meta:
        model = SiteSettings
        fields = ['min_topup', 'max_topup', 'min_balance_to_start']
        widgets = {
            'min_topup': MoneyInput(),
            'max_topup': MoneyInput(),
            'min_balance_to_start': MoneyInput(),
        }

    def clean(self):
        data = super().clean()
        low, high = data.get('min_topup'), data.get('max_topup')
        if low and high and low > high:
            self.add_error('max_topup',
                           "Maksimal summa minimaldan kichik bo'lishi mumkin emas")
        return data


class SettingsSessionForm(forms.ModelForm):
    """Sessiya qoidalari va stansiyalarning ish vaqti."""

    class Meta:
        model = SiteSettings
        fields = ['max_session_minutes', 'work_all_day', 'work_start', 'work_end']
        widgets = {
            'work_start': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'work_end': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
        }

    def clean(self):
        data = super().clean()
        if not data.get('work_all_day'):
            start, end = data.get('work_start'), data.get('work_end')
            # Tunga o'tuvchi jadval (22:00 → 06:00) ham bo'lishi mumkin,
            # lekin bir xil vaqt — bu xato kiritish belgisi
            if start and end and start == end:
                self.add_error('work_end', "Boshlanish va tugash vaqti bir xil")
        return data


class SettingsNotificationForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = [
            'push_enabled', 'notify_charging_complete',
            'notify_parking_started', 'notify_low_balance',
        ]


class SettingsRfidForm(forms.ModelForm):
    """Qat'iy rejim — yoqilishi bilan ro'yxatda yo'q kartalar ishlamay qoladi."""

    class Meta:
        model = SiteSettings
        fields = ['require_known_rfid']
        widgets = {
            'require_known_rfid': forms.CheckboxInput(attrs={
                'data-confirm': "Qat'iy rejim yoqilsa tasdiqlanmagan kartalar "
                                "bilan zaryadlash DARHOL to'xtaydi. Yoqilsinmi?",
            }),
        }


class SettingsAccessForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ['otp_ttl_minutes', 'otp_max_attempts', 'session_timeout_minutes']


class NotificationTemplateForm(forms.ModelForm):
    """Bildirishnoma matni. Hodisa o'zgartirilmaydi — u kodga bog'langan."""

    class Meta:
        model = NotificationTemplate
        fields = ['title', 'body', 'is_active']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_title(self):
        value = (self.cleaned_data['title'] or '').strip()
        if not value:
            raise forms.ValidationError("Sarlavha bo'sh bo'lishi mumkin emas")
        return value

    def clean_body(self):
        value = (self.cleaned_data['body'] or '').strip()
        if not value:
            raise forms.ValidationError("Matn bo'sh bo'lishi mumkin emas")
        return value


class PaymentProviderForm(forms.ModelForm):
    """To'lov tashkiloti: identifikatorlari bilan birga."""

    class Meta:
        model = PaymentProvider
        fields = ['name', 'code', 'merchant_id', 'secret_key', 'endpoint_url',
                  'is_active', 'order', 'note']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Payme'}),
            'code': forms.TextInput(attrs={'placeholder': 'payme'}),
            'merchant_id': forms.TextInput(attrs={'placeholder': '5e730e8e0e...'}),
            'secret_key': forms.PasswordInput(render_value=False),
            'note': forms.TextInput(attrs={'placeholder': 'ixtiyoriy izoh'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('merchant_id', 'secret_key', 'endpoint_url', 'note', 'order'):
            self.fields[name].required = False
        # Mavjud kalit formada ko'rsatilmaydi: bo'sh qoldirilsa eskisi qoladi
        if self.instance.pk and self.instance.secret_key:
            self.fields['secret_key'].help_text = (
                "To'ldirilmasa avvalgi kalit saqlanib qoladi")

    def clean_code(self):
        return (self.cleaned_data['code'] or '').strip().lower()

    def clean_secret_key(self):
        value = (self.cleaned_data.get('secret_key') or '').strip()
        # Bo'sh qiymat kalitni o'chirib yubormasligi kerak
        if not value and self.instance.pk:
            return self.instance.secret_key
        return value


class SettingsContractForm(forms.ModelForm):
    """Shartnoma shablonining sarlavha qismi.

    Shartlarning o'zi bu formada emas — ular alohida yozuvlar
    (`ContractSection`), chunki ularni qo'shish, o'chirish va o'rnini
    almashtirish kerak bo'ladi.
    """

    class Meta:
        model = SiteSettings
        fields = ['contract_title', 'contract_city', 'contract_preamble',
                  'contract_appendix_note']
        widgets = {
            'contract_preamble': forms.Textarea(attrs={'rows': 5}),
        }


class SettingsHolidayForm(forms.ModelForm):
    """Bayramlar kalendarining manzili.

    Kunlarning o'zi bu formada emas — ular alohida yozuvlar (`Holiday`):
    Google'dan yangilanadi va qo'lda ham to'ldiriladi.
    """

    class Meta:
        model = SiteSettings
        fields = ['holiday_ics_url']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Manzilsiz ham panel ishlayveradi — shunchaki sinxronlash bo'lmaydi
        self.fields['holiday_ics_url'].required = False


class ContractSectionForm(forms.ModelForm):
    """Shartnomaning bitta bo'limi: sarlavha va bandlar."""

    class Meta:
        model = ContractSection
        fields = ['title', 'body', 'is_active']
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'SHARTNOMA PREDMETI'}),
            'body': forms.Textarea(attrs={'rows': 12}),
        }

    def clean_title(self):
        return (self.cleaned_data['title'] or '').strip()

    def clean_body(self):
        body = (self.cleaned_data.get('body') or '').strip()
        # Bandsiz bo'lim hujjatda bo'sh sarlavha bo'lib qolardi
        if not any(line.strip().lstrip('-').strip() for line in body.splitlines()):
            raise forms.ValidationError("Kamida bitta band yozing")
        return body


# ── Xodimlar (menejer/administrator) ────────────────────────────
class StaffUserForm(forms.ModelForm):
    """Panel xodimini yaratish/tahrirlash. Parol faqat to'ldirilganda o'zgaradi."""

    password = forms.CharField(
        label='Parol', required=False, widget=forms.PasswordInput,
        help_text="Tahrirlashda bo'sh qoldirilsa parol o'zgarmaydi",
    )
    groups = forms.ModelMultipleChoiceField(
        label='Rollar', queryset=Group.objects.all(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active', 'groups']
        labels = {
            'username': 'Login',
            'first_name': 'Ism',
            'last_name': 'Familiya',
            'is_active': 'Faol',
        }

    def __init__(self, *args, is_admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        # Yangi xodim uchun parol majburiy
        if self.instance.pk is None:
            self.fields['password'].required = True
        self._is_admin = is_admin

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        user.is_superuser = self._is_admin
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
            self.save_m2m()
        return user


class RoleForm(forms.ModelForm):
    """Rol = Django Group. Huquqlar panel modellari bo'yicha filtrlanadi."""

    class Meta:
        model = Group
        fields = ['name', 'permissions']
        labels = {'name': 'Rol nomi', 'permissions': 'Huquqlar'}
        widgets = {'permissions': forms.CheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['permissions'].required = False
        self.fields['permissions'].queryset = (
            Permission.objects
            .filter(content_type__app_label__in=[
                'stations', 'sessions_app', 'wallet', 'bookings', 'accounts', 'management', 'auth',
            ])
            .select_related('content_type')
            .order_by('content_type__app_label', 'codename')
        )


def _user_label(user):
    """Foydalanuvchini tanlash ro'yxatidagi yozuv."""
    from .phones import format_phone

    name = user.get_full_name().strip()
    phone = format_phone(user.username)
    return f'{name} · {phone}' if name else phone


class RfidCardForm(forms.ModelForm):
    """RFID kartani qo'lda qo'shish/tahrirlash.

    `id_tag` — chargerda o'qiladigan raqam. U katta harflarga keltiriladi,
    chunki qurilmalar odatda shunday yuboradi va registr farqi tufayli
    karta "topilmay" qolishi mumkin.
    """

    class Meta:
        model = RfidCard
        fields = ['id_tag', 'label', 'user', 'company', 'status', 'expires_at']
        widgets = {
            'id_tag': forms.TextInput(attrs={
                'placeholder': 'masalan: 04A1B2C3D4',
                # Qurilmalar kartani katta harfda yuboradi. Kiritish ham
                # shunday bo'lsin — registr farqi tufayli karta "topilmay"
                # qolmasligi kerak. CSS ko'rinishni, JS esa QIYMATNI ham
                # katta harfga o'giradi (app.js, `data-uppercase`).
                'style': 'text-transform: uppercase;',
                'autocapitalize': 'characters',
                'autocomplete': 'off',
                'spellcheck': 'false',
                'data-uppercase': '1',
            }),
            'label': forms.TextInput(attrs={'placeholder': 'Kim uchun / qaysi maqsadda'}),
            'expires_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }

    def __init__(self, *args, compact=False, **kwargs):
        """`compact=True` — ro'yxat sahifasidagi qatorli forma uchun.

        Holat so'ralmaydi: qo'lda qo'shilgan karta ham "tasdiqlanmagan"
        bo'lib boshlanadi va operator uni ko'rib chiqib tasdiqlaydi. Shunda
        qo'shish va tasdiqlash qadamlari ajralib, tasodifan faol karta
        yaratib qo'yish ehtimoli yo'qoladi.
        """
        super().__init__(*args, **kwargs)
        if compact:
            self.fields.pop('status', None)
            self.fields.pop('expires_at', None)
        self.fields['user'].required = False
        self.fields['company'].required = False
        if 'expires_at' in self.fields:   # qisqa rejimda bu maydon yo'q
            self.fields['expires_at'].required = False
        self.fields['user'].empty_label = "— Egasi yo'q —"
        self.fields['company'].empty_label = '— Korporativ emas —'
        self.fields['company'].queryset = Company.objects.filter(is_active=True)
        # Mobil foydalanuvchining logini — raqamning o'zi. Ro'yxatda u
        # o'qishga qulay ko'rinishda chiqadi: `998901234567` emas,
        # `+998 (90) 123-45-67`
        self.fields['user'].label_from_instance = _user_label
        self.fields['user'].help_text = 'Karta kimda ekani'
        self.fields['company'].help_text = "Belgilansa pul kompaniya hamyonidan yechiladi"

    def clean_id_tag(self):
        value = (self.cleaned_data['id_tag'] or '').strip().upper()
        if not value:
            raise forms.ValidationError('Karta raqamini kiriting')
        qs = RfidCard.objects.filter(id_tag=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Bu karta allaqachon ro\'yxatda')
        return value


def _check_inn(value):
    """STIR — aynan 9 ta raqam. Bo'sh qoldirilishi mumkin."""
    from .banking import INN_LENGTH, digits_only

    digits = digits_only(value)
    if not digits:
        return ''
    if len(digits) != INN_LENGTH:
        raise forms.ValidationError(
            f"{INN_LENGTH} ta raqamdan iborat bo'lishi kerak (hozir {len(digits)} ta)"
        )
    return digits


def _check_account(value):
    """Hisob raqami — aynan 20 ta raqam. Bo'sh qoldirilishi mumkin."""
    from .banking import ACCOUNT_LENGTH, digits_only

    digits = digits_only(value)
    if not digits:
        return ''
    if len(digits) != ACCOUNT_LENGTH:
        # Xabarda maydon nomi takrorlanmaydi: u yo maydon yorlig'i ostida,
        # yo xabar satrida "Hisob raqami: ..." bo'lib chiqadi
        raise forms.ValidationError(
            f"{ACCOUNT_LENGTH} ta raqamdan iborat bo'lishi kerak "
            f"(hozir {len(digits)} ta)"
        )
    return digits


class CompanyFieldsMixin:
    """Korporativ mijoz maydonlarining umumiy qoidalari.

    Mijoz uch xil formada tahrirlanadi: yaratishda — hammasi birga, keyin
    esa batafsil sahifada bo'limlar bo'yicha alohida. Tekshiruvlar bitta
    joyda tursin, aks holda bir formada o'tgan qiymat boshqasida o'tmasdi.
    """

    OPTIONAL = (
        'contact_name', 'contact_phone', 'legal_name', 'inn', 'oked',
        'vat_code', 'legal_address', 'director',
        'bank_name', 'bank_account', 'bank_mfo',
    )

    WIDGETS = {
        'name': forms.TextInput(attrs={'placeholder': 'masalan: Yandex Taksi Toshkent'}),
        'contact_phone': PhoneInput(),
        'inn': InnInput(),
        'oked': forms.TextInput(attrs={'placeholder': '5 xonali kod', 'inputmode': 'numeric'}),
        'legal_address': forms.TextInput(attrs={'placeholder': 'Toshkent sh., ...'}),
        'bank_name': forms.TextInput(attrs={'placeholder': 'masalan: Kapitalbank Toshkent filiali'}),
        'bank_account': BankAccountInput(),
        'bank_mfo': forms.TextInput(attrs={'placeholder': '5 xonali MFO', 'inputmode': 'numeric'}),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Rekvizitlar keyin ham to'ldirilishi mumkin — mijozni ochish uchun
        # faqat nomi kerak, qolgani shartnoma tuzilganda kiritiladi.
        for name in self.OPTIONAL:
            if name in self.fields:
                self.fields[name].required = False

    def _digits_only(self, field, length, label):
        value = (self.cleaned_data.get(field) or '').strip()
        if not value:
            return ''
        digits = ''.join(ch for ch in value if ch.isdigit())
        if digits != value or len(digits) != length:
            raise forms.ValidationError(f"{label} {length} ta raqamdan iborat bo'lishi kerak")
        return digits

    def clean_inn(self):
        return _check_inn(self.cleaned_data.get('inn'))

    def clean_bank_mfo(self):
        return self._digits_only('bank_mfo', 5, 'MFO')

    def clean_bank_account(self):
        return _check_account(self.cleaned_data.get('bank_account'))


class CompanyForm(CompanyFieldsMixin, forms.ModelForm):
    """Yangi korporativ mijoz. Hisob foydalanuvchisi avtomatik yaratiladi —
    forma uni so'ramaydi."""

    class Meta:
        model = Company
        fields = [
            'name', 'contact_name', 'contact_phone', 'is_active',
            # Yuridik va bank rekvizitlari — hisob-faktura uchun
            'legal_name', 'inn', 'oked', 'vat_code', 'legal_address', 'director',
            'bank_name', 'bank_account', 'bank_mfo',
        ]
        widgets = CompanyFieldsMixin.WIDGETS

    def save(self, commit=True):
        if self.instance.pk:
            return super().save(commit)
        # Yangi kompaniya: hamyoni bilan birga yaratiladi
        return Company.create_with_account(**self.cleaned_data)


class CompanyBasicsForm(CompanyFieldsMixin, forms.ModelForm):
    """Batafsil sahifadagi «Mijoz» bo'limi: kim va qanday bog'lanish mumkin."""

    class Meta:
        model = Company
        fields = ['name', 'contact_name', 'contact_phone', 'is_active']
        widgets = CompanyFieldsMixin.WIDGETS


class CompanyRequisitesForm(CompanyFieldsMixin, forms.ModelForm):
    """Batafsil sahifadagi «Rekvizitlar» bo'limi: shartnoma va hisob uchun."""

    class Meta:
        model = Company
        fields = [
            'legal_name', 'inn', 'oked', 'vat_code', 'legal_address', 'director',
            'bank_name', 'bank_account', 'bank_mfo',
        ]
        widgets = CompanyFieldsMixin.WIDGETS


# Batafsil sahifada tahrirlanadigan bo'limlar
COMPANY_SECTIONS = {
    'basics': CompanyBasicsForm,
    'requisites': CompanyRequisitesForm,
}
