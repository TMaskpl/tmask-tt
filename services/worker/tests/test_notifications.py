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


class TestSendWebhookNotification:
    def _make_job(self, status, webhook_url='', webhook_on_done=False,
                  webhook_on_failed=True, error_message=None, use_flow=False):
        job = MagicMock()
        job.pk = 42
        job.status = status
        job.source_path = '/data/file.tar'
        job.destination_path = '/backup/file.tar'
        job.error_message = error_message or ''
        job.started_at = None
        job.finished_at = None
        if use_flow:
            job.connection = None
            job.flow = MagicMock()
            job.flow.name = 'MyFlow'
        else:
            job.connection = MagicMock()
            job.connection.name = 'TestSrv'
            job.connection.protocol = 'sftp'
            job.flow = None
        job.owner = MagicMock()
        job.owner.webhook_url = webhook_url
        job.owner.webhook_on_done = webhook_on_done
        job.owner.webhook_on_failed = webhook_on_failed
        return job

    def test_skips_if_no_url(self):
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='')
        with patch('notifications.requests.post') as mock_post:
            result = send_webhook_notification(job)
        assert result is False
        mock_post.assert_not_called()

    def test_skips_done_if_webhook_on_done_false(self):
        from notifications import send_webhook_notification
        job = self._make_job('done', webhook_url='http://hooks.example.com/',
                             webhook_on_done=False)
        with patch('notifications.requests.post') as mock_post:
            result = send_webhook_notification(job)
        assert result is False
        mock_post.assert_not_called()

    def test_skips_failed_if_webhook_on_failed_false(self):
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://hooks.example.com/',
                             webhook_on_failed=False)
        with patch('notifications.requests.post') as mock_post:
            result = send_webhook_notification(job)
        assert result is False
        mock_post.assert_not_called()

    def test_sends_on_done_when_enabled(self):
        from notifications import send_webhook_notification
        job = self._make_job('done', webhook_url='http://hooks.example.com/',
                             webhook_on_done=True)
        mock_resp = MagicMock()
        with patch('notifications.requests.post', return_value=mock_resp) as mock_post:
            result = send_webhook_notification(job)
        assert result is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == 'http://hooks.example.com/'
        assert kwargs['timeout'] == 10
        mock_resp.raise_for_status.assert_called_once()

    def test_sends_on_failed_when_enabled(self):
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://hooks.example.com/',
                             webhook_on_failed=True)
        mock_resp = MagicMock()
        with patch('notifications.requests.post', return_value=mock_resp) as mock_post:
            result = send_webhook_notification(job)
        assert result is True
        mock_post.assert_called_once()
        mock_resp.raise_for_status.assert_called_once()

    def test_raises_on_non_2xx(self):
        import requests as req
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://hooks.example.com/',
                             webhook_on_failed=True)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError('403')
        with patch('notifications.requests.post', return_value=mock_resp):
            with pytest.raises(req.HTTPError):
                send_webhook_notification(job)

    def test_raises_on_timeout(self):
        import requests as req
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://hooks.example.com/',
                             webhook_on_failed=True)
        with patch('notifications.requests.post', side_effect=req.Timeout('timeout')):
            with pytest.raises(req.Timeout):
                send_webhook_notification(job)

    def test_payload_contains_expected_fields(self):
        from notifications import send_webhook_notification
        job = self._make_job('done', webhook_url='http://hooks.example.com/',
                             webhook_on_done=True)
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured['payload'] = json
            return MagicMock()

        with patch('notifications.requests.post', side_effect=capture_post):
            send_webhook_notification(job)

        p = captured['payload']
        assert p['job_id'] == 42
        assert p['status'] == 'done'
        assert p['source_path'] == '/data/file.tar'
        assert p['destination_path'] == '/backup/file.tar'
        assert 'TestSrv' in p['connection']
        assert 'SFTP' in p['connection']
        assert p['error'] is None

    def test_skips_if_private_ip_url(self):
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://192.168.1.1/hook',
                             webhook_on_failed=True)
        with patch('notifications.requests.post') as mock_post:
            result = send_webhook_notification(job)
        assert result is False
        mock_post.assert_not_called()

    def test_skips_if_localhost_url(self):
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://localhost/hook',
                             webhook_on_failed=True)
        with patch('notifications.requests.post') as mock_post:
            result = send_webhook_notification(job)
        assert result is False
        mock_post.assert_not_called()

    def test_skips_if_loopback_url(self):
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://127.0.0.1/hook',
                             webhook_on_failed=True)
        with patch('notifications.requests.post') as mock_post:
            result = send_webhook_notification(job)
        assert result is False
        mock_post.assert_not_called()

    def test_payload_connection_label_for_relay_flow(self):
        from notifications import send_webhook_notification
        job = self._make_job('done', webhook_url='http://hooks.example.com/',
                             webhook_on_done=True, use_flow=True)
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured['payload'] = json
            return MagicMock()

        with patch('notifications.requests.post', side_effect=capture_post):
            send_webhook_notification(job)

        assert captured['payload']['connection'] == 'RELAY: MyFlow'


