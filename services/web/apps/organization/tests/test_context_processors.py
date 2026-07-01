import pytest


@pytest.mark.django_db
class TestOrganizationContextProcessor:
    def test_authenticated_request_gets_organization_name_in_navbar(self, auth_client):
        from apps.organization.models import get_organization
        get_organization()  # ensure the row exists with default name
        resp = auth_client.get('/transfers/')
        assert b'Organizacja' in resp.content

    def test_anonymous_request_does_not_crash(self, client):
        resp = client.get('/accounts/login/')
        assert resp.status_code == 200
