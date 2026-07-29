from django.conf import settings
from django.db import models

FAKER_PROVIDER_CHOICES = [
    ('first_name', 'Imię'),
    ('last_name', 'Nazwisko'),
    ('name', 'Imię i nazwisko'),
    ('email', 'E-mail'),
    ('phone_number', 'Telefon'),
    ('street_address', 'Adres (ulica)'),
    ('city', 'Miasto'),
    ('postcode', 'Kod pocztowy'),
    ('country', 'Kraj'),
    ('company', 'Firma'),
    ('job_title', 'Stanowisko'),
]
FAKER_PROVIDER_KEYS = [key for key, _ in FAKER_PROVIDER_CHOICES]


class MaskingRule(models.Model):
    connection = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='masking_rules',
    )
    table_name = models.CharField(max_length=255)
    column_name = models.CharField(max_length=255)
    faker_provider = models.CharField(max_length=30, choices=FAKER_PROVIDER_CHOICES)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='masking_rules_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('connection', 'table_name', 'column_name')
        ordering = ['connection', 'table_name', 'column_name']
        verbose_name = 'Reguła maskowania'
        verbose_name_plural = 'Reguły maskowania'

    def __str__(self):
        return f'{self.connection.name}.{self.table_name}.{self.column_name} → {self.get_faker_provider_display()}'
