import hashlib
import shlex
import subprocess


class ChecksumVerificationError(Exception):
    pass


def _local_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_sftp(source_path: str, ssh_client, remote_path: str, log_callback) -> None:
    local_hash = _local_sha256(source_path)
    _, stdout, stderr = ssh_client.exec_command(f'sha256sum {shlex.quote(remote_path)}')
    output = stdout.read().decode().strip()
    if not output:
        raise ChecksumVerificationError(f'sha256sum failed: {stderr.read().decode().strip()}')
    remote_hash = output.split()[0]
    if local_hash != remote_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: local={local_hash[:16]}... remote={remote_hash[:16]}...'
        )
    log_callback('info', f'SHA-256 OK: {local_hash[:16]}...')


def verify_rsync(source_path: str, ssh_cmd_prefix: list, remote_path: str, log_callback) -> None:
    local_hash = _local_sha256(source_path)
    cmd = ssh_cmd_prefix + [f'sha256sum {shlex.quote(remote_path)}']
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ChecksumVerificationError(f'sha256sum failed: {result.stderr.strip()}')
    remote_hash = result.stdout.strip().split()[0]
    if local_hash != remote_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: local={local_hash[:16]}... remote={remote_hash[:16]}...'
        )
    log_callback('info', f'SHA-256 OK: {local_hash[:16]}...')
