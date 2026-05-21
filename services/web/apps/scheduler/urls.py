from django.urls import path
from . import views

app_name = 'scheduler'

urlpatterns = [
    path('', views.schedule_list, name='list'),
    path('new/', views.schedule_create, name='create'),
    path('<int:pk>/edit/', views.schedule_edit, name='edit'),
    path('<int:pk>/toggle/', views.schedule_toggle, name='toggle'),
    path('<int:pk>/delete/', views.schedule_delete, name='delete'),
]
