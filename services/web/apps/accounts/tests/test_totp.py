import pyotp
import pytest

from apps.accounts import totp
from apps.accounts.models import TOTPRecoveryCode


@pytest.mark.django_db
class TestUserTotpFields:
    def test_totp_secret_default_empty(self, django_user_model):
        user = django_user_model.objects.create_user(username='u1', password='p')
        assert user.totp_secret == ''

    def test_totp_enabled_default_false(self, django_user_model):
        user = django_user_model.objects.create_user(username='u2', password='p')
        assert user.totp_enabled is False


class TestGenerateSecret:
    def test_generates_valid_base32_secret(self):
        secret = totp.generate_secret()
        assert len(secret) == 32
        pyotp.TOTP(secret)  # nie rzuca — poprawny format


class TestProvisioningUriAndQr:
    def test_provisioning_uri_contains_username_and_issuer(self):
        uri = totp.build_provisioning_uri('JBSWY3DPEHPK3PXP', 'alice')
        assert uri.startswith('otpauth://totp/')
        assert 'alice' in uri
        assert 'tmask-transporter' in uri

    def test_qr_data_uri_is_base64_png(self):
        uri = totp.build_provisioning_uri('JBSWY3DPEHPK3PXP', 'alice')
        data_uri = totp.build_qr_data_uri(uri)
        assert data_uri.startswith('data:image/png;base64,')


class TestVerifyTotp:
    def test_current_code_is_valid(self):
        secret = totp.generate_secret()
        code = pyotp.TOTP(secret).now()
        assert totp.verify_totp(secret, code) is True

    def test_wrong_code_is_invalid(self):
        secret = totp.generate_secret()
        assert totp.verify_totp(secret, '000000') is False


class TestNormalizeRecoveryCode:
    def test_strips_and_uppercases(self):
        assert totp.normalize_recovery_code('  a1b2-c3d4  ') == 'A1B2-C3D4'

    def test_reinserts_dash_when_missing(self):
        assert totp.normalize_recovery_code('a1b2c3d4') == 'A1B2-C3D4'

    def test_collapses_extra_dashes(self):
        assert totp.normalize_recovery_code('A1-B2-C3-D4') == 'A1B2-C3D4'


@pytest.mark.django_db
class TestGenerateRecoveryCodes:
    def test_creates_exactly_ten_codes(self, django_user_model):
        user = django_user_model.objects.create_user(username='u3', password='p')
        codes = totp.generate_recovery_codes(user)
        assert len(codes) == 10
        assert TOTPRecoveryCode.objects.filter(user=user).count() == 10

    def test_codes_match_canonical_format(self, django_user_model):
        user = django_user_model.objects.create_user(username='u4', password='p')
        codes = totp.generate_recovery_codes(user)
        for code in codes:
            assert len(code) == 9  # XXXX-XXXX
            assert code[4] == '-'

    def test_regenerating_deletes_old_codes(self, django_user_model):
        user = django_user_model.objects.create_user(username='u5', password='p')
        first_batch = totp.generate_recovery_codes(user)
        totp.generate_recovery_codes(user)
        assert TOTPRecoveryCode.objects.filter(user=user).count() == 10
        remaining_hashes = set(TOTPRecoveryCode.objects.filter(user=user).values_list('code_hash', flat=True))
        from django.contrib.auth.hashers import check_password
        assert not any(check_password(c, h) for c in first_batch for h in remaining_hashes)


@pytest.mark.django_db
class TestCheckRecoveryCode:
    def test_valid_unused_code_matches_and_marks_used(self, django_user_model):
        user = django_user_model.objects.create_user(username='u6', password='p')
        codes = totp.generate_recovery_codes(user)
        result = totp.check_recovery_code(user, codes[0])
        assert result is not None
        assert result.used_at is not None

    def test_valid_code_accepted_without_dash(self, django_user_model):
        user = django_user_model.objects.create_user(username='u7', password='p')
        codes = totp.generate_recovery_codes(user)
        raw_no_dash = codes[0].replace('-', '').lower()
        result = totp.check_recovery_code(user, raw_no_dash)
        assert result is not None

    def test_used_code_rejected_on_second_attempt(self, django_user_model):
        user = django_user_model.objects.create_user(username='u8', password='p')
        codes = totp.generate_recovery_codes(user)
        totp.check_recovery_code(user, codes[0])
        second_attempt = totp.check_recovery_code(user, codes[0])
        assert second_attempt is None

    def test_unknown_code_returns_none(self, django_user_model):
        user = django_user_model.objects.create_user(username='u9', password='p')
        totp.generate_recovery_codes(user)
        assert totp.check_recovery_code(user, 'ZZZZ-ZZZZ') is None

    def test_code_belonging_to_other_user_rejected(self, django_user_model):
        user1 = django_user_model.objects.create_user(username='u10', password='p')
        user2 = django_user_model.objects.create_user(username='u11', password='p')
        codes = totp.generate_recovery_codes(user1)
        assert totp.check_recovery_code(user2, codes[0]) is None
