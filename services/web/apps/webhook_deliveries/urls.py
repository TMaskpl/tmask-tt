from django.urls import path
from . import views

app_name = 'webhook_deliveries'

urlpatterns = [
    path('', views.webhook_deliveries_list, name='list'),
]
