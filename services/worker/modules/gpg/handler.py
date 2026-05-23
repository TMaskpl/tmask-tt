# services/worker/modules/gpg/handler.py
import os
import subprocess
import tempfile
from pathlib import Path

from .config import GPG_CIPHER_ALGO, GPG_TIMEOUT


class GPGEncryptError(Exception):
    pass


def encrypt_file(source_path: str, passphrase: str) -> str:
    """
    Szyfruje plik symetrycznie AES-256 przez GPG CLI.
    Zwraca ścieżkę do zaszyfrowanego pliku tymczasowego.
    Caller odpowiada za os.unlink() zwróconej ścieżki.
    Rzuca GPGEncryptError przy każdym błędzie i czyści temp plik.
    """
    stem = Path(source_path).stem
    fd, encrypted_path = tempfile.mkstemp(suffix='.gpg', prefix=f'{stem}_')
    os.close(fd)
    try:
        result = subprocess.run(
            [
                'gpg', '--batch', '--yes', '--symmetric',
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
        return encrypted_path
    except GPGEncryptError:
        os.unlink(encrypted_path)
        raise
    except subprocess.TimeoutExpired:
        os.unlink(encrypted_path)
        raise GPGEncryptError('GPG TIMEOUT — encryption took too long')
    except FileNotFoundError:
        os.unlink(encrypted_path)
        raise GPGEncryptError('GPG NOT INSTALLED — install gnupg package')
    except Exception as e:
        os.unlink(encrypted_path)
        raise GPGEncryptError(f'GPG ERROR — {e}')
