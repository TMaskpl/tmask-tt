import pytest
from django.urls import reverse
from apps.transfers.models import TransferJob, STATUS_DONE, STATUS_FAILED, STATUS_PENDING


@pytest.mark.django_db
class TestJobStatusEndpoint:
    def _url(self, job_id):
        return reverse('api:job_status', args=[job_id])

    def _get(self, client, job_id, raw_key):
        return client.get(
            self._url(job_id),
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )

    def test_returns_200_with_job_fields(
        self, client, regular_user, make_connection, make_api_token
    ):
        conn = make_connection(regular_user)
        job = TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert data['job_id'] == job.pk
        assert data['status'] == STATUS_PENDING
        assert data['started_at'] is None
        assert data['finished_at'] is None
        assert data['error'] is None

    def test_returns_done_status_with_timestamps(
        self, client, regular_user, make_connection, make_api_token
    ):
        from django.utils import timezone
        conn = make_connection(regular_user)
        now = timezone.now()
        job = TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y',
            status=STATUS_DONE,
            started_at=now,
            finished_at=now,
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == STATUS_DONE
        assert data['started_at'] is not None
        assert data['finished_at'] is not None

    def test_returns_failed_status_with_error(
        self, client, regular_user, make_connection, make_api_token
    ):
        conn = make_connection(regular_user)
        job = TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y',
            status=STATUS_FAILED,
            error_message='Connection refused',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == STATUS_FAILED
        assert data['error'] == 'Connection refused'

    def test_other_users_job_returns_404(
        self, client, regular_user, admin_user, make_connection, make_api_token
    ):
        other_conn = make_connection(admin_user)
        other_job = TransferJob.objects.create(
            owner=admin_user, connection=other_conn,
            source_path='/x', destination_path='/y',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, other_job.pk, raw_key)
        assert response.status_code == 404

    def test_nonexistent_job_returns_404(
        self, client, regular_user, make_api_token
    ):
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, 99999, raw_key)
        assert response.status_code == 404

    def test_no_token_returns_403(self, client, regular_user, make_connection):
        conn = make_connection(regular_user)
        job = TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y',
        )
        response = client.get(self._url(job.pk))
        assert response.status_code == 403
