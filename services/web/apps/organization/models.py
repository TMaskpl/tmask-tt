from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


def get_organization() -> Organization:
    org, _ = Organization.objects.get_or_create(pk=1, defaults={'name': 'Organizacja'})
    return org
