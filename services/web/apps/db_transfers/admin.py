from django.contrib import admin
from .models import DbTransferJob, DbTransferLog


class DbTransferLogInline(admin.TabularInline):
    model = DbTransferLog
    readonly_fields = ['timestamp', 'level', 'message']
    extra = 0
    can_delete = False


@admin.register(DbTransferJob)
class DbTransferJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'source_connection', 'dest_connection', 'table_name', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['owner__username', 'table_name', 'source_connection__name', 'dest_connection__name']
    readonly_fields = ['created_at', 'started_at', 'finished_at', 'celery_task_id']
    inlines = [DbTransferLogInline]
