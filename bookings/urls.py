from django.urls import path
from . import views

app_name = 'bookings'

urlpatterns = [
    path('', views.BookingListCreateView.as_view(), name='list'),
    path('<int:pk>/cancel/', views.BookingCancelView.as_view(), name='cancel'),
]
