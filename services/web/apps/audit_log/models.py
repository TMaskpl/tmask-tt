from django.conf import settings
from django.db import models

ACTION_CREATED = 'created'
ACTION_UPDATED = 'updated'
ACTION_DELETED = 'deleted'
ACTION_CHOICES = [
    (ACTION_CREATED, 'Utworzono'),
    (ACTION_UPDATED, 'Zmieniono'),
    (ACTION_DELETED, 'Usunięto'),
]


class ConfigAuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='config_audit_entries',
    )
    model_name = models.CharField(max_length=50)
    object_id = models.PositiveIntegerField()
    object_repr = models.CharField(max_length=255)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    changed_fields = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Wpis audytu konfiguracji'
        verbose_name_plural = 'Wpisy audytu konfiguracji'

    def __str__(self):
        return f'{self.get_action_display()} {self.model_name} #{self.object_id}'
