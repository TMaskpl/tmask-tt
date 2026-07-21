import pytest
from django.urls import reverse

from apps.audit_log.models import ConfigAuditLog


@pytest.mark.django_db
class TestAuditLogList:
    def test_requires_login(self, client):
        response = client.get(reverse('audit_log:list'))
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_operator_forbidden(self, auth_client):
        response = auth_client.get(reverse('audit_log:list'))
        assert response.status_code == 403

    def test_admin_can_view(self, admin_client):
        response = admin_client.get(reverse('audit_log:list'))
        assert response.status_code == 200

    def test_shows_entries_newest_first(self, admin_client, admin_user):
        older = ConfigAuditLog.objects.create(
            user=admin_user, model_name='Connection', object_id=1,
            object_repr='A', action='created',
        )
        newer = ConfigAuditLog.objects.create(
            user=admin_user, model_name='Connection', object_id=2,
            object_repr='B', action='created',
        )
        response = admin_client.get(reverse('audit_log:list'))
        entries = list(response.context['entries'])
        assert entries[0].pk == newer.pk
        assert entries[1].pk == older.pk
