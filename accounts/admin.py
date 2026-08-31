from django.contrib import admin
from .models import OTPCode, Vehicle


@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ('phone', 'code', 'created_at', 'is_used')
    list_filter = ('is_used',)
    search_fields = ('phone',)


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'make', 'model', 'year', 'is_default')
    list_filter = ('is_default', 'make')
    search_fields = ('user__username', 'name', 'make', 'model')
