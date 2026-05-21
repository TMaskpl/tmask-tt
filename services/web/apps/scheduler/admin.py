from django.contrib import admin
from .models import ScheduledTransfer


@admin.register(ScheduledTransfer)
class ScheduledTransferAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'connection', 'cron_expr', 'enabled', 'last_run', 'next_run']
    list_filter = ['enabled']
    search_fields = ['owner__username', 'connection__name', 'source_path']
    readonly_fields = ['created_at', 'last_run', 'next_run']
