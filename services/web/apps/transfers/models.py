from django.conf import settings
from django.db import models
from django.utils import timezone

STATUS_PENDING = 'pending'
STATUS_RUNNING = 'running'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'
STATUS_CHOICES = [
    (STATUS_PENDING, 'PENDING'),
    (STATUS_RUNNING, 'RUNNING'),
    (STATUS_DONE, 'DONE'),
    (STATUS_FAILED, 'FAILED'),
]

LOG_INFO = 'info'
LOG_WARN = 'warn'
LOG_ERROR = 'error'
LOG_CHOICES = [(LOG_INFO, 'INFO'), (LOG_WARN, 'WARN'), (LOG_ERROR, 'ERROR')]


class TransferJob(models.Model):
    owner            = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='jobs'
    )
    connection       = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='jobs',
        null=True, blank=True,
    )
    flow             = models.ForeignKey(
        'flows.Flow', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='jobs',
    )
    source_path      = models.CharField(max_length=2000)
    destination_path = models.CharField(max_length=2000)
    status           = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    celery_task_id   = models.CharField(max_length=255, null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    started_at       = models.DateTimeField(null=True, blank=True)
    finished_at      = models.DateTimeField(null=True, blank=True)
    error_message    = models.TextField(null=True, blank=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.connection_id and self.flow_id:
            raise ValidationError('Set connection or flow, not both.')
        if not self.connection_id and not self.flow_id:
            raise ValidationError('Set either connection or flow.')

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

    def __str__(self) -> str:
        return f'Job #{self.pk} [{self.status}] {self.source_path}'

    class Meta:
        ordering = ['-created_at']


class TransferLog(models.Model):
    job       = models.ForeignKey(TransferJob, on_delete=models.CASCADE, related_name='logs')
    timestamp = models.DateTimeField(auto_now_add=True)
    level     = models.CharField(max_length=5, choices=LOG_CHOICES, default=LOG_INFO)
    message   = models.TextField()

    class Meta:
        ordering = ['timestamp']
