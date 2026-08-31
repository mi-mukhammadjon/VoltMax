from django.contrib import admin
from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('user', 'station', 'scheduled_at', 'duration_minutes', 'estimated_cost', 'status')
    list_filter = ('status',)
    search_fields = ('user__username', 'station__name')
