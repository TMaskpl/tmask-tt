import os
import socket
import tempfile
from dataclasses import dataclass

import paramiko

from .ssh_keys import load_private_key


@dataclass
class SSHTestResult:
    success: bool
    message: str


def test_connection(connection) -> SSHTestResult:
    client = paramiko.SSHClient()

    if connection.strict_host_key_checking and connection.known_host_key:
        with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
            f.write(connection.known_host_key)
            tmp_path = f.name
        try:
            client.load_host_keys(tmp_path)
        finally:
            os.unlink(tmp_path)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507 — user disabled strict_host_key_checking

    try:
        connect_kwargs = {
            'hostname': connection.host,
            'port': connection.port,
            'username': connection.username,
            'timeout': 10,
            'look_for_keys': False,
            'allow_agent': False,
        }
        if connection.ssh_key:
            connect_kwargs['pkey'] = load_private_key(connection.ssh_key, connection.ssh_key_passphrase or None)
        elif connection.password:
            connect_kwargs['password'] = connection.password
        else:
            return SSHTestResult(False, 'AUTH FAILED — brak danych uwierzytelniania')

        client.connect(**connect_kwargs)
        # Host:port celowo pominięte — już widoczne w kolumnach HOST/PORT tej samej tabeli
        return SSHTestResult(True, 'CONNECTION OK')

    except paramiko.AuthenticationException:
        return SSHTestResult(False, 'AUTH FAILED — nieprawidłowe dane uwierzytelniania')
    except (socket.timeout, socket.gaierror):
        return SSHTestResult(False, f'CONNECTION TIMEOUT — {connection.host} nieosiągalny')
    except paramiko.SSHException as e:
        return SSHTestResult(False, f'SSH ERROR — {e}')
    finally:
        client.close()
