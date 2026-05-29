from django.contrib import admin
from .models import ScheduledTransfer


@admin.register(ScheduledTransfer)
class ScheduledTransferAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'flow', 'cron_expr', 'enabled', 'last_run', 'next_run']
    list_filter = ['enabled']
    search_fields = ['owner__username', 'flow__name']
    readonly_fields = ['created_at', 'last_run', 'next_run']
