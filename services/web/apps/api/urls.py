from django.urls import path
from . import views

app_name = 'api'

urlpatterns = [
    path('transfers/trigger/connection/<int:connection_id>/', views.trigger_connection, name='trigger_connection'),
    path('transfers/trigger/flow/<int:flow_id>/', views.trigger_flow, name='trigger_flow'),
    path('jobs/<int:job_id>/status/', views.job_status, name='job_status'),
]
