import pytest
from django.urls import reverse
from apps.transfers.models import TransferJob, TransferLog, STATUS_PENDING
from apps.transfers.forms import _validate_transfer_path
from django.core.exceptions import ValidationError


@pytest.mark.django_db
class TestTransferCreateView:
    def test_create_form_renders(self, auth_client):
        response = auth_client.get(reverse('transfers:create'))
        assert response.status_code == 200

    def test_create_transfer_dispatches_celery_task(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks):
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            response = auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'source_path': 'file.tar',
                'destination_path': '/backup/',
            })
        assert response.status_code == 302
        job = TransferJob.objects.get(owner=regular_user)
        assert job.status == STATUS_PENDING
        assert job.source_path == '/transfers/file.tar'
        mock_delay.assert_called_once_with('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': None})

    def test_log_fragment_returns_logs(self, auth_client, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        TransferLog.objects.create(job=job, level='info', message='Transfer started')
        response = auth_client.get(reverse('transfers:log_fragment', args=[job.pk]))
        assert response.status_code == 200
        assert b'Transfer started' in response.content


@pytest.mark.django_db
class TestTransferDetailView:
    def test_detail_renders(self, auth_client, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/src/file.tar',
            destination_path='/dst/',
        )
        response = auth_client.get(reverse('transfers:detail', args=[job.pk]))
        assert response.status_code == 200

    def test_detail_404_for_other_users_job(self, auth_client, admin_user, make_connection):
        job = TransferJob.objects.create(
            owner=admin_user,
            connection=make_connection(admin_user),
            source_path='/src/file.tar',
            destination_path='/dst/',
        )
        response = auth_client.get(reverse('transfers:detail', args=[job.pk]))
        assert response.status_code == 404

    def test_detail_requires_login(self, client, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/src/file.tar',
            destination_path='/dst/',
        )
        response = client.get(reverse('transfers:detail', args=[job.pk]))
        assert response.status_code == 302
        assert '/accounts/login/' in response['Location']


@pytest.mark.django_db
class TestTransferLogsView:
    def test_logs_requires_login(self, client):
        response = client.get(reverse('transfers:logs'))
        assert response.status_code == 302
        assert '/accounts/login/' in response['Location']

    def test_logs_shows_only_own_jobs(self, auth_client, regular_user, admin_user, make_connection):
        own_job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/own/file.tar',
            destination_path='/dst/',
        )
        TransferJob.objects.create(
            owner=admin_user,
            connection=make_connection(admin_user),
            source_path='/other/file.tar',
            destination_path='/dst/',
        )
        response = auth_client.get(reverse('transfers:logs'))
        assert response.status_code == 200
        jobs = list(response.context['jobs'])
        assert all(j.owner == regular_user for j in jobs)
        assert own_job in jobs

    def test_logs_renders_when_no_transfers(self, auth_client):
        response = auth_client.get(reverse('transfers:logs'))
        assert response.status_code == 200

    def test_log_fragment_404_for_other_users_job(self, auth_client, admin_user, make_connection):
        job = TransferJob.objects.create(
            owner=admin_user,
            connection=make_connection(admin_user),
            source_path='/x', destination_path='/y',
        )
        response = auth_client.get(reverse('transfers:log_fragment', args=[job.pk]))
        assert response.status_code == 404


class TestValidateTransferPath:
    def test_accepts_normal_absolute_path(self):
        _validate_transfer_path('/data/backups/file.tar')

    def test_accepts_normal_relative_path(self):
        _validate_transfer_path('backups/file.tar')

    def test_rejects_double_dot_traversal(self):
        with pytest.raises(ValidationError, match='\\.\\.'):
            _validate_transfer_path('../../etc/passwd')

    def test_rejects_double_dot_in_middle(self):
        with pytest.raises(ValidationError):
            _validate_transfer_path('/data/../etc/passwd')

    def test_rejects_windows_style_traversal(self):
        with pytest.raises(ValidationError):
            _validate_transfer_path('data\\..\\etc\\passwd')

    def test_rejects_leading_dash(self):
        with pytest.raises(ValidationError):
            _validate_transfer_path('-rf /tmp')

    def test_rejects_control_characters(self):
        with pytest.raises(ValidationError):
            _validate_transfer_path('/data/file\x00name')
