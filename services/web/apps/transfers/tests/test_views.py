from types import SimpleNamespace
import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.transfers.models import TransferJob, TransferLog, STATUS_PENDING
from apps.transfers.forms import _validate_transfer_path
from django.core.exceptions import ValidationError


@pytest.mark.django_db
class TestTransferCreateView:
    def test_create_form_renders(self, auth_client):
        response = auth_client.get(reverse('transfers:create'))
        assert response.status_code == 200

    def test_create_form_has_file_input_and_multipart(self, auth_client):
        response = auth_client.get(reverse('transfers:create'))
        body = response.content.decode()
        assert 'enctype="multipart/form-data"' in body
        assert 'type="file"' in body

    def test_create_transfer_writes_file_and_dispatches(
        self, auth_client, regular_user, make_connection, mocker,
        django_capture_on_commit_callbacks, settings, tmp_path,
    ):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch(
            'apps.transfers.views.current_app.send_task',
            return_value=SimpleNamespace(id='fake-task-id'),
        )
        conn = make_connection(regular_user)
        upload = SimpleUploadedFile('file.tar', b'payload-bytes')
        with django_capture_on_commit_callbacks(execute=True):
            response = auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'destination_path': '/backup/',
                'upload': upload,
            })
        assert response.status_code == 302
        job = TransferJob.objects.get(owner=regular_user)
        assert job.status == STATUS_PENDING
        assert job.source_path == f'{tmp_path}/file.tar'
        assert (tmp_path / 'file.tar').read_bytes() == b'payload-bytes'
        mock_delay.assert_called_once_with(
            'transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': None})

    def test_create_transfer_persists_celery_task_id(
        self, auth_client, regular_user, make_connection, mocker,
        django_capture_on_commit_callbacks, settings, tmp_path,
    ):
        from types import SimpleNamespace
        settings.TRANSFERS_DIR = str(tmp_path)
        mocker.patch(
            'apps.transfers.views.current_app.send_task',
            return_value=SimpleNamespace(id='fake-transfer-task-id'),
        )
        conn = make_connection(regular_user)
        upload = SimpleUploadedFile('file3.tar', b'payload-bytes')
        with django_capture_on_commit_callbacks(execute=True):
            response = auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'destination_path': '/backup/',
                'upload': upload,
            })
        assert response.status_code == 302
        job = TransferJob.objects.get(owner=regular_user)
        assert job.celery_task_id == 'fake-transfer-task-id'

    def test_create_transfer_write_failure_shows_error_no_dispatch(
        self, auth_client, regular_user, make_connection, mocker,
        settings, tmp_path,
    ):
        # TRANSFERS_DIR points inside a directory that does not exist, so open()
        # raises OSError (FileNotFoundError) — the view must re-render with a
        # Polish error, create no job, and never dispatch.
        settings.TRANSFERS_DIR = str(tmp_path / 'missing-dir')
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        upload = SimpleUploadedFile('file.tar', b'payload')
        response = auth_client.post(reverse('transfers:create'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': upload,
        })
        assert response.status_code == 200
        assert 'Nie udało się zapisać pliku' in response.content.decode()
        assert not TransferJob.objects.filter(owner=regular_user).exists()
        mock_delay.assert_not_called()

    def test_create_transfer_overwrites_existing_file(
        self, auth_client, regular_user, make_connection, mocker,
        django_capture_on_commit_callbacks, settings, tmp_path,
    ):
        settings.TRANSFERS_DIR = str(tmp_path)
        (tmp_path / 'file.tar').write_bytes(b'old-content')
        mocker.patch(
            'apps.transfers.views.current_app.send_task',
            return_value=SimpleNamespace(id='fake-task-id'),
        )
        conn = make_connection(regular_user)
        upload = SimpleUploadedFile('file.tar', b'new-content')
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'destination_path': '/backup/',
                'upload': upload,
            })
        assert (tmp_path / 'file.tar').read_bytes() == b'new-content'

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

    def test_log_fragment_includes_oob_progress_bar_with_percent(self, auth_client, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
            progress_percent=42,
        )
        response = auth_client.get(reverse('transfers:log_fragment', args=[job.pk]))
        body = response.content.decode()
        assert 'hx-swap-oob="true"' in body
        assert 'width:42%' in body
        assert '42%</span>' in body

    def test_log_fragment_omits_progress_bar_fill_when_percent_unknown(self, auth_client, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        response = auth_client.get(reverse('transfers:log_fragment', args=[job.pk]))
        body = response.content.decode()
        assert 'progress-bar-fill' not in body


@pytest.mark.django_db
class TestTransferCreateBatchUpload:
    def test_creates_one_job_per_file(
        self, auth_client, regular_user, make_connection, mocker,
        django_capture_on_commit_callbacks, settings, tmp_path,
    ):
        settings.TRANSFERS_DIR = str(tmp_path)
        mocker.patch(
            'apps.transfers.views.current_app.send_task',
            return_value=SimpleNamespace(id='fake-task-id'),
        )
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            response = auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'destination_path': '/backup/',
                'upload': [
                    SimpleUploadedFile('a.tar', b'aaa'),
                    SimpleUploadedFile('b.tar', b'bbb'),
                ],
            })
        assert response.status_code == 302
        jobs = list(TransferJob.objects.filter(owner=regular_user).order_by('source_path'))
        assert len(jobs) == 2
        assert jobs[0].source_path == f'{tmp_path}/a.tar'
        assert jobs[0].destination_path == '/backup/a.tar'
        assert jobs[1].source_path == f'{tmp_path}/b.tar'
        assert jobs[1].destination_path == '/backup/b.tar'
        assert (tmp_path / 'a.tar').read_bytes() == b'aaa'
        assert (tmp_path / 'b.tar').read_bytes() == b'bbb'

    def test_dispatches_one_task_per_job(
        self, auth_client, regular_user, make_connection, mocker,
        django_capture_on_commit_callbacks, settings, tmp_path,
    ):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch(
            'apps.transfers.views.current_app.send_task',
            return_value=SimpleNamespace(id='fake-task-id'),
        )
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'destination_path': '/backup/',
                'upload': [
                    SimpleUploadedFile('a.tar', b'aaa'),
                    SimpleUploadedFile('b.tar', b'bbb'),
                ],
            })
        assert mock_delay.call_count == 2
        job_ids = {c.kwargs['kwargs']['job_id'] for c in mock_delay.call_args_list}
        assert job_ids == set(TransferJob.objects.filter(owner=regular_user).values_list('pk', flat=True))

    def test_redirects_to_logs_with_success_message(
        self, auth_client, regular_user, make_connection, mocker,
        django_capture_on_commit_callbacks, settings, tmp_path,
    ):
        settings.TRANSFERS_DIR = str(tmp_path)
        mocker.patch(
            'apps.transfers.views.current_app.send_task',
            return_value=SimpleNamespace(id='fake-task-id'),
        )
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            response = auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'destination_path': '/backup/',
                'upload': [
                    SimpleUploadedFile('a.tar', b'aaa'),
                    SimpleUploadedFile('b.tar', b'bbb'),
                ],
            }, follow=True)
        assert response.redirect_chain[0][0] == reverse('transfers:logs')
        assert any('2' in str(m) for m in response.context['messages'])

    def test_non_directory_destination_rejected_no_jobs_created(
        self, auth_client, regular_user, make_connection, settings, tmp_path,
    ):
        settings.TRANSFERS_DIR = str(tmp_path)
        conn = make_connection(regular_user)
        response = auth_client.post(reverse('transfers:create'), {
            'connection': conn.pk,
            'destination_path': '/backup/archive.tar',
            'upload': [
                SimpleUploadedFile('a.tar', b'aaa'),
                SimpleUploadedFile('b.tar', b'bbb'),
            ],
        })
        assert response.status_code == 200
        assert not TransferJob.objects.filter(owner=regular_user).exists()

    def test_write_failure_on_second_file_aborts_before_creating_jobs(
        self, auth_client, regular_user, make_connection, mocker, settings, tmp_path,
    ):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        real_open = open

        def _boom_on_second(path, mode):
            if path.endswith('b.tar'):
                raise OSError('disk full')
            return real_open(path, mode)
        mocker.patch('apps.transfers.views.open', side_effect=_boom_on_second)

        response = auth_client.post(reverse('transfers:create'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': [
                SimpleUploadedFile('a.tar', b'aaa'),
                SimpleUploadedFile('b.tar', b'bbb'),
            ],
        })
        assert response.status_code == 200
        assert 'Nie udało się zapisać pliku' in response.content.decode()
        assert not TransferJob.objects.filter(owner=regular_user).exists()
        mock_delay.assert_not_called()


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

    def test_detail_renders_progress_bar_when_percent_known(self, auth_client, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/src/file.tar',
            destination_path='/dst/',
            progress_percent=78,
        )
        response = auth_client.get(reverse('transfers:detail', args=[job.pk]))
        body = response.content.decode()
        assert 'id="progress-bar-wrap"' in body
        assert 'width:78%' in body

    def test_detail_returns_200_for_other_users_job(self, auth_client, admin_user, make_connection):
        job = TransferJob.objects.create(
            owner=admin_user,
            connection=make_connection(admin_user),
            source_path='/src/file.tar',
            destination_path='/dst/',
        )
        response = auth_client.get(reverse('transfers:detail', args=[job.pk]))
        assert response.status_code == 200

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

    def test_logs_shows_jobs_from_all_users(self, auth_client, regular_user, admin_user, make_connection):
        own_job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/own/file.tar',
            destination_path='/dst/',
        )
        other_job = TransferJob.objects.create(
            owner=admin_user,
            connection=make_connection(admin_user),
            source_path='/other/file.tar',
            destination_path='/dst/',
        )
        response = auth_client.get(reverse('transfers:logs'))
        assert response.status_code == 200
        jobs = list(response.context['jobs'])
        assert own_job in jobs
        assert other_job in jobs

    def test_logs_renders_when_no_transfers(self, auth_client):
        response = auth_client.get(reverse('transfers:logs'))
        assert response.status_code == 200

    def test_log_fragment_returns_200_for_other_users_job(self, auth_client, admin_user, make_connection):
        job = TransferJob.objects.create(
            owner=admin_user,
            connection=make_connection(admin_user),
            source_path='/x', destination_path='/y',
        )
        response = auth_client.get(reverse('transfers:log_fragment', args=[job.pk]))
        assert response.status_code == 200


