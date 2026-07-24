from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

STATUS_PENDING = 'pending'
STATUS_RUNNING = 'running'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'
STATUS_CANCELLED = 'cancelled'
STATUS_CHOICES = [
    (STATUS_PENDING, 'PENDING'),
    (STATUS_RUNNING, 'RUNNING'),
    (STATUS_DONE, 'DONE'),
    (STATUS_FAILED, 'FAILED'),
    (STATUS_CANCELLED, 'CANCELLED'),
]

LOG_INFO = 'info'
LOG_WARN = 'warn'
LOG_ERROR = 'error'
LOG_CHOICES = [(LOG_INFO, 'INFO'), (LOG_WARN, 'WARN'), (LOG_ERROR, 'ERROR')]


class DbTransferJob(models.Model):
    owner             = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='db_jobs'
    )
    source_connection = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='db_source_jobs'
    )
    dest_connection   = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='db_dest_jobs'
    )
    engine            = models.CharField(max_length=10, choices=[
        ('postgres', 'Postgres'), ('mysql', 'MySQL'), ('mssql', 'MSSQL'),
    ])
    table_name        = models.CharField(max_length=255, blank=True)
    verify_row_count  = models.BooleanField(default=False)
    status            = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    celery_task_id    = models.CharField(max_length=255, blank=True, default='')
    created_at        = models.DateTimeField(auto_now_add=True)
    started_at        = models.DateTimeField(null=True, blank=True)
    finished_at       = models.DateTimeField(null=True, blank=True)
    error_message     = models.TextField(blank=True, default='')
    cancelled_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cancelled_db_jobs',
    )

    def clean(self):
        if self.source_connection_id and self.dest_connection_id and self.source_connection_id == self.dest_connection_id:
            raise ValidationError('Source and destination connection cannot be the same.')
        if self.source_connection_id and self.dest_connection_id and self.source_connection.kind != self.dest_connection.kind:
            raise ValidationError('Source and destination must be the same database engine.')

    def mark_running(self, task_id: str) -> None:
        self.status = STATUS_RUNNING
        self.celery_task_id = task_id
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'celery_task_id', 'started_at'])

    def mark_done(self) -> None:
        self.status = STATUS_DONE
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'finished_at'])

    def mark_failed(self, message: str) -> None:
        self.status = STATUS_FAILED
        self.error_message = message
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'error_message', 'finished_at'])

    def mark_cancelled(self, by) -> None:
        self.status = STATUS_CANCELLED
        self.cancelled_by = by
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'cancelled_by', 'finished_at'])

    def __str__(self) -> str:
        scope = self.table_name or 'WHOLE DB'
        return f'PgJob #{self.pk} [{self.status}] {scope}'

    class Meta:
        ordering = ['-created_at']


class DbTransferLog(models.Model):
    job       = models.ForeignKey(DbTransferJob, on_delete=models.CASCADE, related_name='logs')
    timestamp = models.DateTimeField(auto_now_add=True)
    level     = models.CharField(max_length=5, choices=LOG_CHOICES, default=LOG_INFO)
    message   = models.TextField()

    class Meta:
        ordering = ['timestamp']
