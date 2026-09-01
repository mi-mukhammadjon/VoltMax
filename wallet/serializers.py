from rest_framework import serializers
from .models import AutoTopUp, SavedCard, Transaction, WalletBalance


class WalletBalanceSerializer(serializers.ModelSerializer):
    currency = serializers.SerializerMethodField()

    class Meta:
        model = WalletBalance
        fields = ['amount', 'currency']

    def get_currency(self, obj):
        return 'UZS'


class TransactionSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    createdAt = serializers.DateTimeField(source='created_at')

    class Meta:
        model = Transaction
        fields = ['id', 'type', 'amount', 'createdAt', 'description']


class TopUpSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1000)


class SavedCardSerializer(serializers.ModelSerializer):
    """Ilovaga ko'rsatiladigan karta.

    TOKEN BU YERDA YO'Q va hech qachon bo'lmaydi: ilova to'lov tokenini
    ko'rmasligi kerak. U faqat «shu karta bilan to'la» deydi, qolganini
    server qiladi. Token ilovaga chiqsa, u telefondan o'g'irlanishi
    mumkin bo'lardi.
    """
    id = serializers.CharField(read_only=True)
    maskedPan = serializers.CharField(source='masked_pan', read_only=True)
    isDefault = serializers.BooleanField(source='is_default', read_only=True)
    isUsable = serializers.BooleanField(source='is_usable', read_only=True)
    stateLabel = serializers.CharField(source='get_state_display', read_only=True)
    providerName = serializers.CharField(source='provider.name', read_only=True)

    class Meta:
        model = SavedCard
        fields = ['id', 'maskedPan', 'brand', 'expires', 'state', 'stateLabel',
                  'isDefault', 'isUsable', 'providerName']


class AutoTopUpSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    cardId = serializers.PrimaryKeyRelatedField(
        source='card', queryset=SavedCard.objects.all())
    isActive = serializers.BooleanField(source='is_active', required=False)
    dailyLimit = serializers.IntegerField(source='daily_limit', read_only=True)
    monthlyLimit = serializers.IntegerField(source='monthly_limit', read_only=True)
    blockedReason = serializers.SerializerMethodField()

    class Meta:
        model = AutoTopUp
        fields = ['id', 'cardId', 'isActive', 'threshold', 'amount',
                  'dailyLimit', 'monthlyLimit', 'blockedReason']

    def get_blockedReason(self, obj):
        return obj.blocked_reason()
