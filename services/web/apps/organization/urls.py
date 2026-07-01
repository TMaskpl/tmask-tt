from django.urls import path
from . import views

app_name = 'organization'

urlpatterns = [
    path('', views.organization_settings, name='settings'),
]
