import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from modules.ssh_keys import load_private_key


def _rsa_key_str(password=None) -> str:
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encryption = (
        serialization.BestAvailableEncryption(password.encode()) if password
        else serialization.NoEncryption()
    )
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=encryption,
    )
    return pem.decode()


def _ed25519_key_str(password=None) -> str:
    priv = ed25519.Ed25519PrivateKey.generate()
    encryption = (
        serialization.BestAvailableEncryption(password.encode()) if password
        else serialization.NoEncryption()
    )
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=encryption,
    )
    return pem.decode()


class TestLoadPrivateKey:
    def test_loads_unencrypted_rsa_key(self):
        key = load_private_key(_rsa_key_str())
        assert isinstance(key, paramiko.RSAKey)

    def test_loads_unencrypted_ed25519_key(self):
        key = load_private_key(_ed25519_key_str())
        assert isinstance(key, paramiko.Ed25519Key)

    def test_loads_rsa_key_with_correct_passphrase(self):
        key = load_private_key(_rsa_key_str(password='correct-horse'), 'correct-horse')
        assert isinstance(key, paramiko.RSAKey)

    def test_loads_ed25519_key_with_correct_passphrase(self):
        key = load_private_key(_ed25519_key_str(password='correct-horse'), 'correct-horse')
        assert isinstance(key, paramiko.Ed25519Key)

    def test_wrong_passphrase_raises_ssh_exception(self):
        key_str = _rsa_key_str(password='correct-horse')
        with pytest.raises(paramiko.SSHException):
            load_private_key(key_str, 'wrong-password')

    def test_encrypted_key_without_passphrase_raises(self):
        key_str = _rsa_key_str(password='correct-horse')
        with pytest.raises(paramiko.SSHException):
            load_private_key(key_str)

    def test_garbage_input_raises_ssh_exception(self):
        with pytest.raises(paramiko.SSHException):
            load_private_key('not a real key')
