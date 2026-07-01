from django.contrib.auth.models import AbstractUser
from django.db import models

ROLE_ADMIN    = 'admin'
ROLE_OPERATOR = 'operator'
ROLE_READONLY = 'readonly'
ROLE_CHOICES  = [(ROLE_ADMIN, 'Admin'), (ROLE_OPERATOR, 'Operator'), (ROLE_READONLY, 'Read-only')]
ROLE_LEVEL    = {ROLE_READONLY: 0, ROLE_OPERATOR: 1, ROLE_ADMIN: 2}


class User(AbstractUser):
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    notify_on_done   = models.BooleanField(default=False)
    notify_on_failed = models.BooleanField(default=True)
    webhook_url       = models.URLField(blank=True, default='')
    webhook_on_done   = models.BooleanField(default=False)
    webhook_on_failed = models.BooleanField(default=True)
    telegram_chat_id   = models.CharField(max_length=50, blank=True, default='')
    telegram_on_done   = models.BooleanField(default=False)
    telegram_on_failed = models.BooleanField(default=True)

    @property
    def role_level(self) -> int:
        return ROLE_LEVEL[self.role]

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def can_operate(self) -> bool:
        return self.role_level >= ROLE_LEVEL[ROLE_OPERATOR]

    class Meta:
        verbose_name = 'Użytkownik'
        verbose_name_plural = 'Użytkownicy'
