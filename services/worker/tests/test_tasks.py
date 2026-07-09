import os
import time

import pytest
from unittest.mock import patch, MagicMock


class TestExecuteTransferTask:
    def test_dispatches_to_sftp_module(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 1
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            MockSFTP.assert_called_once()
            MockSFTP.return_value.execute.assert_called_once()
            mock_job.mark_done.assert_called_once()

    def test_marks_job_failed_on_sftp_error(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 1
            from modules.sftp.handler import SFTPTransferError
            MockSFTP.return_value.execute.side_effect = SFTPTransferError('AUTH FAILED')
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('AUTH FAILED')

    def test_dispatches_to_rsync_module(self):
        with patch('tasks.RsyncHandler') as MockRsync, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'rsync'
            mock_job.pk = 1
            MockRsync.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            MockRsync.assert_called_once()
            MockRsync.return_value.execute.assert_called_once()

    def test_unexpected_exception_marks_failed_and_reraises(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 1
            MockSFTP.return_value.execute.side_effect = RuntimeError('disk full')
            from tasks import execute_transfer
            with pytest.raises(RuntimeError):
                execute_transfer(job_id=1)
            assert 'UNEXPECTED ERROR' in mock_job.mark_failed.call_args[0][0]

    def test_dispatches_relay_handler_when_flow_set(self):
        with patch('tasks.RelayHandler') as MockRelay, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = 99
            mock_job.pk = 1
            MockRelay.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            MockRelay.assert_called_once()
            MockRelay.return_value.execute.assert_called_once()
            mock_job.mark_done.assert_called_once()

    def test_relay_error_marks_job_failed(self):
        with patch('tasks.RelayHandler') as MockRelay, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = 99
            mock_job.pk = 1
            from modules.relay.handler import RelayTransferError
            MockRelay.return_value.execute.side_effect = RelayTransferError('SOURCE ERROR — AUTH FAILED')
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('SOURCE ERROR — AUTH FAILED')

    def test_scheduled_id_creates_job_and_executes(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as _, \
             patch('tasks.TransferLog') as __, \
             patch('tasks._create_job_from_schedule') as MockCreate:
            mock_job = MagicMock()
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 1
            MockCreate.return_value = mock_job
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=None, scheduled_id=5)
            MockCreate.assert_called_once_with(5)
            mock_job.mark_done.assert_called_once()

    def test_scheduled_id_skips_when_schedule_not_found(self):
        with patch('tasks._create_job_from_schedule') as MockCreate, \
             patch('tasks.TransferJob') as MockJob:
            MockCreate.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=None, scheduled_id=999)
            MockJob.objects.get.assert_not_called()

    def test_scheduled_transfer_logs_warn_when_encrypt_true_but_no_passphrase(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as _, \
             patch('tasks.TransferLog') as MockLog, \
             patch('tasks._create_job_from_schedule') as MockCreate, \
             patch('tasks.send_notification'), \
             patch('tasks.send_webhook'), \
             patch('tasks.send_telegram'):
            mock_job = MagicMock()
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.connection.encrypt = True
            mock_job.pk = 1
            MockCreate.return_value = mock_job
            MockSFTP.return_value.execute.return_value = None

            logged = []
            MockLog.objects.create.side_effect = lambda **kw: logged.append((kw['level'], kw['message']))

            from tasks import execute_transfer
            execute_transfer(job_id=None, scheduled_id=5)

            warn_messages = [msg for lvl, msg in logged if lvl == 'warn']
            assert any('GPG' in msg for msg in warn_messages)

            # gpg_passphrase=None w params przekazanych do handlera
            handler_params = MockSFTP.call_args[0][0]
            assert handler_params.get('gpg_passphrase') is None


class TestSendNotificationTask:
    def test_calls_send_email_notification(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.send_email_notification') as mock_notif:
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            from tasks import send_notification
            send_notification(job_id=42)
            mock_notif.assert_called_once_with(mock_job)

    def test_logs_and_skips_when_job_not_found(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.logger') as mock_logger:
            MockJob.objects.select_related.return_value.get.side_effect = Exception('not found')
            from tasks import send_notification
            send_notification(job_id=999)
            mock_logger.error.assert_called()


class TestExecuteTransferDispatchesNotification:
    def test_dispatches_notification_on_done(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'), \
             patch('tasks.send_notification') as mock_notif:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 99
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=99)
            mock_notif.delay.assert_called_once_with(99)

    def test_dispatches_notification_on_failed(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'), \
             patch('tasks.send_notification') as mock_notif:
            from modules.sftp.handler import SFTPTransferError
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 99
            MockSFTP.return_value.execute.side_effect = SFTPTransferError('TIMEOUT')
            from tasks import execute_transfer
            execute_transfer(job_id=99)
            mock_notif.delay.assert_called_once_with(99)


class TestCleanupOrphanJobs:
    def test_marks_old_running_jobs_as_failed(self):
        with patch('tasks.TransferJob') as MockJob:
            mock_qs = MagicMock()
            mock_qs.count.return_value = 2
            MockJob.objects.filter.return_value = mock_qs
            from tasks import cleanup_orphan_jobs
            cleanup_orphan_jobs()
            mock_qs.update.assert_called_once()
            call_kwargs = mock_qs.update.call_args[1]
            assert call_kwargs.get('status') == 'failed'
            assert 'TASK INTERRUPTED' in call_kwargs.get('error_message', '')


class TestSendWebhookTask:
    def test_calls_send_webhook_notification(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.send_webhook_notification') as mock_notif:
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            from tasks import send_webhook
            send_webhook(job_id=42)
            mock_notif.assert_called_once_with(mock_job)

    def test_logs_and_skips_when_job_not_found(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.logger') as mock_logger:
            MockJob.objects.select_related.return_value.get.side_effect = Exception('not found')
            from tasks import send_webhook
            send_webhook(job_id=999)
            mock_logger.error.assert_called()


class TestExecuteTransferDispatchesWebhook:
    def test_dispatches_webhook_on_done(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'), \
             patch('tasks.send_notification'), \
             patch('tasks.send_webhook') as mock_webhook:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 99
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=99)
            mock_webhook.delay.assert_called_once_with(99)

    def test_dispatches_webhook_on_failed(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'), \
             patch('tasks.send_notification'), \
             patch('tasks.send_webhook') as mock_webhook:
            from modules.sftp.handler import SFTPTransferError
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 99
            MockSFTP.return_value.execute.side_effect = SFTPTransferError('TIMEOUT')
            from tasks import execute_transfer
            execute_transfer(job_id=99)
            mock_webhook.delay.assert_called_once_with(99)

    def test_dispatches_webhook_on_unexpected_exception(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'), \
             patch('tasks.send_notification'), \
             patch('tasks.send_webhook') as mock_webhook:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 99
            MockSFTP.return_value.execute.side_effect = RuntimeError('unexpected')
            from tasks import execute_transfer
            with pytest.raises(RuntimeError):
                execute_transfer(job_id=99)
            mock_webhook.delay.assert_called_once_with(99)


class TestBuildRelayParamsVerifyChecksum:
    def test_verify_checksum_passed_to_source_params(self):
        from unittest.mock import MagicMock
        from tasks import _build_relay_params
        flow = MagicMock()
        flow.verify_checksum = True
        flow.source_path = '/src/a'
        flow.dest_path = '/dst/b'
        for conn in (flow.source_conn, flow.dest_conn):
            conn.port = 22
            conn.strict_host_key_checking = False
            conn.known_host_key = ''
        source_params, dest_params = _build_relay_params(flow)
        assert source_params['verify_checksum'] is True


class TestCleanupSourceFileOnSuccess:
    def test_deletes_source_file_after_success_when_connection_job(self, tmp_path):
        source = tmp_path / "upload.txt"
        source.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection_id = 5
            mock_job.connection.protocol = 'sftp'
            mock_job.source_path = str(source)
            mock_job.pk = 1
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            assert not source.exists()

    def test_does_not_delete_when_flow_job(self, tmp_path):
        source = tmp_path / "upload.txt"
        source.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.RelayHandler') as MockRelay, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = 99
            mock_job.connection_id = None
            mock_job.source_path = str(source)
            mock_job.pk = 1
            MockRelay.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            assert source.exists()

    def test_does_not_delete_path_outside_transfers_dir(self, tmp_path):
        transfers_dir = tmp_path / "transfers"
        transfers_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        source = outside_dir / "upload.txt"
        source.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(transfers_dir)), \
             patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection_id = 5
            mock_job.connection.protocol = 'sftp'
            mock_job.source_path = str(source)
            mock_job.pk = 1
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            assert source.exists()

    def test_does_not_delete_when_path_shares_string_prefix_but_not_subdirectory(self, tmp_path):
        transfers_dir = tmp_path / "transfers"
        transfers_dir.mkdir()
        colliding_dir = tmp_path / "transfers-evil"
        colliding_dir.mkdir()
        source = colliding_dir / "upload.txt"
        source.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(transfers_dir)), \
             patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection_id = 5
            mock_job.connection.protocol = 'sftp'
            mock_job.source_path = str(source)
            mock_job.pk = 1
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            assert source.exists()

    def test_success_survives_missing_file(self, tmp_path):
        missing = tmp_path / "gone.txt"
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection_id = 5
            mock_job.connection.protocol = 'sftp'
            mock_job.source_path = str(missing)
            mock_job.pk = 1
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            mock_job.mark_done.assert_called_once()

    def test_does_not_delete_on_failed_transfer(self, tmp_path):
        source = tmp_path / "upload.txt"
        source.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            from modules.sftp.handler import SFTPTransferError
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection_id = 5
            mock_job.connection.protocol = 'sftp'
            mock_job.source_path = str(source)
            mock_job.pk = 1
            MockSFTP.return_value.execute.side_effect = SFTPTransferError('AUTH FAILED')
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            assert source.exists()


class TestCleanupOldTransfers:
    def test_removes_files_older_than_threshold(self, tmp_path):
        old_file = tmp_path / "old.txt"
        old_file.write_text("dummy")
        old_time = time.time() - 2 * 86400
        os.utime(old_file, (old_time, old_time))
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.settings.TRANSFERS_RETENTION_DAYS', 1):
            from tasks import cleanup_old_transfers
            cleanup_old_transfers()
            assert not old_file.exists()

    def test_keeps_files_newer_than_threshold(self, tmp_path):
        new_file = tmp_path / "new.txt"
        new_file.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.settings.TRANSFERS_RETENTION_DAYS', 1):
            from tasks import cleanup_old_transfers
            cleanup_old_transfers()
            assert new_file.exists()

    def test_empty_directory_no_error(self, tmp_path):
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.settings.TRANSFERS_RETENTION_DAYS', 1):
            from tasks import cleanup_old_transfers
            cleanup_old_transfers()

    def test_single_file_error_does_not_abort_loop(self, tmp_path):
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("dummy")
        file_b.write_text("dummy")
        old_time = time.time() - 2 * 86400
        os.utime(file_a, (old_time, old_time))
        os.utime(file_b, (old_time, old_time))
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.settings.TRANSFERS_RETENTION_DAYS', 1), \
             patch('tasks.os.unlink') as mock_unlink:
            mock_unlink.side_effect = [OSError('permission denied'), None]
            from tasks import cleanup_old_transfers
            cleanup_old_transfers()
            assert mock_unlink.call_count == 2

    def test_skips_subdirectories_without_error(self, tmp_path):
        subdir = tmp_path / "some_subdir"
        subdir.mkdir()
        old_time = time.time() - 2 * 86400
        os.utime(subdir, (old_time, old_time))
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.settings.TRANSFERS_RETENTION_DAYS', 1):
            from tasks import cleanup_old_transfers
            cleanup_old_transfers()
            assert subdir.exists()

    def test_missing_transfers_dir_does_not_raise(self, tmp_path):
        missing_dir = tmp_path / "does-not-exist"
        with patch('tasks.settings.TRANSFERS_DIR', str(missing_dir)), \
             patch('tasks.settings.TRANSFERS_RETENTION_DAYS', 1):
            from tasks import cleanup_old_transfers
            cleanup_old_transfers()


class TestDryRunPreviewTask:
    def test_builds_params_from_connection_and_delegates_to_preview(self):
        with patch('tasks.Connection') as MockConn, \
             patch('tasks.RsyncHandler') as MockRsync:
            mock_conn = MagicMock()
            mock_conn.host = '10.0.0.5'
            mock_conn.port = 22
            mock_conn.username = 'deploy'
            mock_conn.password = None
            mock_conn.ssh_key = 'key-data'
            mock_conn.compress = True
            mock_conn.encrypt = False
            mock_conn.strict_host_key_checking = True
            mock_conn.known_host_key = 'known-host-entry'
            MockConn.objects.get.return_value = mock_conn
            MockRsync.return_value.preview.return_value = {'exit_code': 0, 'output': 'ok'}

            from tasks import dry_run_preview
            result = dry_run_preview(connection_id=1, source_path='/transfers/f.tar', destination_path='/backup/')

            assert result == {'exit_code': 0, 'output': 'ok'}
            params = MockRsync.call_args[0][0]
            assert params['host'] == '10.0.0.5'
            assert params['source_path'] == '/transfers/f.tar'
            assert params['destination_path'] == '/backup/'
            assert params['compress'] is True

    def test_returns_error_dict_when_connection_not_found(self):
        with patch('tasks.Connection') as MockConn:
            MockConn.DoesNotExist = Exception
            MockConn.objects.get.side_effect = MockConn.DoesNotExist
            from tasks import dry_run_preview
            result = dry_run_preview(connection_id=999, source_path='/transfers/f.tar', destination_path='/backup/')
            assert result['exit_code'] is None
            assert 'nie istnieje' in result['output']

    def test_passes_gpg_passphrase_to_params(self):
        with patch('tasks.Connection') as MockConn, \
             patch('tasks.RsyncHandler') as MockRsync:
            mock_conn = MagicMock()
            mock_conn.encrypt = True
            MockConn.objects.get.return_value = mock_conn
            MockRsync.return_value.preview.return_value = {'exit_code': 0, 'output': 'ok'}

            from tasks import dry_run_preview
            dry_run_preview(
                connection_id=1, source_path='/transfers/f.tar',
                destination_path='/backup/', gpg_passphrase='secret123',
            )

            params = MockRsync.call_args[0][0]
            assert params['gpg_passphrase'] == 'secret123'
            assert params['encrypt'] is True

    def test_delegates_to_rsync_handler_preview_not_execute(self):
        with patch('tasks.Connection') as MockConn, \
             patch('tasks.RsyncHandler') as MockRsync:
            MockConn.objects.get.return_value = MagicMock()
            MockRsync.return_value.preview.return_value = {'exit_code': 0, 'output': 'ok'}

            from tasks import dry_run_preview
            dry_run_preview(connection_id=1, source_path='/a', destination_path='/b')

            MockRsync.return_value.preview.assert_called_once()
            MockRsync.return_value.execute.assert_not_called()


class TestExecutePgTransferTask:
    def test_dispatches_to_postgres_handler_and_marks_done(self):
        with patch('tasks.PgTransferHandler') as MockHandler, \
             patch('tasks.PgTransferJob') as MockJob, \
             patch('tasks.PgTransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            mock_job.pk = 1
            mock_job.table_name = ''
            mock_job.source_connection.host = '10.0.0.1'
            mock_job.dest_connection.host = '10.0.0.2'
            MockHandler.return_value.execute.return_value = None
            from tasks import execute_pg_transfer
            execute_pg_transfer(job_id=1)
            MockHandler.assert_called_once()
            MockHandler.return_value.execute.assert_called_once()
            mock_job.mark_done.assert_called_once()

    def test_marks_job_failed_on_pg_transfer_error(self):
        with patch('tasks.PgTransferHandler') as MockHandler, \
             patch('tasks.PgTransferJob') as MockJob, \
             patch('tasks.PgTransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            mock_job.pk = 1
            mock_job.table_name = ''
            from modules.postgres.handler import PgTransferError
            MockHandler.return_value.execute.side_effect = PgTransferError('AUTH FAILED')
            from tasks import execute_pg_transfer
            execute_pg_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('AUTH FAILED')

    def test_job_not_found_returns_without_error(self):
        with patch('tasks.PgTransferJob') as MockJob, \
             patch('tasks.PgTransferLog') as _:
            MockJob.DoesNotExist = Exception
            MockJob.objects.select_related.return_value.get.side_effect = MockJob.DoesNotExist
            from tasks import execute_pg_transfer
            execute_pg_transfer(job_id=999)  # should not raise
