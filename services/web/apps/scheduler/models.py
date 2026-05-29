from django.conf import settings
from django.db import models


class ScheduledTransfer(models.Model):
    owner    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='schedules'
    )
    flow     = models.ForeignKey(
        'flows.Flow', on_delete=models.CASCADE, null=True, blank=True,
        related_name='schedules',
    )
    cron_expr   = models.CharField(max_length=100)
    enabled     = models.BooleanField(default=True)
    last_run    = models.DateTimeField(null=True, blank=True)
    next_run    = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.flow_id:
            raise ValidationError('Flow is required.')

    def __str__(self) -> str:
        label = self.flow.name if self.flow_id else '<no flow>'
        return f'{label}: {self.cron_expr}'

    class Meta:
        ordering = ['-created_at']
