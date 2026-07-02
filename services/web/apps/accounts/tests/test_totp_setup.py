import pyotp
import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestTotpSetupGet:
    def test_requires_login(self, client):
        response = client.get(reverse('accounts:2fa_setup'))
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_renders_qr_and_form(self, auth_client):
        response = auth_client.get(reverse('accounts:2fa_setup'))
        assert response.status_code == 200
        assert 'data:image/png;base64,' in response.content.decode()

    def test_stores_pending_secret_in_session(self, auth_client):
        auth_client.get(reverse('accounts:2fa_setup'))
        assert 'pending_totp_secret' in auth_client.session

    def test_redirects_if_already_enabled(self, auth_client, regular_user):
        from apps.accounts import totp
        regular_user.totp_secret = totp.generate_secret()
        regular_user.totp_enabled = True
        regular_user.save()
        response = auth_client.get(reverse('accounts:2fa_setup'))
        assert response.status_code == 302
        assert response['Location'] == reverse('accounts:profile')


@pytest.mark.django_db
class TestTotpSetupPost:
    def test_valid_code_enables_totp_and_generates_recovery_codes(self, auth_client, regular_user):
        from apps.accounts.models import TOTPRecoveryCode

        auth_client.get(reverse('accounts:2fa_setup'))
        secret = auth_client.session['pending_totp_secret']
        code = pyotp.TOTP(secret).now()
        response = auth_client.post(reverse('accounts:2fa_setup'), {'code': code})
        assert response.status_code == 302
        assert response['Location'] == reverse('accounts:2fa_recovery_codes')
        regular_user.refresh_from_db()
        assert regular_user.totp_enabled is True
        assert regular_user.totp_secret == secret
        assert TOTPRecoveryCode.objects.filter(user=regular_user).count() == 10

    def test_valid_code_stores_recovery_codes_in_session(self, auth_client, regular_user):
        auth_client.get(reverse('accounts:2fa_setup'))
        secret = auth_client.session['pending_totp_secret']
        code = pyotp.TOTP(secret).now()
        auth_client.post(reverse('accounts:2fa_setup'), {'code': code})
        assert len(auth_client.session['new_recovery_codes']) == 10

    def test_invalid_code_does_not_enable_totp(self, auth_client, regular_user):
        auth_client.get(reverse('accounts:2fa_setup'))
        response = auth_client.post(reverse('accounts:2fa_setup'), {'code': '000000'})
        assert response.status_code == 200
        regular_user.refresh_from_db()
        assert regular_user.totp_enabled is False

    def test_invalid_code_keeps_pending_secret_for_retry(self, auth_client):
        auth_client.get(reverse('accounts:2fa_setup'))
        secret_before = auth_client.session['pending_totp_secret']
        auth_client.post(reverse('accounts:2fa_setup'), {'code': '000000'})
        assert auth_client.session['pending_totp_secret'] == secret_before

    def test_post_without_pending_session_secret_does_not_crash(self, auth_client):
        response = auth_client.post(reverse('accounts:2fa_setup'), {'code': '123456'})
        assert response.status_code == 200
        assert 'pending_totp_secret' in auth_client.session


@pytest.mark.django_db
class TestTotpRecoveryCodesView:
    def test_requires_login(self, client):
        response = client.get(reverse('accounts:2fa_recovery_codes'))
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_shows_codes_from_session(self, auth_client):
        session = auth_client.session
        session['new_recovery_codes'] = ['AAAA-BBBB', 'CCCC-DDDD']
        session.save()
        response = auth_client.get(reverse('accounts:2fa_recovery_codes'))
        assert response.status_code == 200
        content = response.content.decode()
        assert 'AAAA-BBBB' in content
        assert 'CCCC-DDDD' in content

    def test_pops_codes_from_session(self, auth_client):
        session = auth_client.session
        session['new_recovery_codes'] = ['AAAA-BBBB']
        session.save()
        auth_client.get(reverse('accounts:2fa_recovery_codes'))
        assert 'new_recovery_codes' not in auth_client.session

    def test_redirects_without_pending_codes(self, auth_client):
        response = auth_client.get(reverse('accounts:2fa_recovery_codes'))
        assert response.status_code == 302
        assert response['Location'] == reverse('accounts:profile')
