import os
import subprocess  # nosec B404
import tempfile
from pathlib import Path

from .config import GPG_CIPHER_ALGO, GPG_TIMEOUT


class GPGEncryptError(Exception):
    pass


def encrypt_file(source_path: str, passphrase: str) -> str:
    stem = Path(source_path).stem
    fd, encrypted_path = tempfile.mkstemp(suffix='.gpg', prefix=f'{stem}_')
    os.close(fd)
    success = False
    try:
        with tempfile.TemporaryDirectory() as gnupg_home:
            result = subprocess.run(  # nosec B603 B607 — gpg called with fixed args; passphrase via stdin fd, no shell
                [
                    'gpg', '--batch', '--yes', '--symmetric',
                    '--homedir', gnupg_home,
                    '--cipher-algo', GPG_CIPHER_ALGO,
                    '--passphrase-fd', '0',
                    '--output', encrypted_path,
                    source_path,
                ],
                input=passphrase,
                capture_output=True,
                text=True,
                timeout=GPG_TIMEOUT,
            )
        if result.returncode != 0:
            raise GPGEncryptError(f'GPG FAILED — {result.stderr.strip()}')
        success = True
        return encrypted_path
    except GPGEncryptError:
        raise
    except subprocess.TimeoutExpired:
        raise GPGEncryptError('GPG TIMEOUT — encryption took too long')
    except FileNotFoundError:
        raise GPGEncryptError('GPG NOT INSTALLED — install gnupg package')
    except Exception as e:
        raise GPGEncryptError(f'GPG ERROR — {e}')
    finally:
        if not success and os.path.exists(encrypted_path):
            os.unlink(encrypted_path)
