from django.conf import settings
from django.db import models

from apps.connections.models import Connection


class ScheduledTransfer(models.Model):
    owner            = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='schedules'
    )
    connection       = models.ForeignKey(
        Connection, on_delete=models.CASCADE, related_name='schedules',
        null=True, blank=True,
    )
    flow             = models.ForeignKey(
        'flows.Flow', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='schedules',
    )
    source_path      = models.CharField(max_length=2000, blank=True)
    destination_path = models.CharField(max_length=2000, blank=True)
    cron_expr        = models.CharField(max_length=100)
    enabled          = models.BooleanField(default=True)
    last_run         = models.DateTimeField(null=True, blank=True)
    next_run         = models.DateTimeField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.connection_id and self.flow_id:
            raise ValidationError('Set connection or flow, not both.')
        if not self.connection_id and not self.flow_id:
            raise ValidationError('Set either connection or flow.')

    def __str__(self) -> str:
        label = self.flow.name if self.flow_id else self.connection.name
        return f'{label}: {self.cron_expr}'

    class Meta:
        ordering = ['-created_at']
