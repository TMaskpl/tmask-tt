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

    def test_progress_callback_updates_job_and_dedups_repeats(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 1

            def _fake_execute(log_callback, progress_callback=None):
                for pct in (10, 10, 20, 20, 20, 100):
                    progress_callback(pct)
            MockSFTP.return_value.execute.side_effect = _fake_execute

            from tasks import execute_transfer
            execute_transfer(job_id=1)
            assert [c.args[0] for c in mock_job.update_progress.call_args_list] == [10, 20, 100]

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
    def _mock_job(self, MockJob, **owner_attrs):
        mock_job = MagicMock()
        mock_job.owner.webhook_url = 'http://hooks.example.com/'
        mock_job.owner.webhook_circuit_open_until = None
        for k, v in owner_attrs.items():
            setattr(mock_job.owner, k, v)
        MockJob.objects.select_related.return_value.get.return_value = mock_job
        return mock_job

    def test_calls_send_webhook_notification(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.send_webhook_notification') as mock_notif, \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.circuit_is_open', return_value=False):
            mock_job = self._mock_job(MockJob)
            mock_notif.return_value = True
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

    def test_skips_when_no_webhook_url_configured(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.send_webhook_notification') as mock_notif, \
             patch('tasks.WebhookDeliveryLog') as MockLog:
            self._mock_job(MockJob, webhook_url='')
            from tasks import send_webhook
            send_webhook(job_id=42)
            mock_notif.assert_not_called()
            MockLog.objects.create.assert_not_called()

    def test_skips_and_logs_when_circuit_open(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.send_webhook_notification') as mock_notif, \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.circuit_is_open', return_value=True):
            mock_job = self._mock_job(MockJob)
            from tasks import send_webhook
            send_webhook(job_id=42)
            mock_notif.assert_not_called()
            MockLog.objects.create.assert_called_once()
            kwargs = MockLog.objects.create.call_args.kwargs
            assert kwargs['success'] is False
            assert kwargs['skipped'] is True

    def test_records_success_and_logs_delivery_on_success(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.send_webhook_notification', return_value=True), \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.record_success') as mock_record_success, \
             patch('tasks.circuit_is_open', return_value=False):
            mock_job = self._mock_job(MockJob)
            from tasks import send_webhook
            send_webhook(job_id=42)
            mock_record_success.assert_called_once_with(mock_job.owner)
            kwargs = MockLog.objects.create.call_args.kwargs
            assert kwargs['success'] is True

    def test_no_log_entry_when_notification_returns_false(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.send_webhook_notification', return_value=False), \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.record_success') as mock_record_success, \
             patch('tasks.circuit_is_open', return_value=False):
            self._mock_job(MockJob)
            from tasks import send_webhook
            send_webhook(job_id=42)
            MockLog.objects.create.assert_not_called()
            mock_record_success.assert_not_called()

    def test_records_failure_and_logs_delivery_on_exception_then_retries(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.send_webhook_notification', side_effect=ValueError('boom')), \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.record_failure') as mock_record_failure, \
             patch('tasks.circuit_is_open', return_value=False):
            mock_job = self._mock_job(MockJob)
            from tasks import send_webhook
            with pytest.raises(ValueError, match='boom'):
                send_webhook(job_id=42)
            mock_record_failure.assert_called_once_with(mock_job.owner)
            kwargs = MockLog.objects.create.call_args.kwargs
            assert kwargs['success'] is False
            assert 'boom' in kwargs['error_message']


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


class TestExecuteDbTransferPostgresDispatch:
    def test_dispatches_to_postgres_handler_and_marks_done(self):
        with patch('tasks.PgTransferHandler') as MockHandler, \
             patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog') as _, \
             patch('tasks.MaskingRule') as MockMaskingRule:
            MockMaskingRule.objects.filter.return_value.values.return_value = []
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            mock_job.pk = 1
            mock_job.engine = 'postgres'
            mock_job.table_name = ''
            mock_job.source_connection.host = '10.0.0.1'
            mock_job.dest_connection.host = '10.0.0.2'
            MockHandler.return_value.execute.return_value = None
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            MockHandler.assert_called_once()
            MockHandler.return_value.execute.assert_called_once()
            mock_job.mark_done.assert_called_once()

    def test_builds_params_with_correct_source_dest_field_mapping(self):
        with patch('tasks.PgTransferHandler') as MockHandler, \
             patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog') as _, \
             patch('tasks.MaskingRule') as MockMaskingRule:
            MockMaskingRule.objects.filter.return_value.values.return_value = []
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            mock_job.pk = 1
            mock_job.engine = 'postgres'
            mock_job.table_name = 'users'
            mock_job.verify_row_count = True
            mock_job.source_connection.host = 'src-host'
            mock_job.source_connection.port = 5432
            mock_job.source_connection.username = 'src-user'
            mock_job.source_connection.password = 'src-pass'
            mock_job.source_connection.db_name = 'src-db'
            mock_job.dest_connection.host = 'dst-host'
            mock_job.dest_connection.port = 5433
            mock_job.dest_connection.username = 'dst-user'
            mock_job.dest_connection.password = 'dst-pass'
            mock_job.dest_connection.db_name = 'dst-db'
            MockHandler.return_value.execute.return_value = None
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            params = MockHandler.call_args.args[0]
            assert params['source_host'] == 'src-host'
            assert params['source_port'] == 5432
            assert params['source_username'] == 'src-user'
            assert params['source_password'] == 'src-pass'
            assert params['source_db_name'] == 'src-db'
            assert params['dest_host'] == 'dst-host'
            assert params['dest_port'] == 5433
            assert params['dest_username'] == 'dst-user'
            assert params['dest_password'] == 'dst-pass'
            assert params['dest_db_name'] == 'dst-db'
            assert params['table_name'] == 'users'
            assert params['verify_row_count'] is True

    def test_marks_job_failed_on_pg_transfer_error(self):
        with patch('tasks.PgTransferHandler') as MockHandler, \
             patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog') as _, \
             patch('tasks.MaskingRule') as MockMaskingRule:
            MockMaskingRule.objects.filter.return_value.values.return_value = []
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            mock_job.pk = 1
            mock_job.engine = 'postgres'
            mock_job.table_name = ''
            from modules.postgres.handler import PgTransferError
            MockHandler.return_value.execute.side_effect = PgTransferError('AUTH FAILED')
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('AUTH FAILED')

    def test_job_not_found_returns_without_error(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog') as _:
            MockJob.DoesNotExist = Exception
            MockJob.objects.select_related.return_value.get.side_effect = MockJob.DoesNotExist
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=999)  # should not raise


class TestExecuteDbTransferEngineDispatch:
    def _mock_job(self, MockJob, engine):
        mock_job = MagicMock()
        mock_job.engine = engine
        mock_job.pk = 1
        MockJob.objects.select_related.return_value.get.return_value = mock_job
        return mock_job

    def test_dispatches_to_mysql_handler(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog'), \
             patch('tasks.MaskingRule') as MockMaskingRule, \
             patch('tasks.MysqlTransferHandler') as MockMysql:
            MockMaskingRule.objects.filter.return_value.values.return_value = []
            self._mock_job(MockJob, 'mysql')
            MockMysql.return_value.execute.return_value = None
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            MockMysql.assert_called_once()

    def test_dispatches_to_mssql_handler(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog'), \
             patch('tasks.MaskingRule') as MockMaskingRule, \
             patch('tasks.MssqlTransferHandler') as MockMssql:
            MockMaskingRule.objects.filter.return_value.values.return_value = []
            self._mock_job(MockJob, 'mssql')
            MockMssql.return_value.execute.return_value = None
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            MockMssql.assert_called_once()

    def test_dispatches_to_postgres_handler_unchanged(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog'), \
             patch('tasks.MaskingRule') as MockMaskingRule, \
             patch('tasks.PgTransferHandler') as MockPg:
            MockMaskingRule.objects.filter.return_value.values.return_value = []
            self._mock_job(MockJob, 'postgres')
            MockPg.return_value.execute.return_value = None
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            MockPg.assert_called_once()

    def test_mysql_error_marks_job_failed(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog'), \
             patch('tasks.MaskingRule') as MockMaskingRule, \
             patch('tasks.MysqlTransferHandler') as MockMysql:
            MockMaskingRule.objects.filter.return_value.values.return_value = []
            from modules.mysql.handler import MysqlTransferError
            mock_job = self._mock_job(MockJob, 'mysql')
            MockMysql.return_value.execute.side_effect = MysqlTransferError('AUTH FAILED')
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('AUTH FAILED')

    def test_mssql_error_marks_job_failed(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog'), \
             patch('tasks.MaskingRule') as MockMaskingRule, \
             patch('tasks.MssqlTransferHandler') as MockMssql:
            MockMaskingRule.objects.filter.return_value.values.return_value = []
            from modules.mssql.handler import MssqlTransferError
            mock_job = self._mock_job(MockJob, 'mssql')
            MockMssql.return_value.execute.side_effect = MssqlTransferError('CONN FAILED')
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('CONN FAILED')


class TestMaskingRulesFor:
    @patch('tasks.MaskingRule')
    def test_returns_empty_dict_when_no_rules(self, MockMaskingRule):
        MockMaskingRule.objects.filter.return_value.values.return_value = []
        mock_connection = MagicMock()
        from tasks import _masking_rules_for
        assert _masking_rules_for(mock_connection) == {}
        MockMaskingRule.objects.filter.assert_called_once_with(connection=mock_connection)

    @patch('tasks.MaskingRule')
    def test_groups_rules_by_table_and_column_across_whole_connection(self, MockMaskingRule):
        MockMaskingRule.objects.filter.return_value.values.return_value = [
            {'table_name': 'users', 'column_name': 'email', 'faker_provider': 'email'},
            {'table_name': 'clients', 'column_name': 'name', 'faker_provider': 'name'},
        ]
        mock_connection = MagicMock()
        from tasks import _masking_rules_for
        assert _masking_rules_for(mock_connection) == {
            'users': {'email': 'email'}, 'clients': {'name': 'name'},
        }


class TestHealthCheckAllTask:
    def test_dispatches_one_child_task_per_connection(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.health_check_one') as mock_health_check_one:
            MockConnection.objects.values_list.return_value = [1, 2, 3]
            from tasks import health_check_all
            health_check_all()
            assert mock_health_check_one.delay.call_count == 3
            mock_health_check_one.delay.assert_any_call(1)
            mock_health_check_one.delay.assert_any_call(2)
            mock_health_check_one.delay.assert_any_call(3)

    def test_no_connections_dispatches_nothing(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.health_check_one') as mock_health_check_one:
            MockConnection.objects.values_list.return_value = []
            from tasks import health_check_all
            health_check_all()
            mock_health_check_one.delay.assert_not_called()


class TestHealthCheckOneTask:
    def _mock_connection(self, MockConnection, kind='ssh', old_status='unknown'):
        mock_conn = MagicMock()
        mock_conn.pk = 5
        mock_conn.kind = kind
        mock_conn.health_status = old_status
        MockConnection.objects.select_related.return_value.get.return_value = mock_conn
        return mock_conn

    def test_logs_and_skips_when_connection_not_found(self):
        with patch('tasks.Connection') as MockConnection:
            MockConnection.objects.select_related.return_value.get.side_effect = Exception('not found')
            from tasks import health_check_one
            health_check_one(999)  # should not raise

    def test_dispatches_to_ssh_tester_for_ssh_kind(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='ssh')
            mock_ssh_test.return_value.success = True
            mock_ssh_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_ssh_test.assert_called_once_with(mock_conn)

    def test_dispatches_to_pg_tester_for_postgres_kind(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.pg_test_connection') as mock_pg_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='postgres')
            mock_pg_test.return_value.success = True
            mock_pg_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_pg_test.assert_called_once_with(mock_conn)

    def test_dispatches_to_mysql_tester_for_mysql_kind(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.mysql_test_connection') as mock_mysql_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='mysql')
            mock_mysql_test.return_value.success = True
            mock_mysql_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_mysql_test.assert_called_once_with(mock_conn)

    def test_dispatches_to_mssql_tester_for_mssql_kind(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.mssql_test_connection') as mock_mssql_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='mssql')
            mock_mssql_test.return_value.success = True
            mock_mssql_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_mssql_test.assert_called_once_with(mock_conn)

    def test_saves_ok_status_and_clears_error(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='ssh', old_status='failed')
            mock_ssh_test.return_value.success = True
            mock_ssh_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            assert mock_conn.health_status == 'ok'
            assert mock_conn.health_error == ''
            mock_conn.save.assert_called_once()

    def test_saves_failed_status_and_error_message(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='ssh', old_status='unknown')
            mock_ssh_test.return_value.success = False
            mock_ssh_test.return_value.message = 'CONNECTION FAILED — timeout'
            from tasks import health_check_one
            health_check_one(5)
            assert mock_conn.health_status == 'failed'
            assert mock_conn.health_error == 'CONNECTION FAILED — timeout'

    def test_notifies_on_first_failure(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification') as mock_notify:
            self._mock_connection(MockConnection, kind='ssh', old_status='unknown')
            mock_ssh_test.return_value.success = False
            mock_ssh_test.return_value.message = 'CONNECTION FAILED — timeout'
            from tasks import health_check_one
            health_check_one(5)
            mock_notify.delay.assert_called_once_with(5, 'failed')

    def test_no_notification_on_first_ok(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification') as mock_notify:
            self._mock_connection(MockConnection, kind='ssh', old_status='unknown')
            mock_ssh_test.return_value.success = True
            mock_ssh_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_notify.delay.assert_not_called()

    def test_no_notification_when_still_failed(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification') as mock_notify:
            self._mock_connection(MockConnection, kind='ssh', old_status='failed')
            mock_ssh_test.return_value.success = False
            mock_ssh_test.return_value.message = 'CONNECTION FAILED — timeout'
            from tasks import health_check_one
            health_check_one(5)
            mock_notify.delay.assert_not_called()

    def test_notifies_on_recovery(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification') as mock_notify:
            self._mock_connection(MockConnection, kind='ssh', old_status='failed')
            mock_ssh_test.return_value.success = True
            mock_ssh_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_notify.delay.assert_called_once_with(5, 'ok')

    def test_no_notification_when_still_ok(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification') as mock_notify:
            self._mock_connection(MockConnection, kind='ssh', old_status='ok')
            mock_ssh_test.return_value.success = True
            mock_ssh_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_notify.delay.assert_not_called()


class TestSendHealthNotificationTask:
    def _mock_connection(self, MockConnection, webhook_url='http://hooks.example.com/'):
        mock_conn = MagicMock()
        mock_conn.pk = 5
        mock_conn.owner.webhook_url = webhook_url
        mock_conn.owner.webhook_circuit_open_until = None
        MockConnection.objects.select_related.return_value.get.return_value = mock_conn
        return mock_conn

    def test_logs_and_skips_when_connection_not_found(self):
        with patch('tasks.Connection') as MockConnection:
            MockConnection.objects.select_related.return_value.get.side_effect = Exception('not found')
            from tasks import send_health_notification
            send_health_notification(999, 'failed')  # should not raise

    def test_calls_email_and_telegram(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.send_connection_health_email') as mock_email, \
             patch('tasks.send_connection_health_telegram') as mock_telegram, \
             patch('tasks.send_connection_health_webhook'), \
             patch('tasks.WebhookDeliveryLog'), \
             patch('tasks.circuit_is_open', return_value=False), \
             patch('tasks.record_success'):
            mock_conn = self._mock_connection(MockConnection)
            from tasks import send_health_notification
            send_health_notification(5, 'failed')
            mock_email.assert_called_once_with(mock_conn, 'failed')
            mock_telegram.assert_called_once_with(mock_conn, 'failed')

    def test_skips_webhook_when_no_url_configured(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.send_connection_health_email'), \
             patch('tasks.send_connection_health_telegram'), \
             patch('tasks.send_connection_health_webhook') as mock_webhook, \
             patch('tasks.WebhookDeliveryLog') as MockLog:
            self._mock_connection(MockConnection, webhook_url='')
            from tasks import send_health_notification
            send_health_notification(5, 'failed')
            mock_webhook.assert_not_called()
            MockLog.objects.create.assert_not_called()

    def test_skips_and_logs_when_circuit_open(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.send_connection_health_email'), \
             patch('tasks.send_connection_health_telegram'), \
             patch('tasks.send_connection_health_webhook') as mock_webhook, \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.circuit_is_open', return_value=True):
            self._mock_connection(MockConnection)
            from tasks import send_health_notification
            send_health_notification(5, 'failed')
            mock_webhook.assert_not_called()
            MockLog.objects.create.assert_called_once()
            assert MockLog.objects.create.call_args[1]['skipped'] is True

    def test_records_success_and_logs_delivery_on_success(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.send_connection_health_email'), \
             patch('tasks.send_connection_health_telegram'), \
             patch('tasks.send_connection_health_webhook', return_value=True), \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.circuit_is_open', return_value=False), \
             patch('tasks.record_success') as mock_record_success:
            mock_conn = self._mock_connection(MockConnection)
            from tasks import send_health_notification
            send_health_notification(5, 'ok')
            mock_record_success.assert_called_once()
            MockLog.objects.create.assert_called_once_with(
                user=mock_conn.owner, job=None, url='http://hooks.example.com/', success=True,
            )

    def test_records_failure_and_logs_delivery_on_exception(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.send_connection_health_email'), \
             patch('tasks.send_connection_health_telegram'), \
             patch('tasks.send_connection_health_webhook', side_effect=Exception('boom')), \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.circuit_is_open', return_value=False), \
             patch('tasks.record_failure') as mock_record_failure:
            mock_conn = self._mock_connection(MockConnection)
            from tasks import send_health_notification
            send_health_notification(5, 'failed')  # should not raise
            mock_record_failure.assert_called_once_with(mock_conn.owner)
