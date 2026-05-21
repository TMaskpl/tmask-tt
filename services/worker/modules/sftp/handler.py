import io
import socket
import time

import paramiko

from .config import SFTP_TIMEOUT, SFTP_MAX_RETRIES, SFTP_RETRY_DELAY


class SFTPTransferError(Exception):
    pass


class SFTPHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_client(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        if self.params.get('strict_host_key_checking') and self.params.get('known_host_key'):
            import os
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
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
            connect_kwargs['pkey'] = paramiko.PKey.from_private_key(
                io.StringIO(self.params['ssh_key'])
            )
        elif self.params.get('password'):
            connect_kwargs['password'] = self.params['password']
        client.connect(**connect_kwargs)

    def execute(self, log_callback) -> None:
        if not (self.params.get('strict_host_key_checking') and self.params.get('known_host_key')):
            log_callback('warn', 'Host key verification DISABLED — connection is vulnerable to MITM')

        last_error = None

        for attempt in range(1, SFTP_MAX_RETRIES + 1):
            client = self._build_client()
            try:
                log_callback('info', f'Connecting to {self.params["host"]}:{self.params["port"]} (attempt {attempt})')
                self._connect(client)
                log_callback('info', 'Authentication OK')
                try:
                    log_callback('info', f'Transferring: {self.params["source_path"]}')
                    with client.open_sftp() as sftp:
                        def _progress(done: int, total: int) -> None:
                            if total:
                                log_callback('info', f'Progress: {int(done / total * 100)}%')
                        sftp.put(
                            self.params['source_path'],
                            self.params['destination_path'],
                            callback=_progress,
                        )
                    log_callback('info', 'Transfer complete')
                    return
                except FileNotFoundError:
                    raise SFTPTransferError(f'SOURCE NOT FOUND: {self.params["source_path"]}')
                except OSError as e:
                    if 'No space' in str(e):
                        raise SFTPTransferError('INSUFFICIENT SPACE ON DESTINATION')
                    raise SFTPTransferError(f'TRANSFER ERROR — {e}')
            except paramiko.AuthenticationException:
                raise SFTPTransferError('AUTH FAILED — check credentials')
            except (socket.timeout, socket.gaierror) as e:
                last_error = str(e)
                if attempt < SFTP_MAX_RETRIES:
                    log_callback('warn', f'Connection failed, retrying in {SFTP_RETRY_DELAY}s...')
                    time.sleep(SFTP_RETRY_DELAY)
            except paramiko.SSHException as e:
                raise SFTPTransferError(f'SSH ERROR — {e}')
            finally:
                client.close()

        raise SFTPTransferError(f'CONNECTION TIMEOUT — {self.params["host"]} unreachable')
