from django.conf import settings
from django.db import models


class WebhookDeliveryLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='webhook_deliveries',
    )
    job = models.ForeignKey(
        'transfers.TransferJob', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='webhook_deliveries',
    )
    url = models.CharField(max_length=2000)
    success = models.BooleanField()
    skipped = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Wpis dostarczenia webhooka'
        verbose_name_plural = 'Wpisy dostarczenia webhooków'

    def __str__(self):
        state = 'skipped' if self.skipped else ('ok' if self.success else 'failed')
        return f'Webhook #{self.pk} [{state}] job #{self.job_id}'
