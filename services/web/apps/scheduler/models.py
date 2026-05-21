from django.conf import settings
from django.db import models

from apps.connections.models import Connection


class ScheduledTransfer(models.Model):
    owner            = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='schedules'
    )
    connection       = models.ForeignKey(
        Connection, on_delete=models.CASCADE, related_name='schedules'
    )
    source_path      = models.CharField(max_length=2000)
    destination_path = models.CharField(max_length=2000)
    cron_expr        = models.CharField(max_length=100)
    enabled          = models.BooleanField(default=True)
    last_run         = models.DateTimeField(null=True, blank=True)
    next_run         = models.DateTimeField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f'{self.connection.name}: {self.cron_expr}'

    class Meta:
        ordering = ['-created_at']
