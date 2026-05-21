import pytest
from unittest.mock import patch, MagicMock


class TestExecuteTransferTask:
    def test_dispatches_to_sftp_module(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.connection.protocol = 'sftp'
            mock_sftp_instance = MagicMock()
            MockSFTP.return_value = mock_sftp_instance
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            MockSFTP.assert_called_once()
            mock_sftp_instance.execute.assert_called_once()
            mock_job.mark_done.assert_called_once()

    def test_marks_job_failed_on_sftp_error(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.connection.protocol = 'sftp'
            from modules.sftp.handler import SFTPTransferError
            MockSFTP.return_value.execute.side_effect = SFTPTransferError('AUTH FAILED')
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('AUTH FAILED')

    def test_dispatches_to_rsync_module(self):
        with patch('tasks.RsyncHandler') as MockRsync, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.connection.protocol = 'rsync'
            mock_rsync_instance = MagicMock()
            MockRsync.return_value = mock_rsync_instance
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            MockRsync.assert_called_once()
            mock_rsync_instance.execute.assert_called_once()

    def test_unexpected_exception_marks_failed_and_reraises(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.connection.protocol = 'sftp'
            MockSFTP.return_value.execute.side_effect = RuntimeError('disk full')
            from tasks import execute_transfer
            with pytest.raises(RuntimeError):
                execute_transfer(job_id=1)
            assert 'UNEXPECTED ERROR' in mock_job.mark_failed.call_args[0][0]


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
