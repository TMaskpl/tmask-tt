# services/worker/modules/sftp/handler.py
import os
import socket
import time

import paramiko

from .config import SFTP_TIMEOUT, SFTP_MAX_RETRIES, SFTP_RETRY_DELAY
from modules.gpg.handler import encrypt_file, GPGEncryptError
from modules.checksum.handler import verify_sftp, ChecksumVerificationError
from modules.ssh_keys import load_private_key


class SFTPTransferError(Exception):
    pass


class SFTPHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_client(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        if self.params.get('strict_host_key_checking'):
            if not self.params.get('known_host_key'):
                raise SFTPTransferError(
                    'CONFIG ERROR — strict_host_key_checking requires known_host_key'
                )
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
                f.write(self.params['known_host_key'])
                tmp_path = f.name
            try:
                client.load_host_keys(tmp_path)
            finally:
                os.unlink(tmp_path)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507 — user disabled strict_host_key_checking
        return client

    def _connect(self, client: paramiko.SSHClient) -> None:
        connect_kwargs = {
            'hostname': self.params['host'],
            'port': self.params['port'],
            'username': self.params['username'],
            'timeout': SFTP_TIMEOUT,
            'look_for_keys': False,
            'allow_agent': False,
        }
        if self.params.get('ssh_key'):
            connect_kwargs['pkey'] = load_private_key(
                self.params['ssh_key'], self.params.get('ssh_key_passphrase') or None
            )
        elif self.params.get('password'):
            connect_kwargs['password'] = self.params['password']
        client.connect(**connect_kwargs)

    def _verify_checksum_sftp(self, source: str, client, dest: str, log_callback, use_gpg: bool) -> None:
        if not self.params.get('verify_checksum'):
            return
        if use_gpg:
            log_callback('warn', 'SHA-256: pomijane — GPG włączone (encrypted file)')
            return
        try:
            verify_sftp(source, client, dest, log_callback)
        except ChecksumVerificationError as e:
            raise SFTPTransferError(str(e))

    def _transfer_once(self, source: str, dest: str, log_callback, use_gpg: bool = False,
                        progress_callback=None) -> None:
        """Single SFTP connection + transfer. socket.timeout/gaierror bubble up for retry."""
        client = self._build_client()
        try:
            log_callback('info', f'Connecting to {self.params["host"]}:{self.params["port"]}')
            try:
                self._connect(client)
            except paramiko.AuthenticationException:
                raise SFTPTransferError('AUTH FAILED — check credentials')
            log_callback('info', 'Authentication OK')
            log_callback('info', f'Transferring: {source}')
            with client.open_sftp() as sftp:
                def _progress(done: int, total: int) -> None:
                    if total and progress_callback:
                        progress_callback(int(done / total * 100))
                sftp.put(source, dest, callback=_progress)
            self._verify_checksum_sftp(source, client, dest, log_callback, use_gpg)
            log_callback('info', 'Transfer complete')
        except (socket.timeout, socket.gaierror, TimeoutError):
            raise
        except FileNotFoundError:
            raise SFTPTransferError(f'SOURCE NOT FOUND: {source}')
        except OSError as e:
            if 'No space' in str(e):
                raise SFTPTransferError('INSUFFICIENT SPACE ON DESTINATION')
            raise SFTPTransferError(f'TRANSFER ERROR — {e}')
        except paramiko.SSHException as e:
            raise SFTPTransferError(f'SSH ERROR — {e}')
        finally:
            client.close()

    def execute(self, log_callback, progress_callback=None) -> None:
        if not (self.params.get('strict_host_key_checking') and self.params.get('known_host_key')):
            log_callback('warn', 'Host key verification DISABLED — connection is vulnerable to MITM')

        use_gpg = bool(self.params.get('gpg_passphrase'))
        encrypted_path = None

        try:
            if use_gpg:
                log_callback('info', 'GPG: szyfrowanie pliku...')
                try:
                    encrypted_path = encrypt_file(self.params['source_path'], self.params['gpg_passphrase'])
                except GPGEncryptError as e:
                    raise SFTPTransferError(str(e))
                source = encrypted_path
                dest = self.params['destination_path'] + '.gpg'
            else:
                source = self.params['source_path']
                dest = self.params['destination_path']

            for attempt in range(1, SFTP_MAX_RETRIES + 1):
                try:
                    self._transfer_once(source, dest, log_callback, use_gpg=use_gpg,
                                         progress_callback=progress_callback)
                    return
                except (socket.timeout, socket.gaierror):
                    if attempt < SFTP_MAX_RETRIES:
                        log_callback('warn', f'Connection failed, retrying in {SFTP_RETRY_DELAY}s...')
                        time.sleep(SFTP_RETRY_DELAY)

            raise SFTPTransferError(f'CONNECTION TIMEOUT — {self.params["host"]} unreachable')
        finally:
            if encrypted_path and os.path.exists(encrypted_path):
                os.unlink(encrypted_path)
