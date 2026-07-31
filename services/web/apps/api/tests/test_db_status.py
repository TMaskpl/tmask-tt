import pytest
from django.urls import reverse
from apps.db_transfers.models import DbTransferJob


@pytest.mark.django_db
class TestDbJobStatusEndpoint:
    def _url(self, job_id):
        return reverse('api:db_job_status', args=[job_id])

    def _get(self, client, job_id, raw_key):
        return client.get(
            self._url(job_id),
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )

    def test_returns_200_with_job_fields(
        self, client, regular_user, make_connection, make_api_token
    ):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst,
            engine='postgres', table_name='users',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert data['job_id'] == job.pk
        assert data['status'] == 'pending'
        assert data['engine'] == 'postgres'
        assert data['source_connection_id'] == src.pk
        assert data['dest_connection_id'] == dst.pk
        assert data['table_name'] == 'users'
        assert data['created_at'] is not None
        assert data['started_at'] is None
        assert data['finished_at'] is None
        assert data['error'] is None

    def test_whole_db_transfer_has_null_table_name(
        self, client, regular_user, make_connection, make_api_token
    ):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst,
            engine='postgres', table_name='',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        assert response.json()['table_name'] is None

    def test_returns_done_status_with_timestamps(
        self, client, regular_user, make_connection, make_api_token
    ):
        from django.utils import timezone
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        now = timezone.now()
        job = DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst,
            engine='postgres', status='done', started_at=now, finished_at=now,
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'done'
        assert data['started_at'] is not None
        assert data['finished_at'] is not None

    def test_returns_failed_status_with_error(
        self, client, regular_user, make_connection, make_api_token
    ):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst,
            engine='postgres', status='failed', error_message='Connection refused',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        assert response.json()['error'] == 'Connection refused'

    def test_other_users_job_returns_200(
        self, client, regular_user, admin_user, make_connection, make_api_token
    ):
        src = make_connection(admin_user, kind='postgres', db_name='proddb', name='src2')
        dst = make_connection(admin_user, kind='postgres', db_name='testdb', name='dst2')
        job = DbTransferJob.objects.create(
            owner=admin_user, source_connection=src, dest_connection=dst, engine='postgres',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200

    def test_nonexistent_job_returns_404(self, client, regular_user, make_api_token):
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, 99999, raw_key)
        assert response.status_code == 404

    def test_no_token_returns_403(self, client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres',
        )
        response = client.get(self._url(job.pk))
        assert response.status_code == 403


@pytest.mark.django_db
class TestDbJobListEndpoint:
    def _url(self):
        return reverse('api:db_job_list')

    def _get(self, client, raw_key, **params):
        return client.get(self._url(), params, HTTP_AUTHORIZATION=f'Token {raw_key}')

    def test_returns_all_jobs(self, client, regular_user, make_connection, make_api_token):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        DbTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres')
        DbTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres', table_name='orders')
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        assert len(response.json()['jobs']) == 2

    def test_filters_by_status(self, client, regular_user, make_connection, make_api_token):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        DbTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres', status='done')
        failed = DbTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres', status='failed')
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

    def test_no_token_returns_403(self, client, regular_user):
        response = client.get(self._url())
        assert response.status_code == 403
