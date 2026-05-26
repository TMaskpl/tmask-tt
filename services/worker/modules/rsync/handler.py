import os
import shlex
import subprocess
import tempfile
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
from modules.checksum.handler import verify_rsync, ChecksumVerificationError


class RsyncTransferError(Exception):
    pass


class RsyncHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_ssh_options(self, known_hosts_path=None) -> str:
        port = int(self.params['port'])
        if not (1 <= port <= 65535):
            raise ValueError(f'Invalid SSH port: {port}')
        opts = [f'-p {port}', '-o BatchMode=yes']
        if self.params.get('strict_host_key_checking') and known_hosts_path:
            opts += [
                f'-o UserKnownHostsFile={shlex.quote(known_hosts_path)}',
                '-o StrictHostKeyChecking=yes',
            ]
        elif not self.params.get('strict_host_key_checking', True):
            opts.append('-o StrictHostKeyChecking=no')
        if self.params.get('ssh_key'):
            opts.append(f'-i {shlex.quote(self.params["ssh_key"])}')
        return ' '.join(opts)

    def _build_command(self, source_override=None, dest_override=None, known_hosts_path=None, dry_run: bool = False) -> list:
        source = source_override or self.params['source_path']
        dest = dest_override or self.params['destination_path']
        cmd = ['rsync'] + list(RSYNC_BASE_FLAGS)
        if self.params.get('compress'):
            cmd.append(RSYNC_COMPRESS_FLAG)
        if dry_run:
            cmd.append('--dry-run')
        ssh_opts = self._build_ssh_options(known_hosts_path=known_hosts_path)
        cmd += ['-e', f'ssh {ssh_opts}', '--']
        cmd.append(source)
        cmd.append(f'{self.params["username"]}@{self.params["host"]}:{dest}')
        return cmd

    def _build_ssh_cmd_prefix(self, known_hosts_path=None) -> list:
        port = int(self.params['port'])
        cmd = ['ssh', '-p', str(port), '-o', 'BatchMode=yes']
        if self.params.get('strict_host_key_checking') and known_hosts_path:
            cmd += ['-o', f'UserKnownHostsFile={known_hosts_path}',
                    '-o', 'StrictHostKeyChecking=yes']
        elif not self.params.get('strict_host_key_checking', True):
            cmd += ['-o', 'StrictHostKeyChecking=no']
        if self.params.get('ssh_key'):
            cmd += ['-i', self.params['ssh_key']]
        cmd.append(f'{self.params["username"]}@{self.params["host"]}')
        return cmd

    def _run_attempt(self, cmd: list, log_callback: Callable[[str, str], None]) -> tuple[int, str]:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        output_lines = []
        try:
            for line in proc.stdout:
                line = line.rstrip()
                output_lines.append(line)
                if line:
                    log_callback('info', line)
            return proc.wait(), '\n'.join(output_lines)
        finally:
            if hasattr(proc.stdout, 'close'):
                proc.stdout.close()
            proc.wait()

    def _check_rsync_output(self, exit_code: int, output: str) -> None:
        if exit_code == 0:
            return
        if 'Permission denied' in output or exit_code == 255:
            raise RsyncTransferError('AUTH FAILED — check credentials')
        if 'No space left' in output:
            raise RsyncTransferError('INSUFFICIENT SPACE ON DESTINATION')
        if 'No such file' in output:
            raise RsyncTransferError(f'SOURCE NOT FOUND: {self.params["source_path"]}')

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        use_gpg = self.params.get('encrypt') and self.params.get('gpg_passphrase')
        encrypted_path = None
        known_hosts_path = None

        try:
            if self.params.get('strict_host_key_checking') and self.params.get('known_host_key'):
                with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
                    f.write(self.params['known_host_key'])
                    known_hosts_path = f.name
            else:
                log_callback('warn', 'Host key verification DISABLED — connection is vulnerable to MITM')

            if use_gpg:
                log_callback('info', 'GPG: szyfrowanie pliku...')
                try:
                    encrypted_path = encrypt_file(self.params['source_path'], self.params['gpg_passphrase'])
                except GPGEncryptError as e:
                    raise RsyncTransferError(str(e))
                source_override = encrypted_path
                dest_override = self.params['destination_path'] + '.gpg'
            else:
                source_override = None
                dest_override = None

            if self.params.get('dry_run'):
                log_callback('info', 'Dry-run: sprawdzam transfer...')
                dry_cmd = self._build_command(
                    source_override=source_override,
                    dest_override=dest_override,
                    known_hosts_path=known_hosts_path,
                    dry_run=True,
                )
                exit_code, output = self._run_attempt(dry_cmd, log_callback)
                self._check_rsync_output(exit_code, output)
                if exit_code != 0:
                    raise RsyncTransferError(f'DRY-RUN FAILED (exit {exit_code}) — transfer anulowany')
                log_callback('info', 'Dry-run OK — kontynuuję transfer')

            cmd = self._build_command(
                source_override=source_override,
                dest_override=dest_override,
                known_hosts_path=known_hosts_path,
            )
            last_exit_code = None

            for attempt in range(1, RSYNC_MAX_RETRIES + 1):
                log_callback('info', f'Starting rsync (attempt {attempt}): {" ".join(cmd)}')
                last_exit_code, output = self._run_attempt(cmd, log_callback)
                self._check_rsync_output(last_exit_code, output)
                if last_exit_code == 0:
                    log_callback('info', 'Transfer complete')
                    if self.params.get('verify_checksum') and not use_gpg:
                        try:
                            ssh_prefix = self._build_ssh_cmd_prefix(known_hosts_path)
                            verify_rsync(
                                source_override or self.params['source_path'],
                                ssh_prefix,
                                dest_override or self.params['destination_path'],
                                log_callback,
                            )
                        except ChecksumVerificationError as e:
                            raise RsyncTransferError(str(e))
                    elif self.params.get('verify_checksum') and use_gpg:
                        log_callback('warn', 'SHA-256: pomijane — GPG włączone (encrypted file)')
                    return
                if attempt < RSYNC_MAX_RETRIES:
                    log_callback('warn', f'rsync failed (exit {last_exit_code}), retrying in {RSYNC_RETRY_DELAY}s...')
                    time.sleep(RSYNC_RETRY_DELAY)

            raise RsyncTransferError(
                f'TRANSFER FAILED — rsync failed after {RSYNC_MAX_RETRIES} attempts (last exit code: {last_exit_code})'
            )
        finally:
            if encrypted_path and os.path.exists(encrypted_path):
                os.unlink(encrypted_path)
            if known_hosts_path and os.path.exists(known_hosts_path):
                os.unlink(known_hosts_path)
