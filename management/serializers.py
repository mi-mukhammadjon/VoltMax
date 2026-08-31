from rest_framework import serializers

from .models import UserNotification


class UserNotificationSerializer(serializers.ModelSerializer):
    """Mobil ilovadagi "Bildirishnomalar" ekrani uchun.

    Maydon nomlari camelCase — ilovaning qolgan API'lari bilan bir xil.
    """

    id = serializers.CharField(read_only=True)
    stationId = serializers.IntegerField(source='station_id', read_only=True)
    stationName = serializers.CharField(source='station.name', read_only=True, default=None)
    createdAt = serializers.DateTimeField(source='created_at', read_only=True)
    isRead = serializers.BooleanField(source='is_read', read_only=True)

    class Meta:
        model = UserNotification
        fields = ['id', 'kind', 'title', 'body', 'stationId', 'stationName', 'createdAt', 'isRead']
