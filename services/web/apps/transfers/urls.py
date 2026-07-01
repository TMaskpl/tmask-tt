from django.urls import path
from . import views

app_name = 'transfers'

urlpatterns = [
    path('', views.transfer_create, name='create'),
    path('<int:pk>/', views.transfer_detail, name='detail'),
    path('<int:pk>/logs/', views.log_fragment, name='log_fragment'),
    path('<int:pk>/stop/', views.transfer_stop, name='stop'),
    path('logs/', views.transfer_logs, name='logs'),
]
