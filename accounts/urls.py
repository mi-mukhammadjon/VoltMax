from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

app_name = 'accounts'

urlpatterns = [
    path('send-otp/', views.SendOTPView.as_view(), name='send_otp'),
    path('verify-otp/', views.VerifyOTPView.as_view(), name='verify_otp'),
    # `access` tokeni bir soatda tugaydi. Bu manzilsiz ilova jimgina 401
    # qaytarardi va foydalanuvchi "hech narsa yuklanmayapti" holatiga tushardi.
    # Yangilashda YANGI refresh beriladi, eskisi qora ro'yxatga tushadi.
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('vehicles/', views.VehicleListView.as_view(), name='vehicle_list'),
    path('vehicles/<int:pk>/', views.VehicleDetailView.as_view(), name='vehicle_detail'),
    path('rfid-cards/', views.MyRfidCardsView.as_view(), name='rfid_card_list'),
    path('rfid-cards/<int:pk>/block/', views.MyRfidCardBlockView.as_view(), name='rfid_card_block'),
]
