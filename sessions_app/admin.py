from django.contrib import admin
from .models import ChargingSession


@admin.register(ChargingSession)
class ChargingSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'station', 'connector_label', 'status', 'started_at', 'stopped_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'station__name')
