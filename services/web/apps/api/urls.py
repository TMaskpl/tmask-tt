from django.urls import path
from . import views

app_name = 'api'

urlpatterns = [
    path('transfers/trigger/connection/<int:connection_id>/', views.trigger_connection, name='trigger_connection'),
    path('transfers/trigger/flow/<int:flow_id>/', views.trigger_flow, name='trigger_flow'),
    path('jobs/<int:job_id>/status/', views.job_status, name='job_status'),
    path('jobs/', views.job_list, name='job_list'),
    path('db-jobs/<int:job_id>/status/', views.db_job_status, name='db_job_status'),
    path('db-jobs/', views.db_job_list, name='db_job_list'),
]
