from django.urls import path
from . import views

app_name = 'stations'

urlpatterns = [
    path('', views.StationListView.as_view(), name='list'),
    # `<int:pk>` dan OLDIN turishi shart — aks holda 'promo' raqam sifatida
    # o'qilishga urinilardi
    path('promo/check/', views.PromoCheckView.as_view(), name='promo_check'),
    path('<int:pk>/', views.StationDetailView.as_view(), name='detail'),
    path('<int:station_id>/reviews/', views.ReviewListView.as_view(), name='reviews'),
]
