import os
import shlex
import subprocess
import time
from typing import Callable

from .config import (
    RSYNC_BASE_FLAGS,
    RSYNC_COMPRESS_FLAG,
    RSYNC_MAX_RETRIES,
    RSYNC_RETRY_DELAY,
    RSYNC_TIMEOUT,
)
from modules.gpg.handler import encrypt_file, GPGEncryptError


class RsyncTransferError(Exception):
    pass


class RsyncHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_ssh_options(self) -> str:
        port = int(self.params['port'])
        if not (1 <= port <= 65535):
            raise ValueError(f'Invalid SSH port: {port}')
        opts = [f'-p {port}', '-o BatchMode=yes']
        if not self.params.get('strict_host_key_checking', True):
            opts.append('-o StrictHostKeyChecking=no')
        if self.params.get('ssh_key'):
            opts.append(f'-i {shlex.quote(self.params["ssh_key"])}')
        return ' '.join(opts)

    def _build_command(self, source_override=None, dest_override=None) -> list:
        source = source_override or self.params['source_path']
        dest = dest_override or self.params['destination_path']
        cmd = ['rsync'] + list(RSYNC_BASE_FLAGS)
        if self.params.get('compress'):
            cmd.append(RSYNC_COMPRESS_FLAG)
        ssh_opts = self._build_ssh_options()
        cmd += ['-e', f'ssh {ssh_opts}']
        cmd.append(source)
        cmd.append(f'{self.params["username"]}@{self.params["host"]}:{dest}')
        return cmd

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        use_gpg = self.params.get('encrypt') and self.params.get('gpg_passphrase')
        encrypted_path = None

        try:
            if use_gpg:
                log_callback('info', 'GPG: szyfrowanie pliku...')
                try:
                    encrypted_path = encrypt_file(
                        self.params['source_path'], self.params['gpg_passphrase']
                    )
                except GPGEncryptError as e:
                    raise RsyncTransferError(str(e))
                source = encrypted_path
                dest = self.params['destination_path'] + '.gpg'
            else:
                source = None
                dest = None

            cmd = self._build_command(source_override=source, dest_override=dest)
            last_exit_code = None

            for attempt in range(1, RSYNC_MAX_RETRIES + 1):
                log_callback('info', f'Starting rsync (attempt {attempt}): {" ".join(cmd)}')
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                output_lines = []
                try:
                    for line in proc.stdout:
                        line = line.rstrip()
                        output_lines.append(line)
                        if line:
                            log_callback('info', line)
                    last_exit_code = proc.wait()
                finally:
                    if hasattr(proc.stdout, 'close'):
                        proc.stdout.close()
                    proc.wait()
                full_output = '\n'.join(output_lines)

                if last_exit_code == 0:
                    log_callback('info', 'Transfer complete')
                    return

                if 'Permission denied' in full_output or last_exit_code == 255:
                    raise RsyncTransferError('AUTH FAILED — check credentials')
                if 'No space left' in full_output:
                    raise RsyncTransferError('INSUFFICIENT SPACE ON DESTINATION')
                if 'No such file' in full_output:
                    raise RsyncTransferError(f'SOURCE NOT FOUND: {self.params["source_path"]}')

                if attempt < RSYNC_MAX_RETRIES:
                    log_callback('warn', f'rsync failed (exit {last_exit_code}), retrying in {RSYNC_RETRY_DELAY}s...')
                    time.sleep(RSYNC_RETRY_DELAY)

            raise RsyncTransferError(
                f'TRANSFER FAILED — rsync failed after {RSYNC_MAX_RETRIES} attempts (last exit code: {last_exit_code})'
            )
        finally:
            if encrypted_path and os.path.exists(encrypted_path):
                os.unlink(encrypted_path)
