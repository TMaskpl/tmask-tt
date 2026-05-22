from django.contrib.auth.models import AbstractUser
from django.db import models

ROLE_ADMIN = 'admin'
ROLE_USER = 'user'
ROLE_CHOICES = [(ROLE_ADMIN, 'Admin'), (ROLE_USER, 'User')]


class User(AbstractUser):
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_USER)
    notify_on_done   = models.BooleanField(default=False)
    notify_on_failed = models.BooleanField(default=True)

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    class Meta:
        verbose_name = 'Użytkownik'
        verbose_name_plural = 'Użytkownicy'