class TestSendConnectionHealthEmail:
    def _make_connection(self, status='failed', email='u@example.com', notify_on_failed=True, error='CONNECTION FAILED — timeout'):
        conn = MagicMock()
        conn.pk = 7
        conn.name = 'ProdSSH'
        conn.host = '10.0.0.5'
        conn.port = 22
        conn.health_error = error
        conn.owner = MagicMock()
        conn.owner.email = email
        conn.owner.notify_on_failed = notify_on_failed
        return conn

    def test_skips_if_no_email(self):
        from notifications import send_connection_health_email
        conn = self._make_connection(email='')
        with patch('notifications.send_mail') as mock_mail:
            result = send_connection_health_email(conn, 'failed')
        assert result is False
        mock_mail.assert_not_called()

    def test_skips_if_notify_on_failed_false(self):
        from notifications import send_connection_health_email
        conn = self._make_connection(notify_on_failed=False)
        with patch('notifications.send_mail') as mock_mail:
            result = send_connection_health_email(conn, 'failed')
        assert result is False
        mock_mail.assert_not_called()

    def test_sends_email_on_failed(self):
        from notifications import send_connection_health_email
        conn = self._make_connection()
        with patch('notifications.send_mail') as mock_mail, \
             patch('notifications._render_connection_health_notification', return_value=('subj', 'plain', '<html>')):
            result = send_connection_health_email(conn, 'failed')
        assert result is True
        mock_mail.assert_called_once()
        assert 'u@example.com' in mock_mail.call_args[0][3]

    def test_sends_email_on_recovered(self):
        from notifications import send_connection_health_email
        conn = self._make_connection()
        with patch('notifications.send_mail') as mock_mail, \
             patch('notifications._render_connection_health_notification', return_value=('subj', 'plain', '<html>')):
            result = send_connection_health_email(conn, 'ok')
        assert result is True
        mock_mail.assert_called_once()


