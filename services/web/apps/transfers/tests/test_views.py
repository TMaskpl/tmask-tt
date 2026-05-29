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
