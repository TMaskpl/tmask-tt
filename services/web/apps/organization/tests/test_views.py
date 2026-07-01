import pytest


@pytest.mark.django_db
class TestOrganizationSettings:
    def test_admin_can_view_settings_page(self, admin_client):
        resp = admin_client.get('/organization/')
        assert resp.status_code == 200

    def test_admin_can_rename_organization(self, admin_client):
        from apps.organization.models import get_organization
        resp = admin_client.post('/organization/', {'name': 'Acme Corp'})
        assert resp.status_code == 302
        assert get_organization().name == 'Acme Corp'

    def test_operator_cannot_view_settings_page(self, auth_client):
        resp = auth_client.get('/organization/')
        assert resp.status_code == 403

    def test_readonly_cannot_rename_organization(self, readonly_client):
        resp = readonly_client.post('/organization/', {'name': 'Hacked'})
        assert resp.status_code == 403

    def test_empty_name_rejected(self, admin_client):
        from apps.organization.models import get_organization
        original_name = get_organization().name
        resp = admin_client.post('/organization/', {'name': ''})
        assert resp.status_code == 200
        assert get_organization().name == original_name
