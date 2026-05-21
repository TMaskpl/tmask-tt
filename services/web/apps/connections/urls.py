from django.urls import path
from . import views

app_name = 'connections'

urlpatterns = [
    path('', views.connection_list, name='list'),
    path('new/', views.connection_create, name='create'),
    path('<int:pk>/edit/', views.connection_edit, name='edit'),
    path('<int:pk>/delete/', views.connection_delete, name='delete'),
    path('<int:pk>/test/', views.connection_test, name='test'),
]
