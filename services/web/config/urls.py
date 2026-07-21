from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('connections/', include('apps.connections.urls')),
    path('flows/', include('apps.flows.urls')),
    path('transfers/', include('apps.transfers.urls')),
    path('db-transfers/', include('apps.db_transfers.urls')),
    path('scheduler/', include('apps.scheduler.urls')),
    path('api/', include('apps.api.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('organization/', include('apps.organization.urls')),
    path('audit-log/', include('apps.audit_log.urls')),
    path('webhook-deliveries/', include('apps.webhook_deliveries.urls')),
    path('', RedirectView.as_view(url='/transfers/', permanent=False)),
]
