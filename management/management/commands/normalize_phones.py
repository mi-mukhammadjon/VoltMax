"""Bazadagi telefon, STIR va bank hisob raqamlarini tartibga soladi.

Maydonlar ilgari erkin matn edi: bir xil raqam `+998901234567`,
`90 123 45 67`, `998 90 123-45-67` bo'lib yozilgan. Bu qidiruvni buzadi
(bir yozuv bo'yicha izlansa boshqasi topilmaydi) va hujjatlarda ham har xil
ko'rinadi.

Buyruq ularni kanonik holga keltiradi: `+998901234567`.

    python manage.py normalize_phones          # ko'rsatadi, o'zgartirmaydi
    python manage.py normalize_phones --apply  # saqlaydi
"""

from django.core.management.base import BaseCommand

from accounts.models import Company
from dashboard.banking import (
    format_account, format_inn, normalize_account, normalize_inn,
)
from dashboard.phones import format_phone, normalize_phone
from management.models import Partner, SiteSettings

# (model, maydon) juftliklari — panelda operator qo'lda kiritadigan raqamlar
TARGETS = [
    (Company, 'contact_phone'),
    (Partner, 'phone'),
]

# Bank hisob raqamlari — bazada faqat raqamlar bo'lishi kerak, aks holda
# bir xil hisob ikki xil yozilib, qidiruv ham, solishtiruv ham buziladi
ACCOUNT_TARGETS = [
    (Company, 'bank_account'),
]

INN_TARGETS = [
    (Company, 'inn'),
]


class Command(BaseCommand):
    help = "Telefon, STIR va hisob raqamlarini kanonik ko'rinishga keltiradi"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="O'zgarishlarni saqlaydi")

    def handle(self, *args, **options):
        apply_changes = options['apply']
        changed = 0

        for model, field in TARGETS:
            for obj in model.objects.exclude(**{field: ''}):
                current = getattr(obj, field)
                fixed = normalize_phone(current)
                if fixed == current:
                    continue
                changed += 1
                self.stdout.write(
                    f'{model.__name__} #{obj.pk}: {current!r} -> {fixed!r} '
                    f'({format_phone(fixed)})'
                )
                if apply_changes:
                    setattr(obj, field, fixed)
                    obj.save(update_fields=[field])

        for model, field in ACCOUNT_TARGETS:
            for obj in model.objects.exclude(**{field: ''}):
                current = getattr(obj, field)
                fixed = normalize_account(current)
                if fixed == current:
                    continue
                changed += 1
                self.stdout.write(
                    f'{model.__name__} #{obj.pk}: {current!r} -> {fixed!r} '
                    f'({format_account(fixed)})'
                )
                if apply_changes:
                    setattr(obj, field, fixed)
                    obj.save(update_fields=[field])

        for model, field in INN_TARGETS:
            for obj in model.objects.exclude(**{field: ''}):
                current = getattr(obj, field)
                fixed = normalize_inn(current)
                if fixed == current:
                    continue
                changed += 1
                self.stdout.write(
                    f'{model.__name__} #{obj.pk}: {current!r} -> {fixed!r} '
                    f'({format_inn(fixed)})'
                )
                if apply_changes:
                    setattr(obj, field, fixed)
                    obj.save(update_fields=[field])

        settings_obj = SiteSettings.load()
        inn = normalize_inn(settings_obj.org_inn)
        if settings_obj.org_inn and inn != settings_obj.org_inn:
            changed += 1
            self.stdout.write(f'Sozlamalar STIR: {settings_obj.org_inn!r} -> {inn!r}')
            if apply_changes:
                settings_obj.org_inn = inn
                settings_obj.save(update_fields=['org_inn'])

        account = normalize_account(settings_obj.org_bank_account)
        if settings_obj.org_bank_account and account != settings_obj.org_bank_account:
            changed += 1
            self.stdout.write(
                f'Sozlamalar h/r: {settings_obj.org_bank_account!r} -> {account!r}')
            if apply_changes:
                settings_obj.org_bank_account = account
                settings_obj.save(update_fields=['org_bank_account'])

        fixed = normalize_phone(settings_obj.support_phone)
        if settings_obj.support_phone and fixed != settings_obj.support_phone:
            changed += 1
            self.stdout.write(
                f'Sozlamalar: {settings_obj.support_phone!r} -> {fixed!r}')
            if apply_changes:
                settings_obj.support_phone = fixed
                settings_obj.save(update_fields=['support_phone'])

        if not changed:
            self.stdout.write(self.style.SUCCESS("Hamma raqam allaqachon yagona ko'rinishda"))
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS(f'{changed} ta raqam yangilandi'))
        else:
            self.stdout.write(self.style.WARNING(
                f"{changed} ta raqam o'zgaradi. Saqlash uchun: --apply"))