@pytest.mark.django_db
class TestOrgWideVisibility:
    def test_operator_sees_job_created_by_another_user_in_history(self, auth_client, django_user_model, make_connection):
        from apps.transfers.models import TransferJob
        other = django_user_model.objects.create_user(username='tother1', password='p', role='admin')
        conn = make_connection(other)
        TransferJob.objects.create(owner=other, connection=conn, source_path='/a', destination_path='/b')
        resp = auth_client.get('/transfers/logs/')
        assert resp.status_code == 200

    def test_operator_can_view_job_detail_created_by_another_user(self, auth_client, django_user_model, make_connection):
        from apps.transfers.models import TransferJob
        other = django_user_model.objects.create_user(username='tother2', password='p', role='admin')
        conn = make_connection(other)
        job = TransferJob.objects.create(owner=other, connection=conn, source_path='/a', destination_path='/b')
        resp = auth_client.get(f'/transfers/{job.pk}/')
        assert resp.status_code == 200

    def test_transfer_form_offers_connections_from_other_users(self, django_user_model, make_connection):
        from apps.transfers.forms import TransferForm
        owner = django_user_model.objects.create_user(username='tconnowner', password='p')
        conn = make_connection(owner, name='OtherUsersConn2')
        requester = django_user_model.objects.create_user(username='trequester', password='p', role='admin')
        form = TransferForm(user=requester)
        assert conn in form.fields['connection'].queryset


