from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/stations/', include('stations.urls')),
    path('api/sessions/', include('sessions_app.urls')),
    path('api/wallet/', include('wallet.urls')),
    # To'lov tizimlari BIZNING serverga murojaat qiladi (webhook)
    path('api/payments/', include('wallet.payment_urls')),
    path('api/bookings/', include('bookings.urls')),
    path('api/notifications/', include('management.urls')),
    path('', include('dashboard.urls')),
]

# Yuklangan fayllar (stansiya rasmlari, bannerlar) DEBUG=False da ham
# ko'rinishi kerak — WhiteNoise faqat statik fayllarni beradi, media'ni emas.
# Bir nusxali panel uchun Django'ning o'zi xizmat qilishi yetarli.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
