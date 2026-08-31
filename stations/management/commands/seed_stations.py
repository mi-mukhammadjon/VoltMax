from django.core.management.base import BaseCommand
from stations.models import Station, Connector, StationAmenity


class Command(BaseCommand):
    help = "Mobil ilovadagi mock stansiyalarga mos namuna ma'lumot qo'shadi (faqat baza bo'sh bo'lsa)"

    def handle(self, *args, **options):
        if Station.objects.exists():
            self.stdout.write('Stansiyalar allaqachon mavjud — o\'tkazib yuborildi')
            return

        st1 = Station.objects.create(
            name='VoltMax Chilonzor',
            address="Chilonzor tumani, Bunyodkor shoh ko'chasi 12",
            latitude=41.2856, longitude=69.2034,
            charger_type=Station.ChargerType.DC, power_kw=160,
            discount_price_per_kwh=1900,
            status=Station.Status.AVAILABLE, rating=4.8,
        )
        Connector.objects.create(station=st1, label='A', type='DC', power_kw=80, status=Connector.Status.CHARGING, charging_percent=97)
        Connector.objects.create(station=st1, label='B', type='DC', power_kw=80, status=Connector.Status.AVAILABLE)
        StationAmenity.objects.create(station=st1, icon=StationAmenity.Icon.OIL, title='Bepul moy almashtirish', subtitle='Mukofot')

        st2 = Station.objects.create(
            name='VoltMax Yunusobod',
            address="Yunusobod tumani, Amir Temur shoh ko'chasi 45",
            latitude=41.3453, longitude=69.2879,
            charger_type=Station.ChargerType.AC, power_kw=20,
            discount_price_per_kwh=1900,
            status=Station.Status.BUSY, rating=4.5,
        )
        Connector.objects.create(station=st2, label='A', type='AC', power_kw=20, status=Connector.Status.CHARGING, charging_percent=62)
        Connector.objects.create(station=st2, label='B', type='AC', power_kw=20, status=Connector.Status.OFFLINE)

        st3 = Station.objects.create(
            name="VoltMax Mirzo Ulug'bek",
            address="Mirzo Ulug'bek tumani, Universitet ko'chasi 4",
            latitude=41.3306, longitude=69.3308,
            charger_type=Station.ChargerType.DC, power_kw=120,
            discount_price_per_kwh=1900,
            status=Station.Status.AVAILABLE, rating=4.9,
        )
        Connector.objects.create(station=st3, label='A', type='DC', power_kw=120, status=Connector.Status.AVAILABLE)

        st4 = Station.objects.create(
            name='VoltMax Sergeli',
            address="Sergeli tumani, Qoshtepa ko'chasi 7",
            latitude=41.2264, longitude=69.2401,
            charger_type=Station.ChargerType.AC, power_kw=22,
            discount_price_per_kwh=1800,
            status=Station.Status.OFFLINE, rating=4.2,
        )
        Connector.objects.create(station=st4, label='A', type='AC', power_kw=22, status=Connector.Status.OFFLINE)

        self.stdout.write(self.style.SUCCESS('4 ta namuna stansiya qo\'shildi'))
