from rest_framework import serializers
from .models import ChargingSession


class ChargingSessionSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    stationId = serializers.CharField(source='station_id')
    startedAt = serializers.DateTimeField(source='started_at')
    currentPercent = serializers.IntegerField(source='current_percent')
    powerKw = serializers.IntegerField(source='power_kw')
    elapsedSeconds = serializers.IntegerField(source='elapsed_seconds')
    costSoFar = serializers.IntegerField(source='cost_so_far')
    remainingSeconds = serializers.IntegerField(source='remaining_seconds')
    kwhCharged = serializers.FloatField(source='kwh_charged')
    pricePerKwh = serializers.IntegerField(source='price_per_kwh')
    currentAmps = serializers.FloatField(source='current_amps')
    voltageV = serializers.FloatField(source='voltage_v')
    parkingFeePerMin = serializers.IntegerField(source='parking_fee_per_min')
    # costSoFar UMUMIY summa (energiya + parkovka). Quyidagi ikkitasi ilovada
    # foydalanuvchiga "nega ko'proq" ekanini ajratib ko'rsatish uchun.
    energyCost = serializers.IntegerField(source='energy_cost', read_only=True)
    parkingMinutes = serializers.IntegerField(source='parking_minutes', read_only=True)
    parkingCost = serializers.IntegerField(source='parking_cost', read_only=True)
    # Parkovka daqiqalik yechilgani uchun — qancha qismi allaqachon to'langan
    parkingPaid = serializers.IntegerField(source='parking_billed_amount', read_only=True)
    connectorLabel = serializers.CharField(source='connector_label')
    # Chegirma: chegirmasiz narx, tejalgan summa va sababi. Uchalasi ham
    # kerak — foydalanuvchi "qancha yutdim"ni raqamda ko'radi.
    basePricePerKwh = serializers.IntegerField(source='base_price_per_kwh',
                                               read_only=True, allow_null=True)
    savedAmount = serializers.IntegerField(source='saved_amount', read_only=True)
    priceLabel = serializers.CharField(source='price_label', read_only=True)

    class Meta:
        model = ChargingSession
        fields = [
            'id', 'stationId', 'startedAt', 'status',
            'currentPercent', 'powerKw', 'elapsedSeconds', 'costSoFar',
            'remainingSeconds', 'kwhCharged', 'pricePerKwh',
            'currentAmps', 'voltageV', 'parkingFeePerMin', 'connectorLabel',
            'energyCost', 'parkingMinutes', 'parkingCost', 'parkingPaid',
            'basePricePerKwh', 'savedAmount', 'priceLabel',
        ]


class StartSessionSerializer(serializers.Serializer):
    stationId = serializers.IntegerField()
    connectorId = serializers.IntegerField(required=False)
    # Promo-kod ixtiyoriy. Bo'sh bo'lsa faqat avtomatik aksiyalar
    # qo'llanadi — kodli aksiya kodsiz ishlab ketmasligi kerak.
    promoCode = serializers.CharField(required=False, allow_blank=True, max_length=40)


class SessionHistorySerializer(serializers.ModelSerializer):
    """HistoryScreen uchun — mobil ilovadagi SessionHistoryItem tipiga mos."""
    id = serializers.CharField(read_only=True)
    stationName = serializers.CharField(source='station.name')
    connectorLabel = serializers.CharField(source='connector_label')
    date = serializers.DateTimeField(source='started_at')
    kwhCharged = serializers.FloatField(source='kwh_charged')
    cost = serializers.IntegerField(source='cost_so_far')
    durationMinutes = serializers.SerializerMethodField()
    startPercent = serializers.IntegerField(source='start_percent')
    endPercent = serializers.IntegerField(source='current_percent')

    class Meta:
        model = ChargingSession
        fields = [
            'id', 'stationName', 'connectorLabel', 'date', 'kwhCharged', 'cost', 'durationMinutes',
            'startPercent', 'endPercent',
        ]

    def get_durationMinutes(self, obj):
        return round(obj.elapsed_seconds / 60)
