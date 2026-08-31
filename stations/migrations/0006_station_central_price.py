"""Stansiya narxini markazlashtirish.

Ilgari har bir stansiya o'z `price_per_kwh` va `original_price_per_kwh`
maydonlarini saqlardi. Endi standart narx bitta joyda — Sozlamalar > To'lov
bo'limida (SiteSettings.default_price_per_kwh), stansiyada esa faqat unga xos
chegirma narxi qoladi.

Ma'lumot ko'chirish EHTIYOTKOR: bugungi narxlar aynan saqlanadi. Stansiyaning
joriy narxi markaziy narxdan farq qilsa, u `discount_price_per_kwh` ga
yoziladi — shunda migratsiyadan keyin hech kimning narxi o'zgarib ketmaydi.
Operator keyinchalik shu maydonni bo'shatib, stansiyani markaziy narxga
o'tkazishi mumkin.
"""

from django.db import migrations, models


def move_prices_to_discount(apps, schema_editor):
    Station = apps.get_model('stations', 'Station')
    SiteSettings = apps.get_model('management', 'SiteSettings')

    settings_obj = SiteSettings.objects.first()
    standard = settings_obj.default_price_per_kwh if settings_obj else 1200

    for station in Station.objects.all():
        price = station.price_per_kwh
        # Narx markaziy narxdan farq qilsa — uni saqlab qolamiz.
        # Aks holda maydon bo'sh qoladi va stansiya markaziy narxni kuzatadi.
        station.discount_price_per_kwh = None if price == standard else price
        station.save(update_fields=['discount_price_per_kwh'])


def restore_prices(apps, schema_editor):
    """Ortga qaytarish: chegirma narxi bo'lsa uni, aks holda markaziy narxni yozadi."""
    Station = apps.get_model('stations', 'Station')
    SiteSettings = apps.get_model('management', 'SiteSettings')

    settings_obj = SiteSettings.objects.first()
    standard = settings_obj.default_price_per_kwh if settings_obj else 1200

    for station in Station.objects.all():
        effective = station.discount_price_per_kwh or standard
        station.price_per_kwh = effective
        station.original_price_per_kwh = standard if effective < standard else None
        station.save(update_fields=['price_per_kwh', 'original_price_per_kwh'])


class Migration(migrations.Migration):

    dependencies = [
        ('stations', '0005_station_partner'),
        ('management', '0001_initial'),
    ]

    operations = [
        # 1) Avval yangi maydon qo'shiladi
        migrations.AddField(
            model_name='station',
            name='discount_price_per_kwh',
            field=models.PositiveIntegerField(
                blank=True, null=True,
                help_text="Bo'sh qoldirilsa — sozlamalardagi standart narx qo'llanadi",
                verbose_name="Chegirmali narx (so'm/kVt·s)",
            ),
        ),
        # 2) Mavjud narxlar ko'chiriladi
        migrations.RunPython(move_prices_to_discount, restore_prices),
        # 3) Endi eski maydonlarni olib tashlash xavfsiz
        migrations.RemoveField(model_name='station', name='original_price_per_kwh'),
        migrations.RemoveField(model_name='station', name='price_per_kwh'),
    ]
