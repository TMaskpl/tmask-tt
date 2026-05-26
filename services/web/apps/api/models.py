import hashlib
import secrets
from django.conf import settings
from django.db import models

MAX_TOKENS_PER_USER = 5


class ApiToken(models.Model):
    user         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='api_tokens'
    )
    label        = models.CharField(max_length=100)
    key_hash     = models.CharField(max_length=64, unique=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def generate(cls, user, label: str):
        raw_key = secrets.token_hex(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        token = cls.objects.create(user=user, label=label, key_hash=key_hash)
        return token, raw_key
