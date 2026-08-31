from rest_framework import serializers
from .models import RfidCard, Vehicle


class VehicleSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    batteryCapacityKwh = serializers.IntegerField(source='battery_capacity_kwh', required=False, allow_null=True)
    isDefault = serializers.BooleanField(source='is_default', required=False)

    vin = serializers.CharField(required=False, allow_blank=True, max_length=17)

    class Meta:
        model = Vehicle
        fields = ['id', 'name', 'make', 'model', 'year', 'batteryCapacityKwh', 'vin', 'isDefault']

    def validate_vin(self, value):
        """VIN — 17 belgi, faqat lotin harflari va raqamlar.

        Standart bo'yicha I, O va Q ishlatilmaydi (1 va 0 bilan adashmasligi
        uchun), shuning uchun ular rad etiladi. Bo'sh qoldirish mumkin.
        """
        value = (value or '').strip().upper()
        if not value:
            return ''
        if len(value) != 17:
            raise serializers.ValidationError("VIN 17 ta belgidan iborat bo'lishi kerak")
        allowed = set('ABCDEFGHJKLMNPRSTUVWXYZ0123456789')
        if set(value) - allowed:
            raise serializers.ValidationError(
                "VIN'da faqat raqam va lotin harflari bo'ladi (I, O, Q ishlatilmaydi)"
            )
        return value


class SendOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)

    def validate_phone(self, value):
        digits = ''.join(ch for ch in value if ch.isdigit())
        if len(digits) < 9:
            raise serializers.ValidationError("Telefon raqam noto'g'ri")
        return digits


class VerifyOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=6)

    def validate_phone(self, value):
        return ''.join(ch for ch in value if ch.isdigit())


class RfidCardSerializer(serializers.ModelSerializer):
    """Foydalanuvchining o'z kartasi (mobil ilova).

    Foydalanuvchi kartani faqat BLOKLAY va OCHA oladi — qo'shish, o'chirish
    va boshqaga biriktirish operator ishi. Shu sabab `status` yagona
    o'zgartiriladigan maydon, u ham cheklangan qiymatlar bilan.
    """

    id = serializers.CharField(read_only=True)
    idTag = serializers.CharField(source='id_tag', read_only=True)
    companyName = serializers.CharField(source='company.name', read_only=True, default=None)
    lastUsedAt = serializers.DateTimeField(source='last_used_at', read_only=True)
    useCount = serializers.IntegerField(source='use_count', read_only=True)
    isBlocked = serializers.SerializerMethodField()
    canUnblock = serializers.SerializerMethodField()

    class Meta:
        model = RfidCard
        fields = ['id', 'idTag', 'label', 'status', 'companyName',
                  'lastUsedAt', 'useCount', 'isBlocked', 'canUnblock']
        read_only_fields = ['label', 'status']

    def get_isBlocked(self, card) -> bool:
        return card.status == RfidCard.Status.BLOCKED

    def get_canUnblock(self, card) -> bool:
        """Operator bloklagan kartani foydalanuvchi ocha olmaydi.

        Aks holda firibgarlik sababli bloklangan karta darhol qayta
        yoqilib qo'yilardi.
        """
        return card.status == RfidCard.Status.BLOCKED and card.blocked_by_owner
