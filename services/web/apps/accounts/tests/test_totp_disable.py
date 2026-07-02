import pytest
from django.urls import reverse


def _enable_totp(user):
    from apps.accounts import totp
    user.totp_secret = totp.generate_secret()
    user.totp_enabled = True
    user.save()
    totp.generate_recovery_codes(user)
    return user


@pytest.mark.django_db
class TestTotpDisable:
    def test_requires_login(self, client):
        response = client.post(reverse('accounts:2fa_disable'), {'password': 'x'})
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_correct_password_disables_totp(self, auth_client, regular_user):
        _enable_totp(regular_user)
        response = auth_client.post(reverse('accounts:2fa_disable'), {'password': 'testpass123'})
        assert response.status_code == 302
        regular_user.refresh_from_db()
        assert regular_user.totp_enabled is False
        assert regular_user.totp_secret == ''

    def test_correct_password_deletes_recovery_codes(self, auth_client, regular_user):
        from apps.accounts.models import TOTPRecoveryCode

        _enable_totp(regular_user)
        auth_client.post(reverse('accounts:2fa_disable'), {'password': 'testpass123'})
        assert TOTPRecoveryCode.objects.filter(user=regular_user).count() == 0

    def test_wrong_password_does_not_disable(self, auth_client, regular_user):
        _enable_totp(regular_user)
        response = auth_client.post(reverse('accounts:2fa_disable'), {'password': 'wrong'})
        assert response.status_code == 302
        regular_user.refresh_from_db()
        assert regular_user.totp_enabled is True


@pytest.mark.django_db
class TestProfilePageShowsTotpStatus:
    def test_shows_enable_button_when_disabled(self, auth_client):
        response = auth_client.get(reverse('accounts:profile'))
        assert 'WŁĄCZ 2FA'.encode() in response.content or b'2fa/setup' in response.content

    def test_shows_disable_form_when_enabled(self, auth_client, regular_user):
        _enable_totp(regular_user)
        response = auth_client.get(reverse('accounts:profile'))
        assert b'2fa/disable' in response.content
