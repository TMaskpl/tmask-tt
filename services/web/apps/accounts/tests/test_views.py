import pytest
from django.urls import reverse
from unittest.mock import MagicMock, patch


@pytest.mark.django_db
class TestLoginView:
    def test_login_page_renders(self, client):
        url = reverse('accounts:login')
        response = client.get(url)
        assert response.status_code == 200

    def test_login_with_valid_credentials(self, client, regular_user):
        url = reverse('accounts:login')
        response = client.post(url, {'username': 'user_test', 'password': 'testpass123'})
        assert response.status_code == 302

    def test_login_with_invalid_credentials(self, client):
        url = reverse('accounts:login')
        response = client.post(url, {'username': 'wrong', 'password': 'wrong'})
        assert response.status_code == 200
        assert '__all__' in response.context['form'].errors

    def test_logout_redirects_to_login(self, auth_client):
        url = reverse('accounts:logout')
        response = auth_client.post(url)
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_unauthenticated_access_to_users_requires_login(self, client):
        url = reverse('accounts:users')
        response = client.get(url)
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_regular_user_cannot_access_users_list(self, auth_client):
        url = reverse('accounts:users')
        response = auth_client.get(url)
        assert response.status_code == 403


@pytest.mark.django_db
class TestProfileView:
    def test_unauthenticated_redirects_to_login(self, client):
        url = reverse('accounts:profile')
        response = client.get(url)
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_get_renders_form_with_current_values(self, auth_client, regular_user):
        regular_user.email = 'existing@example.com'
        regular_user.save()
        url = reverse('accounts:profile')
        response = auth_client.get(url)
        assert response.status_code == 200
        assert response.context['form'].instance.email == 'existing@example.com'

    def test_post_saves_prefs_and_redirects(self, auth_client, regular_user):
        url = reverse('accounts:profile')
        response = auth_client.post(url, {
            'email': 'updated@example.com',
            'notify_on_done': True,
            'notify_on_failed': False,
            'webhook_url': 'http://hooks.slack.com/test',
            'webhook_on_done': True,
            'webhook_on_failed': False,
        })
        assert response.status_code == 302
        regular_user.refresh_from_db()
        assert regular_user.email == 'updated@example.com'
        assert regular_user.notify_on_done is True
        assert regular_user.notify_on_failed is False
        assert regular_user.webhook_url == 'http://hooks.slack.com/test'
        assert regular_user.webhook_on_done is True
        assert regular_user.webhook_on_failed is False

    def test_post_with_invalid_email_shows_errors(self, auth_client):
        url = reverse('accounts:profile')
        response = auth_client.post(url, {
            'email': 'not-an-email',
            'notify_on_done': False,
            'notify_on_failed': True,
        })
        assert response.status_code == 200
        assert 'email' in response.context['form'].errors


@pytest.mark.django_db
class TestNotificationTemplates:
    def _make_job(self, django_user_model, status, error_message=None):
        from apps.transfers.models import TransferJob
        from apps.connections.models import Connection
        user = django_user_model.objects.create_user(username='tpl_user', password='p')
        conn = Connection.objects.create(
            owner=user, name='TestSrv', host='10.0.0.1', port=22,
            username='u', password='p', protocol='sftp',
        )
        job = TransferJob.objects.create(
            owner=user, connection=conn,
            source_path='/data/file.tar',
            destination_path='/backup/file.tar',
            status=status,
        )
        if error_message:
            job.error_message = error_message
            job.save()
        return job

    def test_done_plain_text_contains_key_data(self, django_user_model):
        from django.template.loader import render_to_string
        job = self._make_job(django_user_model, 'done')
        result = render_to_string('notifications/transfer_done.txt', {'job': job})
        assert 'DONE' in result
        assert str(job.pk) in result
        assert '/data/file.tar' in result
        assert '/backup/file.tar' in result

    def test_failed_plain_text_contains_error(self, django_user_model):
        from django.template.loader import render_to_string
        job = self._make_job(django_user_model, 'failed', error_message='AUTH FAILED')
        result = render_to_string('notifications/transfer_failed.txt', {'job': job})
        assert 'FAILED' in result
        assert 'AUTH FAILED' in result
        assert str(job.pk) in result

    def test_done_html_contains_job_data(self, django_user_model):
        from django.template.loader import render_to_string
        job = self._make_job(django_user_model, 'done')
        result = render_to_string('notifications/transfer_done.html', {'job': job})
        assert str(job.pk) in result
        assert '/data/file.tar' in result
        assert '33ff33' in result

    def test_failed_html_contains_error_color(self, django_user_model):
        from django.template.loader import render_to_string
        job = self._make_job(django_user_model, 'failed', error_message='TIMEOUT')
        result = render_to_string('notifications/transfer_failed.html', {'job': job})
        assert 'TIMEOUT' in result
        assert 'ff3333' in result


@pytest.mark.django_db
class TestTestWebhookView:
    def test_requires_login(self, client):
        url = reverse('accounts:test_webhook')
        response = client.post(url, {'webhook_url': 'http://hooks.example.com/'})
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_returns_ok_on_success(self, auth_client):
        url = reverse('accounts:test_webhook')
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch('apps.accounts.views.requests.post', return_value=mock_resp):
            response = auth_client.post(url, {'webhook_url': 'http://hooks.example.com/'})
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert data['code'] == 200

    def test_returns_error_on_connection_refused(self, auth_client):
        import requests as req
        url = reverse('accounts:test_webhook')
        with patch('apps.accounts.views.requests.post',
                   side_effect=req.ConnectionError('Connection refused')):
            response = auth_client.post(url, {'webhook_url': 'http://hooks.example.com/'})
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is False
        assert 'Connection refused' in data['error']

    def test_returns_error_on_missing_url(self, auth_client):
        url = reverse('accounts:test_webhook')
        response = auth_client.post(url, {'webhook_url': ''})
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is False
        assert 'URL' in data['error']

    def test_returns_error_on_timeout(self, auth_client):
        import requests as req
        url = reverse('accounts:test_webhook')
        with patch('apps.accounts.views.requests.post',
                   side_effect=req.Timeout('timeout')):
            response = auth_client.post(url, {'webhook_url': 'http://hooks.example.com/'})
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is False