class TestSendConnectionHealthTelegram:
    def _make_connection(self, chat_id='123', telegram_on_failed=True):
        conn = MagicMock()
        conn.name = 'ProdSSH'
        conn.host = '10.0.0.5'
        conn.port = 22
        conn.health_error = 'CONNECTION FAILED — timeout'
        conn.owner = MagicMock()
        conn.owner.telegram_chat_id = chat_id
        conn.owner.telegram_on_failed = telegram_on_failed
        return conn

    def test_skips_if_no_chat_id(self):
        from notifications import send_connection_health_telegram
        conn = self._make_connection(chat_id='')
        with patch('notifications.requests') as mock_requests:
            result = send_connection_health_telegram(conn, 'failed')
        assert result is False
        mock_requests.post.assert_not_called()

    def test_skips_if_telegram_on_failed_false(self):
        from notifications import send_connection_health_telegram
        conn = self._make_connection(telegram_on_failed=False)
        with patch('notifications.requests') as mock_requests:
            result = send_connection_health_telegram(conn, 'failed')
        assert result is False
        mock_requests.post.assert_not_called()

    def test_skips_if_no_bot_token(self):
        from notifications import send_connection_health_telegram
        conn = self._make_connection()
        with patch('notifications.settings') as mock_settings, patch('notifications.requests') as mock_requests:
            mock_settings.TELEGRAM_BOT_TOKEN = ''
            result = send_connection_health_telegram(conn, 'failed')
        assert result is False
        mock_requests.post.assert_not_called()

    def test_sends_telegram_on_failed(self):
        from notifications import send_connection_health_telegram
        conn = self._make_connection()
        with patch('notifications.settings') as mock_settings, patch('notifications.requests') as mock_requests:
            mock_settings.TELEGRAM_BOT_TOKEN = 'tok'
            mock_requests.post.return_value.raise_for_status.return_value = None
            result = send_connection_health_telegram(conn, 'failed')
        assert result is True
        mock_requests.post.assert_called_once()
        payload = mock_requests.post.call_args[1]['json']
        assert payload['chat_id'] == '123'
        assert 'FAILED' in payload['text']

    def test_sends_telegram_on_recovered(self):
        from notifications import send_connection_health_telegram
        conn = self._make_connection()
        with patch('notifications.settings') as mock_settings, patch('notifications.requests') as mock_requests:
            mock_settings.TELEGRAM_BOT_TOKEN = 'tok'
            mock_requests.post.return_value.raise_for_status.return_value = None
            result = send_connection_health_telegram(conn, 'ok')
        assert result is True
        payload = mock_requests.post.call_args[1]['json']
        assert 'RECOVERED' in payload['text']


class TestSendConnectionHealthWebhook:
    def _make_connection(self, webhook_url='http://hooks.example.com/', webhook_on_failed=True):
        conn = MagicMock()
        conn.pk = 7
        conn.name = 'ProdSSH'
        conn.host = '10.0.0.5'
        conn.port = 22
        conn.health_error = 'CONNECTION FAILED — timeout'
        conn.owner = MagicMock()
        conn.owner.webhook_url = webhook_url
        conn.owner.webhook_on_failed = webhook_on_failed
        return conn

    def test_skips_if_no_webhook_url(self):
        from notifications import send_connection_health_webhook
        conn = self._make_connection(webhook_url='')
        with patch('notifications.requests') as mock_requests:
            result = send_connection_health_webhook(conn, 'failed')
        assert result is False
        mock_requests.post.assert_not_called()

    def test_skips_if_webhook_on_failed_false(self):
        from notifications import send_connection_health_webhook
        conn = self._make_connection(webhook_on_failed=False)
        with patch('notifications.requests') as mock_requests:
            result = send_connection_health_webhook(conn, 'failed')
        assert result is False
        mock_requests.post.assert_not_called()

    def test_skips_if_url_targets_private_address(self):
        from notifications import send_connection_health_webhook
        conn = self._make_connection(webhook_url='http://127.0.0.1/hook')
        result = send_connection_health_webhook(conn, 'failed')
        assert result is False

    def test_sends_generic_payload_for_non_slack_url(self):
        from notifications import send_connection_health_webhook
        conn = self._make_connection()
        with patch('notifications.requests') as mock_requests, \
             patch('notifications.block_private_url'):
            mock_requests.post.return_value.raise_for_status.return_value = None
            result = send_connection_health_webhook(conn, 'failed')
        assert result is True
        payload = mock_requests.post.call_args[1]['json']
        assert payload['connection_id'] == 7
        assert payload['status'] == 'failed'

    def test_sends_slack_payload_for_slack_url(self):
        from notifications import send_connection_health_webhook
        conn = self._make_connection(webhook_url='https://hooks.slack.com/services/x')
        with patch('notifications.requests') as mock_requests, \
             patch('notifications.block_private_url'):
            mock_requests.post.return_value.raise_for_status.return_value = None
            result = send_connection_health_webhook(conn, 'ok')
        assert result is True
        payload = mock_requests.post.call_args[1]['json']
        assert 'text' in payload
        assert 'RECOVERED' in payload['text']
