from django.contrib import admin
from .models import Station, Connector, StationAmenity, Review


class ConnectorInline(admin.TabularInline):
    model = Connector
    extra = 1
    fields = (
        'label', 'type', 'power_kw', 'status', 'charging_percent',
        'ocpp_connector_id', 'parking_started_at', 'offline_reason',
    )


class StationAmenityInline(admin.TabularInline):
    model = StationAmenity
    extra = 0


@admin.register(Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ('name', 'address', 'status', 'charger_type', 'power_kw',
                    'discount_price_per_kwh', 'price_per_kwh')
    list_filter = ('status', 'charger_type')
    search_fields = ('name', 'address')
    inlines = [ConnectorInline, StationAmenityInline]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('station', 'user', 'rating', 'created_at')
    list_filter = ('rating',)
    search_fields = ('station__name', 'user__username', 'comment')
