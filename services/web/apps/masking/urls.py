from django.urls import path
from . import views

app_name = 'masking'

urlpatterns = [
    path('columns/', views.masking_columns, name='columns'),
]
