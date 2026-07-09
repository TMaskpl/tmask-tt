from django.urls import path
from . import views

app_name = 'db_transfers'

urlpatterns = [
    path('', views.db_transfer_list, name='list'),
    path('new/', views.db_transfer_create, name='create'),
    path('<int:pk>/', views.db_transfer_detail, name='detail'),
    path('<int:pk>/logs/', views.log_fragment, name='log_fragment'),
    path('<int:pk>/stop/', views.db_transfer_stop, name='stop'),
]
