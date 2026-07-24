from django.urls import path
from . import views

app_name = 'connections'

urlpatterns = [
    path('', views.connection_list, name='list'),
    path('new/', views.connection_create, name='create'),
    path('<int:pk>/edit/', views.connection_edit, name='edit'),
    path('<int:pk>/delete/', views.connection_delete, name='delete'),
    path('<int:pk>/test/', views.connection_test, name='test'),
    path('<int:pk>/scan-hostkey/', views.connection_scan_hostkey, name='scan_hostkey'),
    path('<int:pk>/browse/', views.browse_directory, name='browse'),
    path('db-tables/', views.connection_db_tables, name='db_tables'),
    path('export/', views.connection_export, name='export'),
    path('import/', views.connection_import, name='import'),
]
