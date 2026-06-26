import base64
import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from apps.flows.models import Flow
from .models import Connection

FORMAT = "tmask-transporter-config"
VERSION = 1
KDF_ITERATIONS = 600000
CHECK_MARKER = b"tmask-config-v1"

CONNECTION_FIELDS = [
    'name', 'host', 'port', 'username', 'protocol', 'compress', 'encrypt',
    'strict_host_key_checking', 'known_host_key', 'dry_run_before_transfer',
    'verify_checksum',
]


class PassphraseError(Exception):
    pass


@dataclass
class ImportResult:
    conn_added: int = 0
    conn_skipped: int = 0
    flow_added: int = 0
    flow_skipped: int = 0
    flow_unresolved: int = 0


def _derive_key(passphrase: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=iterations)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def _encrypt_secret(plaintext, fernet: Fernet):
    if not plaintext:
        return None
    return fernet.encrypt(plaintext.encode()).decode()


def _decrypt_secret(token, fernet: Fernet):
    if token is None:
        return None
    return fernet.decrypt(token.encode()).decode()


def export_config(user, passphrase: str) -> dict:
    salt = os.urandom(16)
    fernet = Fernet(_derive_key(passphrase, salt))
    connections = []
    for c in Connection.objects.filter(owner=user):
        row = {f: getattr(c, f) for f in CONNECTION_FIELDS}
        row['password_enc'] = _encrypt_secret(c.password, fernet)
        row['ssh_key_enc'] = _encrypt_secret(c.ssh_key, fernet)
        connections.append(row)
    flows = []
    for fl in Flow.objects.filter(owner=user):
        flows.append({
            'name': fl.name,
            'source_conn': fl.source_conn.name,
            'source_path': fl.source_path,
            'dest_conn': fl.dest_conn.name,
            'dest_path': fl.dest_path,
            'verify_checksum': fl.verify_checksum,
        })
    return {
        'format': FORMAT,
        'version': VERSION,
        'kdf': {
            'algo': 'pbkdf2_sha256',
            'iterations': KDF_ITERATIONS,
            'salt': base64.b64encode(salt).decode(),
        },
        'check': fernet.encrypt(CHECK_MARKER).decode(),
        'connections': connections,
        'flows': flows,
    }
