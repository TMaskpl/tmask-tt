import base64
import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from django.db import transaction

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


def import_config(user, data: dict, passphrase: str) -> ImportResult:
    if data.get('format') != FORMAT or data.get('version') != VERSION:
        raise ValueError('Nieprawidłowy format pliku')
    salt = base64.b64decode(data['kdf']['salt'])
    iterations = data['kdf'].get('iterations', KDF_ITERATIONS)
    fernet = Fernet(_derive_key(passphrase, salt, iterations))
    try:
        fernet.decrypt(data['check'].encode())
    except InvalidToken:
        raise PassphraseError('Błędne hasło lub uszkodzony plik')

    result = ImportResult()
    with transaction.atomic():
        existing = set(
            Connection.objects.filter(owner=user).values_list('name', flat=True)
        )
        for row in data.get('connections', []):
            if row['name'] in existing:
                result.conn_skipped += 1
                continue
            conn = Connection(owner=user)
            for f in CONNECTION_FIELDS:
                setattr(conn, f, row.get(f))
            try:
                conn.password = _decrypt_secret(row.get('password_enc'), fernet)
                conn.ssh_key = _decrypt_secret(row.get('ssh_key_enc'), fernet)
            except InvalidToken:
                raise PassphraseError('Błędne hasło lub uszkodzony plik')
            conn.save()
            existing.add(row['name'])
            result.conn_added += 1

        conn_map = {c.name: c for c in Connection.objects.filter(owner=user)}
        existing_flows = set(
            Flow.objects.filter(owner=user).values_list('name', flat=True)
        )
        for row in data.get('flows', []):
            if row['name'] in existing_flows:
                result.flow_skipped += 1
                continue
            src = conn_map.get(row['source_conn'])
            dst = conn_map.get(row['dest_conn'])
            if src is None or dst is None:
                result.flow_unresolved += 1
                continue
            Flow.objects.create(
                owner=user, name=row['name'],
                source_conn=src, source_path=row['source_path'],
                dest_conn=dst, dest_path=row['dest_path'],
                verify_checksum=row.get('verify_checksum', False),
            )
            existing_flows.add(row['name'])
            result.flow_added += 1
    return result