@pytest.mark.django_db
class TestTransferStop:
    def test_operator_can_stop_running_job(self, auth_client, django_user_model, make_connection, monkeypatch):
        from celery import current_app
        from apps.transfers.models import TransferJob, STATUS_RUNNING, STATUS_CANCELLED
        other = django_user_model.objects.create_user(username='sother1', password='p', role='admin')
        conn = make_connection(other)
        job = TransferJob.objects.create(
            owner=other, connection=conn, source_path='/a', destination_path='/b',
            status=STATUS_RUNNING, celery_task_id='abc-123',
        )
        calls = {}
        monkeypatch.setattr(
            current_app.control, 'revoke',
            lambda task_id, **kw: calls.update(task_id=task_id, kw=kw),
        )
        resp = auth_client.post(f'/transfers/{job.pk}/stop/')
        assert resp.status_code == 302
        job.refresh_from_db()
        assert job.status == STATUS_CANCELLED
        assert job.cancelled_by_id is not None
        assert calls['task_id'] == 'abc-123'
        assert calls['kw']['terminate'] is True

    def test_readonly_cannot_stop_job(self, readonly_client, django_user_model, make_connection):
        from apps.transfers.models import TransferJob, STATUS_RUNNING
        other = django_user_model.objects.create_user(username='sother2', password='p', role='admin')
        conn = make_connection(other)
        job = TransferJob.objects.create(
            owner=other, connection=conn, source_path='/a', destination_path='/b',
            status=STATUS_RUNNING, celery_task_id='abc-456',
        )
        resp = readonly_client.post(f'/transfers/{job.pk}/stop/')
        assert resp.status_code == 403

    def test_stop_on_finished_job_is_noop(self, auth_client, django_user_model, make_connection, monkeypatch):
        from celery import current_app
        from apps.transfers.models import TransferJob, STATUS_DONE
        other = django_user_model.objects.create_user(username='sother3', password='p', role='admin')
        conn = make_connection(other)
        job = TransferJob.objects.create(
            owner=other, connection=conn, source_path='/a', destination_path='/b',
            status=STATUS_DONE, celery_task_id='should-not-be-revoked',
        )
        calls = []
        monkeypatch.setattr(current_app.control, 'revoke', lambda *a, **kw: calls.append((a, kw)))
        resp = auth_client.post(f'/transfers/{job.pk}/stop/')
        assert resp.status_code == 302
        job.refresh_from_db()
        assert job.status == STATUS_DONE
        assert calls == []


