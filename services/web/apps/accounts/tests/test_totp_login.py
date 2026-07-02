import pyotp
import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestLoginWithoutTotp:
    def test_regular_login_unaffected(self, client, regular_user):
        response = client.post(reverse('accounts:login'), {'username': 'user_test', 'password': 'testpass123'})
        assert response.status_code == 302
        assert response['Location'] not in [reverse('accounts:2fa_verify')]
        session = client.session
        assert '_auth_user_id' in session


@pytest.mark.django_db
class TestLoginWithTotpRedirectsToVerify:
    def _enable_totp(self, user):
        from apps.accounts import totp
        secret = totp.generate_secret()
        user.totp_secret = secret
        user.totp_enabled = True
        user.save()
        return secret

    def test_password_alone_does_not_log_in(self, client, regular_user):
        self._enable_totp(regular_user)
        response = client.post(reverse('accounts:login'), {'username': 'user_test', 'password': 'testpass123'})
        assert response.status_code == 302
        assert response['Location'] == reverse('accounts:2fa_verify')
        assert '_auth_user_id' not in client.session

    def test_sets_pre_2fa_session(self, client, regular_user):
        self._enable_totp(regular_user)
        client.post(reverse('accounts:login'), {'username': 'user_test', 'password': 'testpass123'})
        assert client.session['pre_2fa_user_id'] == regular_user.id
        assert client.session['pre_2fa_attempts'] == 0


@pytest.mark.django_db
class TestTotpVerifyView:
    def _login_step_one(self, client, user, password='testpass123'):
        from apps.accounts import totp
        secret = totp.generate_secret()
        user.totp_secret = secret
        user.totp_enabled = True
        user.save()
        client.post(reverse('accounts:login'), {'username': user.username, 'password': password})
        return secret

    def test_get_without_pre_2fa_session_redirects_to_login(self, client):
        response = client.get(reverse('accounts:2fa_verify'))
        assert response.status_code == 302
        assert response['Location'] == reverse('accounts:login')

    def test_valid_totp_code_logs_in(self, client, regular_user):
        secret = self._login_step_one(client, regular_user)
        code = pyotp.TOTP(secret).now()
        response = client.post(reverse('accounts:2fa_verify'), {'code': code})
        assert response.status_code == 302
        assert client.session['_auth_user_id'] == str(regular_user.id)

    def test_valid_totp_code_clears_pre_2fa_session(self, client, regular_user):
        secret = self._login_step_one(client, regular_user)
        code = pyotp.TOTP(secret).now()
        client.post(reverse('accounts:2fa_verify'), {'code': code})
        assert 'pre_2fa_user_id' not in client.session

    def test_valid_recovery_code_logs_in_and_marks_used(self, client, regular_user):
        from apps.accounts import totp
        from apps.accounts.models import TOTPRecoveryCode

        self._login_step_one(client, regular_user)
        codes = totp.generate_recovery_codes(regular_user)
        response = client.post(reverse('accounts:2fa_verify'), {'code': codes[0]})
        assert response.status_code == 302
        assert client.session['_auth_user_id'] == str(regular_user.id)
        assert TOTPRecoveryCode.objects.filter(user=regular_user, used_at__isnull=False).count() == 1

    def test_wrong_code_does_not_log_in(self, client, regular_user):
        self._login_step_one(client, regular_user)
        response = client.post(reverse('accounts:2fa_verify'), {'code': '000000'})
        assert response.status_code == 200
        assert '_auth_user_id' not in client.session

    def test_wrong_code_increments_attempts(self, client, regular_user):
        self._login_step_one(client, regular_user)
        client.post(reverse('accounts:2fa_verify'), {'code': '000000'})
        assert client.session['pre_2fa_attempts'] == 1

    def test_fifth_wrong_attempt_clears_pre_2fa_session(self, client, regular_user):
        self._login_step_one(client, regular_user)
        for _ in range(5):
            client.post(reverse('accounts:2fa_verify'), {'code': '000000'})
        assert 'pre_2fa_user_id' not in client.session

    def test_after_five_attempts_redirects_to_login(self, client, regular_user):
        self._login_step_one(client, regular_user)
        for _ in range(4):
            client.post(reverse('accounts:2fa_verify'), {'code': '000000'})
        response = client.post(reverse('accounts:2fa_verify'), {'code': '000000'})
        assert response.status_code == 302
        assert response['Location'] == reverse('accounts:login')
