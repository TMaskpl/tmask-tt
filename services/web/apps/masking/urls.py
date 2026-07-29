from django.urls import path
from . import views

app_name = 'masking'

urlpatterns = [
    path('', views.masking_list, name='list'),
    path('new/', views.masking_create, name='create'),
    path('<int:pk>/edit/', views.masking_edit, name='edit'),
    path('<int:pk>/delete/', views.masking_delete, name='delete'),
    path('columns/', views.masking_columns, name='columns'),
]
