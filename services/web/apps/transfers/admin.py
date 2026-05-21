from django.contrib import admin
from .models import TransferJob, TransferLog


class TransferLogInline(admin.TabularInline):
    model = TransferLog
    readonly_fields = ['timestamp', 'level', 'message']
    extra = 0
    can_delete = False


@admin.register(TransferJob)
class TransferJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'connection', 'status', 'created_at', 'started_at', 'finished_at']
    list_filter = ['status']
    search_fields = ['owner__username', 'source_path', 'connection__name']
    readonly_fields = ['created_at', 'started_at', 'finished_at', 'celery_task_id']
    inlines = [TransferLogInline]
