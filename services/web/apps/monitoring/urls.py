from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    path('', views.metrics_view, name='metrics'),
]
