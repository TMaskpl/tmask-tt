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
        assert data['connection_id'] == conn.pk
        assert data['flow_id'] is None
        assert data['source_path'] == '/x'
        assert data['destination_path'] == '/y'
        assert 'created_at' in data and data['created_at'] is not None

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

    def test_other_users_job_returns_200(
        self, client, regular_user, admin_user, make_connection, make_api_token
    ):
        other_conn = make_connection(admin_user)
        other_job = TransferJob.objects.create(
            owner=admin_user, connection=other_conn,
            source_path='/x', destination_path='/y',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, other_job.pk, raw_key)
        assert response.status_code == 200

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


@pytest.mark.django_db
class TestOrgWideJobStatus:
    def test_any_authenticated_token_can_read_job_status_of_another_users_job(self, client, django_user_model, make_connection, make_api_token):
        owner = django_user_model.objects.create_user(username='apiowner3', password='p', role='admin')
        conn = make_connection(owner)
        job = TransferJob.objects.create(owner=owner, connection=conn, source_path='/a', destination_path='/b')
        viewer = django_user_model.objects.create_user(username='apiviewer1', password='p', role='readonly')
        _, raw_key = make_api_token(viewer)
        resp = client.get(f'/api/jobs/{job.pk}/status/', HTTP_AUTHORIZATION=f'Token {raw_key}')
        assert resp.status_code == 200


@pytest.mark.django_db
class TestJobListEndpoint:
    def _url(self):
        return reverse('api:job_list')

    def _get(self, client, raw_key, **params):
        return client.get(self._url(), params, HTTP_AUTHORIZATION=f'Token {raw_key}')

    def test_returns_all_jobs(self, client, regular_user, make_connection, make_api_token):
        conn = make_connection(regular_user)
        TransferJob.objects.create(owner=regular_user, connection=conn, source_path='/a', destination_path='/b')
        TransferJob.objects.create(owner=regular_user, connection=conn, source_path='/c', destination_path='/d')
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert len(data['jobs']) == 2

    def test_filters_by_status(self, client, regular_user, make_connection, make_api_token):
        conn = make_connection(regular_user)
        TransferJob.objects.create(owner=regular_user, connection=conn, source_path='/a', destination_path='/b', status=STATUS_DONE)
        failed = TransferJob.objects.create(owner=regular_user, connection=conn, source_path='/c', destination_path='/d', status=STATUS_FAILED)
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key, status='failed')
        assert response.status_code == 200
        data = response.json()
        assert len(data['jobs']) == 1
        assert data['jobs'][0]['job_id'] == failed.pk

    def test_invalid_status_returns_400(self, client, regular_user, make_api_token):
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key, status='not-a-real-status')
        assert response.status_code == 400
        assert 'Invalid status' in response.json()['error']

    def test_empty_list_returns_200_empty_array(self, client, regular_user, make_api_token):
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        assert response.json()['jobs'] == []

    def test_respects_page_size_cap(self, client, regular_user, make_connection, make_api_token):
        conn = make_connection(regular_user)
        TransferJob.objects.bulk_create([
            TransferJob(owner=regular_user, connection=conn, source_path='/x', destination_path='/y')
            for _ in range(205)
        ])
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        assert len(response.json()['jobs']) == 200

    def test_no_token_returns_403(self, client, regular_user):
        response = client.get(self._url())
        assert response.status_code == 403

    def test_shows_other_users_jobs(self, client, regular_user, admin_user, make_connection, make_api_token):
        other_conn = make_connection(admin_user)
        TransferJob.objects.create(owner=admin_user, connection=other_conn, source_path='/a', destination_path='/b')
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        assert len(response.json()['jobs']) == 1
