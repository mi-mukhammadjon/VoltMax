from rest_framework import serializers
from .models import Station, Connector, StationAmenity, Review

# Maydon nomlari mobil ilovadagi src/types/index.ts'ga aynan mos (camelCase) —
# shunda src/services/api.ts javobni o'zgarishsiz ishlata oladi.


class ConnectorSerializer(serializers.ModelSerializer):
    # Mobil tomonda Connector.id: string — Django'ning integer PK'sini string'ga o'giramiz
    id = serializers.CharField(read_only=True)
    powerKw = serializers.IntegerField(source='power_kw')
    chargingPercent = serializers.IntegerField(source='charging_percent', allow_null=True)

    # Ilovada ulagich bosilganda chiqadigan holat oynasi (ConnectorStatusModal.tsx)
    # shu maydonlardan to'ldiriladi: band foizi, pullik parkovka, xato sababi.
    parkingMode = serializers.BooleanField(source='parking_mode', read_only=True)
    parkingFeePerMin = serializers.IntegerField(
        source='parking_fee_per_min', read_only=True, allow_null=True
    )
    parkingMinutes = serializers.IntegerField(source='parking_minutes', read_only=True)
    estimatedFreeInMinutes = serializers.IntegerField(
        source='estimated_free_in_minutes', read_only=True, allow_null=True
    )
    offlineReason = serializers.CharField(source='offline_reason', read_only=True)

    class Meta:
        model = Connector
        fields = [
            'id', 'label', 'type', 'powerKw', 'status', 'chargingPercent',
            'parkingMode', 'parkingFeePerMin', 'parkingMinutes',
            'estimatedFreeInMinutes', 'offlineReason',
        ]


class StationAmenitySerializer(serializers.ModelSerializer):
    class Meta:
        model = StationAmenity
        fields = ['icon', 'title', 'subtitle']


class StationSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    chargerType = serializers.CharField(source='charger_type')
    powerKw = serializers.IntegerField(source='power_kw')
    pricePerKwh = serializers.IntegerField(source='price_per_kwh')
    originalPricePerKwh = serializers.IntegerField(source='original_price_per_kwh', allow_null=True)
    photoUrl = serializers.SerializerMethodField()
    connectors = ConnectorSerializer(many=True, read_only=True)
    amenities = StationAmenitySerializer(many=True, read_only=True)
    rating = serializers.FloatField(source='average_rating')
    reviewCount = serializers.IntegerField(source='review_count')

    class Meta:
        model = Station
        fields = [
            'id', 'name', 'address', 'latitude', 'longitude',
            'chargerType', 'powerKw', 'pricePerKwh', 'originalPricePerKwh',
            'status', 'rating', 'reviewCount', 'photoUrl', 'connectors', 'amenities',
        ]

    def get_photoUrl(self, obj):
        if not obj.photo:
            return None
        request = self.context.get('request')
        url = obj.photo.url
        return request.build_absolute_uri(url) if request else url


class ReviewSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    userName = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = Review
        fields = ['id', 'userName', 'rating', 'comment', 'createdAt']

    def get_userName(self, obj):
        phone = obj.user.username
        return f'+{phone[:-4]}{"*" * 4}' if len(phone) > 4 else phone