@pytest.mark.django_db
class TestTransferDelete:
    def test_admin_can_delete_finished_job(self, admin_client, admin_user, make_connection):
        from apps.transfers.models import TransferJob, STATUS_DONE
        conn = make_connection(admin_user)
        job = TransferJob.objects.create(
            owner=admin_user, connection=conn, source_path='/a', destination_path='/b', status=STATUS_DONE,
        )
        resp = admin_client.post(reverse('transfers:delete', args=[job.pk]))
        assert resp.status_code == 302
        assert not TransferJob.objects.filter(pk=job.pk).exists()

    def test_operator_gets_403(self, auth_client, regular_user, make_connection):
        from apps.transfers.models import TransferJob, STATUS_DONE
        conn = make_connection(regular_user)
        job = TransferJob.objects.create(
            owner=regular_user, connection=conn, source_path='/a', destination_path='/b', status=STATUS_DONE,
        )
        resp = auth_client.post(reverse('transfers:delete', args=[job.pk]))
        assert resp.status_code == 403
        assert TransferJob.objects.filter(pk=job.pk).exists()

    def test_cannot_delete_running_job(self, admin_client, admin_user, make_connection):
        from apps.transfers.models import TransferJob, STATUS_RUNNING
        conn = make_connection(admin_user)
        job = TransferJob.objects.create(
            owner=admin_user, connection=conn, source_path='/a', destination_path='/b', status=STATUS_RUNNING,
        )
        resp = admin_client.post(reverse('transfers:delete', args=[job.pk]))
        assert resp.status_code == 302
        assert TransferJob.objects.filter(pk=job.pk).exists()


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


