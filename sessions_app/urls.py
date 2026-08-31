from django.urls import path
from . import views

app_name = 'sessions_app'

urlpatterns = [
    path('', views.SessionListView.as_view(), name='list'),
    path('start/', views.StartSessionView.as_view(), name='start'),
    path('active/', views.ActiveSessionView.as_view(), name='active'),
    path('insights/', views.InsightsView.as_view(), name='insights'),
    path('<int:pk>/', views.SessionDetailView.as_view(), name='detail'),
    path('<int:pk>/stop/', views.StopSessionView.as_view(), name='stop'),
]
