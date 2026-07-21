import os
import re
import shlex
import subprocess  # nosec B404
import tempfile
import time
from typing import Callable

import paramiko

from .config import (
    RSYNC_BASE_FLAGS,
    RSYNC_COMPRESS_FLAG,
    RSYNC_MAX_RETRIES,
    RSYNC_RETRY_DELAY,
)
from modules.gpg.handler import encrypt_file, GPGEncryptError
from modules.ssh_keys import load_private_key
from modules.checksum.handler import verify_rsync, ChecksumVerificationError


class RsyncTransferError(Exception):
    pass


HOST_KEY_WARNING = 'Host key verification DISABLED — connection is vulnerable to MITM'

# rsync --info=progress2 emits lines like:
#       1,234,567  45%   12.34MB/s    0:00:03
# These update in place on a real TTY; over a pipe each shows up as its own line.
PROGRESS_LINE_RE = re.compile(r'^\s*[\d,]+\s+(\d{1,3})%\s+\S+/s\s')


class RsyncHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_ssh_options(self, known_hosts_path=None, ssh_key_path=None) -> str:
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
        if ssh_key_path:
            opts.append(f'-i {shlex.quote(ssh_key_path)}')
        return ' '.join(opts)

    def _build_command(self, source_override=None, dest_override=None, known_hosts_path=None,
                        ssh_key_path=None, dry_run: bool = False) -> list:
        source = source_override or self.params['source_path']
        dest = dest_override or self.params['destination_path']
        cmd = ['rsync'] + list(RSYNC_BASE_FLAGS)
        if self.params.get('compress'):
            cmd.append(RSYNC_COMPRESS_FLAG)
        if dry_run:
            cmd.append('--dry-run')
        ssh_opts = self._build_ssh_options(known_hosts_path=known_hosts_path, ssh_key_path=ssh_key_path)
        cmd += ['-e', f'ssh {ssh_opts}', '--']
        cmd.append(source)
        cmd.append(f'{self.params["username"]}@{self.params["host"]}:{dest}')
        return cmd

    def _build_ssh_cmd_prefix(self, known_hosts_path=None, ssh_key_path=None) -> list:
        port = int(self.params['port'])
        if not (1 <= port <= 65535):
            raise ValueError(f'Invalid port: {port}')
        cmd = ['ssh', '-p', str(port), '-o', 'BatchMode=yes']
        if self.params.get('strict_host_key_checking') and known_hosts_path:
            cmd += ['-o', f'UserKnownHostsFile={known_hosts_path}',
                    '-o', 'StrictHostKeyChecking=yes']
        elif not self.params.get('strict_host_key_checking', True):
            cmd += ['-o', 'StrictHostKeyChecking=no']
        if ssh_key_path:
            cmd += ['-i', ssh_key_path]
        cmd.append(f'{self.params["username"]}@{self.params["host"]}')
        return cmd

    def _run_attempt(self, cmd: list, log_callback: Callable[[str, str], None],
                      progress_callback: Callable[[int], None] = None) -> tuple[int, str]:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)  # nosec B603 — cmd built from validated SSH/rsync params + shlex.quote
        output_lines = []
        try:
            for line in proc.stdout:
                line = line.rstrip()
                output_lines.append(line)
                if not line:
                    continue
                match = PROGRESS_LINE_RE.match(line)
                if match:
                    if progress_callback:
                        progress_callback(int(match.group(1)))
                else:
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

    def _setup_known_hosts(self, log_callback: Callable[[str, str], None]):
        if self.params.get('strict_host_key_checking') and self.params.get('known_host_key'):
            with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
                f.write(self.params['known_host_key'])
                return f.name
        log_callback('warn', HOST_KEY_WARNING)
        return None

    def _setup_ssh_key(self):
        """Writes the (possibly passphrase-protected) private key to a mode-600
        tempfile without a passphrase, since the ssh CLI (rsync -e) can't be fed
        a passphrase non-interactively. Returns the path, or None if no key is
        configured. Raises RsyncTransferError on an invalid key/passphrase."""
        raw_key = self.params.get('ssh_key')
        if not raw_key:
            return None
        passphrase = self.params.get('ssh_key_passphrase') or None
        try:
            pkey = load_private_key(raw_key, passphrase)
        except paramiko.SSHException as e:
            raise RsyncTransferError(f'SSH KEY ERROR — {e}')
        fd, path = tempfile.mkstemp(suffix='_ssh_key')
        os.close(fd)
        os.chmod(path, 0o600)
        with open(path, 'w') as f:
            pkey.write_private_key(f)
        return path

    def _encrypt_source_if_needed(self, log_callback: Callable[[str, str], None]):
        """Returns (use_gpg, source_override, dest_override, encrypted_path). May raise GPGEncryptError."""
        if not (self.params.get('encrypt') and self.params.get('gpg_passphrase')):
            return False, None, None, None
        log_callback('info', 'GPG: szyfrowanie pliku...')
        encrypted_path = encrypt_file(self.params['source_path'], self.params['gpg_passphrase'])
        dest_override = self.params['destination_path'] + '.gpg'
        return True, encrypted_path, dest_override, encrypted_path

    def _run_dry_run_precheck(self, source_override, dest_override, known_hosts_path, ssh_key_path, log_callback) -> None:
        log_callback('info', 'Dry-run: sprawdzam transfer...')
        dry_cmd = self._build_command(
            source_override=source_override,
            dest_override=dest_override,
            known_hosts_path=known_hosts_path,
            ssh_key_path=ssh_key_path,
            dry_run=True,
        )
        exit_code, output = self._run_attempt(dry_cmd, log_callback)
        self._check_rsync_output(exit_code, output)
        if exit_code != 0:
            raise RsyncTransferError(f'DRY-RUN FAILED (exit {exit_code}) — transfer anulowany')
        log_callback('info', 'Dry-run OK — kontynuuję transfer')

    def _verify_checksum_if_needed(self, use_gpg, source_override, dest_override, known_hosts_path, ssh_key_path, log_callback) -> None:
        if not self.params.get('verify_checksum'):
            return
        if use_gpg:
            log_callback('warn', 'SHA-256: pomijane — GPG włączone (encrypted file)')
            return
        try:
            ssh_prefix = self._build_ssh_cmd_prefix(known_hosts_path, ssh_key_path=ssh_key_path)
            verify_rsync(
                source_override or self.params['source_path'],
                ssh_prefix,
                dest_override or self.params['destination_path'],
                log_callback,
            )
        except ChecksumVerificationError as e:
            raise RsyncTransferError(str(e))

    def _transfer_with_retries(self, cmd, log_callback: Callable[[str, str], None],
                                progress_callback: Callable[[int], None] = None) -> None:
        last_exit_code = None
        for attempt in range(1, RSYNC_MAX_RETRIES + 1):
            log_callback('info', f'Starting rsync (attempt {attempt}): {" ".join(cmd)}')
            last_exit_code, output = self._run_attempt(cmd, log_callback, progress_callback=progress_callback)
            self._check_rsync_output(last_exit_code, output)
            if last_exit_code == 0:
                log_callback('info', 'Transfer complete')
                return
            if attempt < RSYNC_MAX_RETRIES:
                log_callback('warn', f'rsync failed (exit {last_exit_code}), retrying in {RSYNC_RETRY_DELAY}s...')
                time.sleep(RSYNC_RETRY_DELAY)
        raise RsyncTransferError(
            f'TRANSFER FAILED — rsync failed after {RSYNC_MAX_RETRIES} attempts (last exit code: {last_exit_code})'
        )

    def execute(self, log_callback: Callable[[str, str], None],
                progress_callback: Callable[[int], None] = None) -> None:
        encrypted_path = None
        known_hosts_path = None
        ssh_key_path = None

        try:
            known_hosts_path = self._setup_known_hosts(log_callback)
            ssh_key_path = self._setup_ssh_key()
            try:
                use_gpg, source_override, dest_override, encrypted_path = self._encrypt_source_if_needed(log_callback)
            except GPGEncryptError as e:
                raise RsyncTransferError(str(e))

            if self.params.get('dry_run'):
                self._run_dry_run_precheck(source_override, dest_override, known_hosts_path, ssh_key_path, log_callback)

            cmd = self._build_command(
                source_override=source_override,
                dest_override=dest_override,
                known_hosts_path=known_hosts_path,
                ssh_key_path=ssh_key_path,
            )
            self._transfer_with_retries(cmd, log_callback, progress_callback=progress_callback)
            self._verify_checksum_if_needed(
                use_gpg, source_override, dest_override, known_hosts_path, ssh_key_path, log_callback
            )
        finally:
            if encrypted_path and os.path.exists(encrypted_path):
                os.unlink(encrypted_path)
            if known_hosts_path and os.path.exists(known_hosts_path):
                os.unlink(known_hosts_path)
            if ssh_key_path and os.path.exists(ssh_key_path):
                os.unlink(ssh_key_path)

    def preview(self, log_callback: Callable[[str, str], None]) -> dict:
        encrypted_path = None
        known_hosts_path = None
        ssh_key_path = None

        try:
            known_hosts_path = self._setup_known_hosts(log_callback)
            warning_prefix = '' if known_hosts_path else HOST_KEY_WARNING + '\n'

            try:
                ssh_key_path = self._setup_ssh_key()
            except RsyncTransferError as e:
                return {'exit_code': None, 'output': warning_prefix + str(e)}

            try:
                _, source_override, dest_override, encrypted_path = self._encrypt_source_if_needed(log_callback)
            except GPGEncryptError as e:
                return {'exit_code': None, 'output': warning_prefix + f'GPG ENCRYPTION FAILED: {e}'}

            dry_cmd = self._build_command(
                source_override=source_override,
                dest_override=dest_override,
                known_hosts_path=known_hosts_path,
                ssh_key_path=ssh_key_path,
                dry_run=True,
            )
            exit_code, output = self._run_attempt(dry_cmd, log_callback)
            return {'exit_code': exit_code, 'output': warning_prefix + output}
        finally:
            if encrypted_path and os.path.exists(encrypted_path):
                os.unlink(encrypted_path)
            if known_hosts_path and os.path.exists(known_hosts_path):
                os.unlink(known_hosts_path)
            if ssh_key_path and os.path.exists(ssh_key_path):
                os.unlink(ssh_key_path)
