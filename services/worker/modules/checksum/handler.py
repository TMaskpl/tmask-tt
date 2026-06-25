import hashlib
import shlex
import subprocess  # nosec B404


CHECKSUM_TIMEOUT = 30


class ChecksumVerificationError(Exception):
    pass


def _local_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _remote_sha256(ssh_client, remote_path: str) -> str:
    _stdin, stdout, stderr = ssh_client.exec_command(f'sha256sum {shlex.quote(remote_path)}')
    output = stdout.read().decode().strip()
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0 or not output:
        raise ChecksumVerificationError(f'sha256sum failed: {stderr.read().decode().strip()}')
    return output.split()[0]


def verify_sftp(source_path: str, ssh_client, remote_path: str, log_callback) -> None:
    local_hash = _local_sha256(source_path)
    remote_hash = _remote_sha256(ssh_client, remote_path)
    if local_hash != remote_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: local={local_hash[:16]}... remote={remote_hash[:16]}...'
        )
    log_callback('info', f'SHA-256 OK: {local_hash[:16]}...')


def verify_relay(src_client, src_path: str, dst_client, dst_path: str, log_callback) -> None:
    src_hash = _remote_sha256(src_client, src_path)
    dst_hash = _remote_sha256(dst_client, dst_path)
    if src_hash != dst_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: source={src_hash[:16]}... dest={dst_hash[:16]}...'
        )
    log_callback('info', f'SHA-256 OK: {src_hash[:16]}...')


def verify_rsync(source_path: str, ssh_cmd_prefix: list, remote_path: str, log_callback) -> None:
    local_hash = _local_sha256(source_path)
    cmd = ssh_cmd_prefix + [f'sha256sum {shlex.quote(remote_path)}']
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=CHECKSUM_TIMEOUT)  # nosec B603 — cmd built from validated SSH params + shlex.quote
    if result.returncode != 0:
        raise ChecksumVerificationError(f'sha256sum failed: {result.stderr.strip()}')
    parts = result.stdout.strip().split()
    if not parts:
        raise ChecksumVerificationError('sha256sum failed: empty output')
    remote_hash = parts[0]
    if local_hash != remote_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: local={local_hash[:16]}... remote={remote_hash[:16]}...'
        )
    log_callback('info', f'SHA-256 OK: {local_hash[:16]}...')
