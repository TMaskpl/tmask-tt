import pytest
from django.http import HttpResponse
from django.urls import path
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN, ROLE_OPERATOR, ROLE_READONLY


@require_role(ROLE_ADMIN)
def _admin_only_view(request):
    return HttpResponse('ok')


urlpatterns = [path('__test_admin_only__/', _admin_only_view)]


@pytest.mark.django_db
class TestRequireRole:
    def test_admin_passes_admin_gate(self, admin_client, settings):
        settings.ROOT_URLCONF = __name__
        resp = admin_client.get('/__test_admin_only__/')
        assert resp.status_code == 200

    def test_operator_blocked_by_admin_gate(self, auth_client, settings):
        settings.ROOT_URLCONF = __name__
        resp = auth_client.get('/__test_admin_only__/')
        assert resp.status_code == 403

    def test_readonly_blocked_by_admin_gate(self, readonly_client, settings):
        settings.ROOT_URLCONF = __name__
        resp = readonly_client.get('/__test_admin_only__/')
        assert resp.status_code == 403

    def test_anonymous_redirected_to_login(self, client, settings):
        settings.ROOT_URLCONF = __name__
        resp = client.get('/__test_admin_only__/')
        assert resp.status_code == 302
        assert '/accounts/login/' in resp.url
