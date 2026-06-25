from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.connections.models import Connection


class Flow(models.Model):
    owner       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='flows')
    name        = models.CharField(max_length=100)
    source_conn = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='source_flows')
    source_path = models.CharField(max_length=2000)
    dest_conn   = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='dest_flows')
    dest_path   = models.CharField(max_length=2000)
    verify_checksum = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.source_conn_id == self.dest_conn_id and self.source_path == self.dest_path:
            raise ValidationError('Source and destination cannot be the same file on the same server.')

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']
