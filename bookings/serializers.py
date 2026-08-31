from rest_framework import serializers

from stations.models import Station, Connector
from .models import Booking


class BookingSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    stationId = serializers.PrimaryKeyRelatedField(source='station', queryset=Station.objects.all())
    stationName = serializers.CharField(source='station.name', read_only=True)
    stationAddress = serializers.CharField(source='station.address', read_only=True)
    connectorId = serializers.PrimaryKeyRelatedField(
        source='connector', queryset=Connector.objects.all(), required=False, allow_null=True
    )
    connectorLabel = serializers.CharField(source='connector.label', read_only=True, default=None)
    scheduledAt = serializers.DateTimeField(source='scheduled_at')
    durationMinutes = serializers.IntegerField(source='duration_minutes', min_value=15, max_value=480)
    estimatedCost = serializers.IntegerField(source='estimated_cost', read_only=True)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id', 'stationId', 'stationName', 'stationAddress', 'connectorId', 'connectorLabel',
            'scheduledAt', 'durationMinutes', 'estimatedCost', 'status', 'createdAt',
        ]
        read_only_fields = ['status']

    def create(self, validated_data):
        station = validated_data['station']
        connector = validated_data.get('connector')
        power_kw = connector.power_kw if connector else station.power_kw
        energy_kwh = power_kw * validated_data['duration_minutes'] / 60
        validated_data['estimated_cost'] = round(energy_kwh * station.price_per_kwh)
        return Booking.objects.create(**validated_data)
