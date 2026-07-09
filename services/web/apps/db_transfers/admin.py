from django.contrib import admin
from .models import PgTransferJob, PgTransferLog


class PgTransferLogInline(admin.TabularInline):
    model = PgTransferLog
    readonly_fields = ['timestamp', 'level', 'message']
    extra = 0
    can_delete = False


@admin.register(PgTransferJob)
class PgTransferJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'source_connection', 'dest_connection', 'table_name', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['owner__username', 'table_name', 'source_connection__name', 'dest_connection__name']
    readonly_fields = ['created_at', 'started_at', 'finished_at', 'celery_task_id']
    inlines = [PgTransferLogInline]
