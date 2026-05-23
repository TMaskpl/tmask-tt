import pytest


@pytest.fixture
def sftp_params():
    return {
        'host': '192.168.1.10',
        'port': 22,
        'username': 'deploy',
        'password': 'secret',
        'ssh_key': None,
        'source_path': '/data/file.tar',
        'destination_path': '/backup/file.tar',
        'compress': False,
        'encrypt': False,
        'gpg_passphrase': None,
        'strict_host_key_checking': False,
        'known_host_key': None,
    }


@pytest.fixture
def rsync_params():
    return {
        'host': '192.168.1.10',
        'port': 22,
        'username': 'deploy',
        'password': None,
        'ssh_key': '/tmp/id_rsa',
        'source_path': '/data/',
        'destination_path': '/backup/',
        'compress': False,
        'encrypt': False,
        'gpg_passphrase': None,
        'strict_host_key_checking': False,
        'known_host_key': None,
    }
