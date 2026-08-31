from django.contrib import admin
from .models import WalletBalance, Transaction


@admin.register(WalletBalance)
class WalletBalanceAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount')
    search_fields = ('user__username',)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'type', 'amount', 'created_at')
    list_filter = ('type',)
    search_fields = ('user__username', 'description')
