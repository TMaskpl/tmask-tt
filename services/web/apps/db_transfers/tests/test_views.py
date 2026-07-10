from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.db_transfers.models import PgTransferJob


@pytest.mark.django_db
class TestDbTransferCreate:
    def test_requires_login(self, client):
        response = client.get(reverse('db_transfers:create'))
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_readonly_cannot_create(self, readonly_client):
        response = readonly_client.get(reverse('db_transfers:create'))
        assert response.status_code == 403

    def test_create_whole_db_transfer_dispatches_task(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        with patch('apps.db_transfers.views.current_app') as mock_app:
            mock_app.send_task.return_value.id = 'task-123'
            response = auth_client.post(reverse('db_transfers:create'), {
                'source_connection': src.pk, 'dest_connection': dst.pk,
                'scope': 'whole_db', 'table_name': '', 'verify_row_count': False,
            })
        assert response.status_code == 302
        job = PgTransferJob.objects.get()
        assert job.table_name == ''
        assert job.owner == regular_user

    def test_table_scope_requires_table_name(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        response = auth_client.post(reverse('db_transfers:create'), {
            'source_connection': src.pk, 'dest_connection': dst.pk,
            'scope': 'table', 'table_name': '', 'verify_row_count': False,
        })
        assert response.status_code == 200
        assert response.context['form'].errors

    def test_rejects_same_source_and_dest(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        response = auth_client.post(reverse('db_transfers:create'), {
            'source_connection': conn.pk, 'dest_connection': conn.pk,
            'scope': 'whole_db', 'table_name': '', 'verify_row_count': False,
        })
        assert response.status_code == 200
        assert response.context['form'].errors


@pytest.mark.django_db
class TestDbTransferStop:
    def test_operator_can_stop_running_job(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, status='running')
        with patch('apps.db_transfers.views.current_app'):
            response = auth_client.post(reverse('db_transfers:stop', args=[job.pk]))
        assert response.status_code == 302
        job.refresh_from_db()
        assert job.status == 'cancelled'


@pytest.mark.django_db
class TestDbTransferDelete:
    def test_admin_can_delete_finished_job(self, admin_client, admin_user, make_connection):
        src = make_connection(admin_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(admin_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob.objects.create(owner=admin_user, source_connection=src, dest_connection=dst, status='done')
        response = admin_client.post(reverse('db_transfers:delete', args=[job.pk]))
        assert response.status_code == 302
        assert not PgTransferJob.objects.filter(pk=job.pk).exists()

    def test_operator_gets_403(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, status='done')
        response = auth_client.post(reverse('db_transfers:delete', args=[job.pk]))
        assert response.status_code == 403
        assert PgTransferJob.objects.filter(pk=job.pk).exists()

    def test_cannot_delete_running_job(self, admin_client, admin_user, make_connection):
        src = make_connection(admin_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(admin_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob.objects.create(owner=admin_user, source_connection=src, dest_connection=dst, status='running')
        response = admin_client.post(reverse('db_transfers:delete', args=[job.pk]))
        assert response.status_code == 302
        assert PgTransferJob.objects.filter(pk=job.pk).exists()


@pytest.mark.django_db
class TestDbTransferList:
    def test_shows_jobs(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        PgTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst)
        response = auth_client.get(reverse('db_transfers:list'))
        assert response.status_code == 200
        assert len(response.context['jobs']) == 1
