import base64
import secrets
from io import BytesIO

import pyotp
import qrcode
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

RECOVERY_CODE_COUNT = 10
ISSUER_NAME = 'tmask-transporter'


def generate_secret() -> str:
    return pyotp.random_base32()


def build_provisioning_uri(secret: str, username: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER_NAME)


def build_qr_data_uri(uri: str) -> str:
    img = qrcode.make(uri)
    buf = BytesIO()
    img.save(buf, format='PNG')
    encoded = base64.b64encode(buf.getvalue()).decode('ascii')
    return f'data:image/png;base64,{encoded}'


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def normalize_recovery_code(raw: str) -> str:
    stripped = raw.strip().upper().replace('-', '')
    if len(stripped) != 8:
        return stripped
    return f'{stripped[:4]}-{stripped[4:]}'


def generate_recovery_codes(user) -> list:
    from .models import TOTPRecoveryCode

    TOTPRecoveryCode.objects.filter(user=user).delete()
    plaintext_codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(4).upper()
        code = f'{raw[:4]}-{raw[4:]}'
        TOTPRecoveryCode.objects.create(user=user, code_hash=make_password(code))
        plaintext_codes.append(code)
    return plaintext_codes


def check_recovery_code(user, raw_code: str):
    from .models import TOTPRecoveryCode

    normalized = normalize_recovery_code(raw_code)
    with transaction.atomic():
        unused_codes = TOTPRecoveryCode.objects.select_for_update().filter(
            user=user, used_at__isnull=True
        )
        for recovery_code in unused_codes:
            if check_password(normalized, recovery_code.code_hash):
                recovery_code.used_at = timezone.now()
                recovery_code.save(update_fields=['used_at'])
                return recovery_code
    return None
