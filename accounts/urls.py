from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('send-otp/', views.SendOTPView.as_view(), name='send_otp'),
    path('verify-otp/', views.VerifyOTPView.as_view(), name='verify_otp'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('vehicles/', views.VehicleListView.as_view(), name='vehicle_list'),
    path('vehicles/<int:pk>/', views.VehicleDetailView.as_view(), name='vehicle_detail'),
    path('rfid-cards/', views.MyRfidCardsView.as_view(), name='rfid_card_list'),
    path('rfid-cards/<int:pk>/block/', views.MyRfidCardBlockView.as_view(), name='rfid_card_block'),
]
