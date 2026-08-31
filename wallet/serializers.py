from rest_framework import serializers
from .models import WalletBalance, Transaction


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
