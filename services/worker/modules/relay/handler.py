import io
import os
import tempfile

import paramiko

from .config import RELAY_STREAM_THRESHOLD, RELAY_TEMP_DIR


class RelayTransferError(Exception):
    pass


class RelayHandler:
    def __init__(self, source_params: dict, dest_params: dict):
        self.source_params = source_params
        self.dest_params = dest_params

    def _build_client(self, params: dict) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        if params.get('strict_host_key_checking') and params.get('known_host_key'):
            with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
                f.write(params['known_host_key'])
                tmp_path = f.name
            try:
                client.load_host_keys(tmp_path)
            finally:
                os.unlink(tmp_path)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return client

    def _connect(self, client: paramiko.SSHClient, params: dict) -> None:
        connect_kwargs = {
            'hostname': params['host'],
            'port': params['port'],
            'username': params['username'],
            'timeout': 30,
            'look_for_keys': False,
            'allow_agent': False,
        }
        if params.get('ssh_key'):
            connect_kwargs['pkey'] = paramiko.PKey.from_private_key(
                io.StringIO(params['ssh_key'])
            )
        elif params.get('password'):
            connect_kwargs['password'] = params['password']
        client.connect(**connect_kwargs)

    def execute(self, log_callback) -> None:
        buf = None
        tmp_path = None

        source_client = self._build_client(self.source_params)
        try:
            log_callback('info', f'SOURCE: Connecting to {self.source_params["host"]}:{self.source_params["port"]}')
            try:
                self._connect(source_client, self.source_params)
            except paramiko.AuthenticationException:
                raise RelayTransferError('SOURCE ERROR — AUTH FAILED')
            except Exception as e:
                raise RelayTransferError(f'SOURCE ERROR — {e}')

            log_callback('info', f'SOURCE: Downloading {self.source_params["source_path"]}')
            try:
                with source_client.open_sftp() as sftp:
                    try:
                        size = sftp.stat(self.source_params['source_path']).st_size or 0
                    except FileNotFoundError:
                        raise RelayTransferError(
                            f'SOURCE ERROR — FILE NOT FOUND: {self.source_params["source_path"]}'
                        )
                    if size > RELAY_STREAM_THRESHOLD:
                        tmp = tempfile.NamedTemporaryFile(delete=False, dir=RELAY_TEMP_DIR)
                        tmp_path = tmp.name
                        tmp.close()
                        sftp.get(self.source_params['source_path'], tmp_path)
                        log_callback('info', f'SOURCE: Downloaded {size} bytes to tempfile')
                    else:
                        buf = io.BytesIO()
                        sftp.getfo(self.source_params['source_path'], buf)
                        buf.seek(0)
                        log_callback('info', f'SOURCE: Downloaded {buf.getbuffer().nbytes} bytes to buffer')
            except RelayTransferError:
                raise
            except OSError as e:
                raise RelayTransferError(f'SOURCE ERROR — {e}')
        finally:
            source_client.close()

        dest_client = self._build_client(self.dest_params)
        try:
            log_callback('info', f'DEST: Connecting to {self.dest_params["host"]}:{self.dest_params["port"]}')
            try:
                self._connect(dest_client, self.dest_params)
            except paramiko.AuthenticationException:
                raise RelayTransferError('DEST ERROR — AUTH FAILED')
            except Exception as e:
                raise RelayTransferError(f'DEST ERROR — {e}')

            log_callback('info', f'DEST: Uploading to {self.dest_params["destination_path"]}')
            try:
                with dest_client.open_sftp() as sftp:
                    if tmp_path:
                        sftp.put(tmp_path, self.dest_params['destination_path'])
                    else:
                        sftp.putfo(buf, self.dest_params['destination_path'])
            except RelayTransferError:
                raise
            except OSError as e:
                raise RelayTransferError(f'DEST ERROR — {e}')

            log_callback('info', 'RELAY: Transfer complete')
        finally:
            dest_client.close()
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
