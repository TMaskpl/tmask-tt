from django.urls import path
from . import views

app_name = 'flows'

urlpatterns = [
    path('', views.flow_list, name='list'),
    path('new/', views.flow_create, name='create'),
    path('<int:pk>/edit/', views.flow_edit, name='edit'),
    path('<int:pk>/delete/', views.flow_delete, name='delete'),
    path('<int:pk>/run/', views.flow_run, name='run'),
]