@pytest.mark.django_db
class TestTransferDryRunView:
    def test_dry_run_forbidden_for_readonly(self, readonly_client, regular_user, make_connection):
        conn = make_connection(regular_user, protocol='rsync')
        response = readonly_client.post(reverse('transfers:dry_run'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': SimpleUploadedFile('file.tar', b'payload'),
        })
        assert response.status_code == 403

    def test_dry_run_rejects_non_rsync_connection(self, auth_client, regular_user, make_connection, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        conn = make_connection(regular_user, protocol='sftp')
        response = auth_client.post(reverse('transfers:dry_run'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': SimpleUploadedFile('file.tar', b'payload'),
        })
        assert response.status_code == 200
        assert 'rsync' in response.content.decode().lower()
        assert TransferJob.objects.count() == 0

    def test_dry_run_validates_form_same_as_create(self, auth_client, regular_user, make_connection, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        conn = make_connection(regular_user, protocol='rsync')
        response = auth_client.post(reverse('transfers:dry_run'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            # brak 'upload' — pole wymagane
        })
        assert response.status_code == 200
        assert TransferJob.objects.count() == 0

    def test_dry_run_saves_upload_without_creating_transferjob(self, auth_client, regular_user, make_connection, settings, tmp_path, mocker):
        settings.TRANSFERS_DIR = str(tmp_path)
        mocker.patch(
            'apps.transfers.views.current_app.send_task',
            return_value=SimpleNamespace(id='fake-task-id'),
        )
        conn = make_connection(regular_user, protocol='rsync')
        upload = SimpleUploadedFile('preview.tar', b'payload-bytes')
        response = auth_client.post(reverse('transfers:dry_run'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': upload,
        })
        assert response.status_code == 200
        assert TransferJob.objects.count() == 0
        assert (tmp_path / 'preview.tar').exists()

    def test_dry_run_dispatches_task_and_returns_task_id(self, auth_client, regular_user, make_connection, settings, tmp_path, mocker):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_send = mocker.patch(
            'apps.transfers.views.current_app.send_task',
            return_value=SimpleNamespace(id='fake-task-id'),
        )
        conn = make_connection(regular_user, protocol='rsync')
        upload = SimpleUploadedFile('preview.tar', b'payload-bytes')
        response = auth_client.post(reverse('transfers:dry_run'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': upload,
        })
        assert response.status_code == 200
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == 'transfers.dry_run_preview'
        assert response.context['dry_run_task_id'] == 'fake-task-id'
        # Verify the actual kwargs passed to the task dispatch
        kwargs = mock_send.call_args.kwargs
        assert kwargs['kwargs']['connection_id'] == conn.pk
        assert kwargs['kwargs']['source_path'] == f'{tmp_path}/preview.tar'
        assert kwargs['kwargs']['destination_path'] == '/backup/'
        assert kwargs['kwargs']['gpg_passphrase'] is None


@pytest.mark.django_db
class TestTransferDryRunStatusView:
    def test_status_forbidden_for_readonly(self, readonly_client):
        response = readonly_client.get(reverse('transfers:dry_run_status', args=['fake-id']))
        assert response.status_code == 403

    def test_status_renders_pending(self, auth_client, mocker):
        mock_result = mocker.MagicMock()
        mock_result.state = 'PENDING'
        mocker.patch('apps.transfers.views.AsyncResult', return_value=mock_result)
        response = auth_client.get(reverse('transfers:dry_run_status', args=['fake-id']))
        assert response.status_code == 200
        body = response.content.decode()
        assert 'every' in body  # kontener nadal polluje (hx-trigger)

    def test_status_renders_success_exit_zero(self, auth_client, mocker):
        mock_result = mocker.MagicMock()
        mock_result.state = 'SUCCESS'
        mock_result.result = {'exit_code': 0, 'output': 'sending incremental file list\nfile.tar'}
        mocker.patch('apps.transfers.views.AsyncResult', return_value=mock_result)
        response = auth_client.get(reverse('transfers:dry_run_status', args=['fake-id']))
        assert response.status_code == 200
        body = response.content.decode()
        assert 'file.tar' in body
        assert 'msg-ok' in body

    def test_status_renders_success_nonzero_exit(self, auth_client, mocker):
        mock_result = mocker.MagicMock()
        mock_result.state = 'SUCCESS'
        mock_result.result = {'exit_code': 23, 'output': 'rsync: No such file or directory'}
        mocker.patch('apps.transfers.views.AsyncResult', return_value=mock_result)
        response = auth_client.get(reverse('transfers:dry_run_status', args=['fake-id']))
        assert response.status_code == 200
        body = response.content.decode()
        assert 'No such file' in body
        assert 'msg-error' in body

    def test_status_renders_failure(self, auth_client, mocker):
        mock_result = mocker.MagicMock()
        mock_result.state = 'FAILURE'
        mocker.patch('apps.transfers.views.AsyncResult', return_value=mock_result)
        response = auth_client.get(reverse('transfers:dry_run_status', args=['fake-id']))
        assert response.status_code == 200
        assert 'msg-error' in response.content.decode()
