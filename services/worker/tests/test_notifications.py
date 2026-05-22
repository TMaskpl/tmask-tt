import pytest
from unittest.mock import patch, MagicMock


class TestSendEmailNotification:
    def _make_job(self, status, email='', notify_on_done=False, notify_on_failed=True, error_message=None):
        job = MagicMock()
        job.pk = 42
        job.status = status
        job.source_path = '/data/file.tar'
        job.destination_path = '/backup/file.tar'
        job.error_message = error_message or ''
        job.started_at = None
        job.finished_at = None
        job.connection = MagicMock()
        job.connection.name = 'TestSrv'
        job.connection.protocol = 'sftp'
        job.flow = None
        job.owner = MagicMock()
        job.owner.email = email
        job.owner.notify_on_done = notify_on_done
        job.owner.notify_on_failed = notify_on_failed
        return job

    def test_skips_if_no_email(self):
        from notifications import send_email_notification
        job = self._make_job('failed', email='')
        with patch('notifications.send_mail') as mock_mail:
            result = send_email_notification(job)
        assert result is False
        mock_mail.assert_not_called()

    def test_skips_done_if_notify_on_done_false(self):
        from notifications import send_email_notification
        job = self._make_job('done', email='u@example.com', notify_on_done=False)
        with patch('notifications.send_mail') as mock_mail:
            result = send_email_notification(job)
        assert result is False
        mock_mail.assert_not_called()

    def test_skips_failed_if_notify_on_failed_false(self):
        from notifications import send_email_notification
        job = self._make_job('failed', email='u@example.com', notify_on_failed=False)
        with patch('notifications.send_mail') as mock_mail:
            result = send_email_notification(job)
        assert result is False
        mock_mail.assert_not_called()

    def test_sends_email_on_done_when_enabled(self):
        from notifications import send_email_notification
        job = self._make_job('done', email='u@example.com', notify_on_done=True)
        with patch('notifications.send_mail') as mock_mail, \
             patch('notifications._render_notification', return_value=('subj', 'plain', '<html>')):
            result = send_email_notification(job)
        assert result is True
        mock_mail.assert_called_once()
        call_kwargs = mock_mail.call_args
        assert 'u@example.com' in call_kwargs[0][3]

    def test_sends_email_on_failed_when_enabled(self):
        from notifications import send_email_notification
        job = self._make_job('failed', email='u@example.com', notify_on_failed=True)
        with patch('notifications.send_mail') as mock_mail, \
             patch('notifications._render_notification', return_value=('subj', 'plain', '<html>')):
            result = send_email_notification(job)
        assert result is True
        mock_mail.assert_called_once()

    def test_render_notification_done_subject(self):
        from notifications import _render_notification
        job = self._make_job('done', email='u@example.com')
        with patch('notifications.render_to_string', return_value='rendered'):
            subject, plain, html = _render_notification(job)
        assert 'DONE' in subject
        assert '42' in subject

    def test_render_notification_failed_subject(self):
        from notifications import _render_notification
        job = self._make_job('failed', email='u@example.com')
        with patch('notifications.render_to_string', return_value='rendered'):
            subject, plain, html = _render_notification(job)
        assert 'FAILED' in subject
        assert '42' in subject
