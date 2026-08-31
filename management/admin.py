from django.contrib import admin

from .models import Banner, FaqItem, LegalPage, Offer, Partner, SiteSettings


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'phone', 'commission_percent', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'legal_name', 'contact_person')


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ('title', 'discount_type', 'discount_value', 'promo_code', 'starts_at', 'ends_at', 'is_active')
    list_filter = ('is_active', 'discount_type')
    search_fields = ('title', 'promo_code')
    filter_horizontal = ('stations',)


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'order', 'is_active')
    list_filter = ('is_active',)


@admin.register(FaqItem)
class FaqItemAdmin(admin.ModelAdmin):
    list_display = ('question', 'category', 'order', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('question', 'answer')


@admin.register(LegalPage)
class LegalPageAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'updated_at')


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('app_name', 'maintenance_mode', 'updated_at')

    def has_add_permission(self, request):
        # Singleton — faqat bitta yozuv bo'ladi
        return not SiteSettings.objects.exists()
