import io
import os
import stat as stat_module
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

    def _transfer_file(self, src_sftp, dst_sftp, src_path: str, dst_path: str,
                       log_callback, file_stat=None) -> None:
        if file_stat is None:
            try:
                file_stat = src_sftp.stat(src_path)
            except FileNotFoundError:
                raise RelayTransferError(f'SOURCE ERROR — FILE NOT FOUND: {src_path}')
            except OSError as e:
                raise RelayTransferError(f'SOURCE ERROR — {e}')

        size = file_stat.st_size or 0
        tmp_path = None
        try:
            if size > RELAY_STREAM_THRESHOLD:
                tmp = tempfile.NamedTemporaryFile(delete=False, dir=RELAY_TEMP_DIR)
                tmp_path = tmp.name
                tmp.close()
                src_sftp.get(src_path, tmp_path)
                log_callback('info', f'{os.path.basename(src_path)}: {size} bytes (tempfile)')
                dst_sftp.put(tmp_path, dst_path)
            else:
                buf = io.BytesIO()
                src_sftp.getfo(src_path, buf)
                buf.seek(0)
                log_callback('info', f'{os.path.basename(src_path)}: {buf.getbuffer().nbytes} bytes')
                dst_sftp.putfo(buf, dst_path)
        except RelayTransferError:
            raise
        except OSError as e:
            raise RelayTransferError(f'DEST ERROR — {e}')
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _transfer_directory(self, src_sftp, dst_sftp, source_dir: str,
                             dest_dir: str, log_callback) -> int:
        try:
            entries = src_sftp.listdir_attr(source_dir)
        except IOError as e:
            raise RelayTransferError(f'SOURCE ERROR — cannot list {source_dir}: {e}')

        files = [e for e in entries if stat_module.S_ISREG(e.st_mode)]

        if not files:
            log_callback('info', f'Source directory is empty: {source_dir}')
            return 0

        log_callback('info', f'Found {len(files)} file(s) in {source_dir}')
        source_dir = source_dir.rstrip('/')
        dest_dir = dest_dir.rstrip('/')

        for i, entry in enumerate(files, 1):
            src_path = f'{source_dir}/{entry.filename}'
            dst_path = f'{dest_dir}/{entry.filename}'
            log_callback('info', f'[{i}/{len(files)}] {entry.filename}')
            self._transfer_file(src_sftp, dst_sftp, src_path, dst_path, log_callback,
                                file_stat=entry)

        return len(files)

    def execute(self, log_callback) -> None:
        source_client = self._build_client(self.source_params)
        dest_client = self._build_client(self.dest_params)

        try:
            log_callback('info', f'SOURCE: Connecting to {self.source_params["host"]}:{self.source_params["port"]}')
            try:
                self._connect(source_client, self.source_params)
            except paramiko.AuthenticationException:
                raise RelayTransferError('SOURCE ERROR — AUTH FAILED')
            except Exception as e:
                raise RelayTransferError(f'SOURCE ERROR — {e}')

            log_callback('info', f'DEST: Connecting to {self.dest_params["host"]}:{self.dest_params["port"]}')
            try:
                self._connect(dest_client, self.dest_params)
            except paramiko.AuthenticationException:
                raise RelayTransferError('DEST ERROR — AUTH FAILED')
            except Exception as e:
                raise RelayTransferError(f'DEST ERROR — {e}')

            with source_client.open_sftp() as src_sftp, dest_client.open_sftp() as dst_sftp:
                source_path = self.source_params['source_path']
                dest_path = self.dest_params['destination_path']

                try:
                    source_stat = src_sftp.stat(source_path)
                except FileNotFoundError:
                    raise RelayTransferError(f'SOURCE ERROR — FILE NOT FOUND: {source_path}')
                except OSError as e:
                    raise RelayTransferError(f'SOURCE ERROR — {e}')

                if stat_module.S_ISDIR(source_stat.st_mode):
                    count = self._transfer_directory(
                        src_sftp, dst_sftp, source_path, dest_path, log_callback
                    )
                    log_callback('info', f'RELAY: {count} file(s) transferred')
                else:
                    self._transfer_file(
                        src_sftp, dst_sftp, source_path, dest_path, log_callback,
                        file_stat=source_stat,
                    )
                    log_callback('info', 'RELAY: Transfer complete')

        finally:
            source_client.close()
            dest_client.close()
