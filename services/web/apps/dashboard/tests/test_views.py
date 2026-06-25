import json
import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone

from apps.transfers.models import TransferJob, STATUS_DONE


def _make_job(user, connection, status=STATUS_DONE, days_ago=0):
    job = TransferJob.objects.create(
        owner=user, connection=connection,
        source_path='/s', destination_path='/d', status=status,
    )
    TransferJob.objects.filter(pk=job.pk).update(
        created_at=timezone.now() - timedelta(days=days_ago)
    )
    return job


@pytest.mark.django_db
class TestDashboardView:
    def test_requires_login(self, client):
        response = client.get(reverse('dashboard:index'))
        assert response.status_code == 302
        assert '/accounts/login' in response.url

    def test_renders_200_with_data(self, auth_client, regular_user, make_connection):
        _make_job(regular_user, make_connection(regular_user))
        response = auth_client.get(reverse('dashboard:index'))
        assert response.status_code == 200
        data = response.context['data']
        assert set(data.keys()) == {'per_day', 'success', 'top'}

    def test_per_user_isolation(self, auth_client, regular_user, admin_user, make_connection):
        # job innego użytkownika nie może wpływać na agregaty regular_user
        _make_job(admin_user, make_connection(admin_user, name='AdminConn'))
        response = auth_client.get(reverse('dashboard:index'))
        assert response.context['data']['success']['total'] == 0

    def test_json_script_present(self, auth_client, regular_user, make_connection):
        _make_job(regular_user, make_connection(regular_user))
        response = auth_client.get(reverse('dashboard:index'))
        html = response.content.decode()
        assert 'id="dashboard-data"' in html
        assert 'type="application/json"' in html
        # zawartość json_script musi być poprawnym JSON
        start = html.index('id="dashboard-data"')
        snippet = html[start:start + 2000]
        assert '"per_day"' in snippet and '"success"' in snippet
