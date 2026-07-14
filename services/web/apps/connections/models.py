from django.conf import settings
from django.db import models
from encrypted_model_fields.fields import EncryptedCharField, EncryptedTextField

PROTOCOL_SFTP = 'sftp'
PROTOCOL_RSYNC = 'rsync'
PROTOCOL_CHOICES = [(PROTOCOL_SFTP, 'SFTP/SCP'), (PROTOCOL_RSYNC, 'rsync')]

KIND_SSH = 'ssh'
KIND_POSTGRES = 'postgres'
KIND_CHOICES = [(KIND_SSH, 'SSH'), (KIND_POSTGRES, 'Postgres')]

class Connection(models.Model):
    owner    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='connections')
    name     = models.CharField(max_length=100)
    host     = models.CharField(max_length=255)
    port     = models.IntegerField(default=22)
    username = models.CharField(max_length=100)
    password = EncryptedCharField(max_length=500, null=True, blank=True)
    ssh_key  = EncryptedTextField(null=True, blank=True)
    protocol = models.CharField(max_length=10, choices=PROTOCOL_CHOICES, default=PROTOCOL_SFTP)
    compress = models.BooleanField(default=False)
    encrypt  = models.BooleanField(default=False)
    strict_host_key_checking = models.BooleanField(default=True)
    known_host_key = models.TextField(blank=True, default='')
    dry_run_before_transfer = models.BooleanField(default=False)
    verify_checksum = models.BooleanField(default=False)
    kind     = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_SSH)
    db_name  = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.host}:{self.port})'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.kind == KIND_POSTGRES and not self.db_name:
            raise ValidationError('DB NAME jest wymagane dla połączeń typu Postgres.')

    class Meta:
        ordering = ['-created_at']
