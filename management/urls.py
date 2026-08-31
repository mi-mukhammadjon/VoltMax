from django.urls import path

from . import views

app_name = 'notifications'

urlpatterns = [
    path('', views.NotificationListView.as_view(), name='list'),
    path('read-all/', views.NotificationReadAllView.as_view(), name='read_all'),
    # Telefonning push manzili — ilova har ishga tushganda yuboradi
    path('device/', views.DeviceTokenView.as_view(), name='device'),
    path('<int:pk>/read/', views.NotificationReadView.as_view(), name='read'),
]
