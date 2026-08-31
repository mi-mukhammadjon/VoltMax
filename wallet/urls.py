from django.urls import path

from . import views

app_name = 'wallet'

urlpatterns = [
    path('balance/', views.BalanceView.as_view(), name='balance'),
    path('transactions/', views.TransactionListView.as_view(), name='transactions'),
    # To'ldirish usullari — faqat yoqilgan va sozlangan tizimlar
    path('providers/', views.ProviderListView.as_view(), name='providers'),
    path('topup/', views.TopUpView.as_view(), name='topup'),
    path('payments/<int:pk>/', views.PaymentStatusView.as_view(), name='payment_status'),
]
