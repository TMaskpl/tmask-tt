import pytest
import paramiko
from unittest.mock import MagicMock, patch
from unittest import mock

from modules.sftp.handler import SFTPHandler, SFTPTransferError
from modules.sftp.config import SFTP_MAX_RETRIES, SFTP_RETRY_DELAY
from modules.checksum.handler import ChecksumVerificationError


class TestSFTPHandler:
    def test_auth_failure_raises_error(self, sftp_params):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_client.connect.side_effect = paramiko.AuthenticationException()
            handler = SFTPHandler(sftp_params)
            with pytest.raises(SFTPTransferError, match='AUTH FAILED'):
                handler.execute(log_callback=lambda lvl, msg: None)

    def test_successful_transfer_calls_sftp_put(self, sftp_params):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            handler = SFTPHandler(sftp_params)
            logs = []
            handler.execute(log_callback=lambda lvl, msg: logs.append((lvl, msg)))
            mock_sftp.put.assert_called_once_with(
                sftp_params['source_path'],
                sftp_params['destination_path'],
                callback=mock_sftp.put.call_args[1]['callback'],
            )
            assert any('Transfer complete' in msg for _, msg in logs)

    def test_source_not_found_raises_error(self, sftp_params):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_sftp.put.side_effect = FileNotFoundError('/data/file.tar')
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            handler = SFTPHandler(sftp_params)
            with pytest.raises(SFTPTransferError, match='SOURCE NOT FOUND'):
                handler.execute(log_callback=lambda lvl, msg: None)

    def test_connection_timeout_retries_and_raises(self, sftp_params):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.sftp.handler.time.sleep') as mock_sleep:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            import socket
            mock_client.connect.side_effect = socket.timeout('timed out')
            handler = SFTPHandler(sftp_params)
            with pytest.raises(SFTPTransferError, match='CONNECTION TIMEOUT'):
                handler.execute(log_callback=lambda lvl, msg: None)
            assert mock_client.connect.call_count == SFTP_MAX_RETRIES
            assert mock_sleep.call_count == SFTP_MAX_RETRIES - 1
            mock_sleep.assert_called_with(SFTP_RETRY_DELAY)

    def test_insufficient_space_raises_error(self, sftp_params):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_sftp.put.side_effect = OSError('No space left on device')
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            handler = SFTPHandler(sftp_params)
            with pytest.raises(SFTPTransferError, match='INSUFFICIENT SPACE'):
                handler.execute(log_callback=lambda lvl, msg: None)

    def test_logs_connection_and_auth_messages(self, sftp_params):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            handler = SFTPHandler(sftp_params)
            logs = []
            handler.execute(log_callback=lambda lvl, msg: logs.append((lvl, msg)))
            messages = [msg for _, msg in logs]
            assert any('Connecting to' in m for m in messages)
            assert any('Authentication OK' in m for m in messages)

    def _make_params(self, **kwargs):
        params = {
            'host': '192.168.1.10',
            'port': 22,
            'username': 'deploy',
            'password': 'secret',
            'ssh_key': None,
            'source_path': '/data/file.tar',
            'destination_path': '/backup/file.tar',
            'compress': False,
            'encrypt': False,
            'strict_host_key_checking': False,
            'known_host_key': None,
        }
        params.update(kwargs)
        return params

    def test_passphrase_without_encrypt_flag_still_encrypts(self, sftp_params):
        """Samo wpisanie hasła w formularzu wystarczy — flaga conn.encrypt nie jest wymagana."""
        sftp_params['encrypt'] = False
        sftp_params['gpg_passphrase'] = 'secret123'
        encrypted_tmp = '/tmp/file_abc.gpg'

        with patch('modules.sftp.handler.encrypt_file', return_value=encrypted_tmp) as mock_encrypt, \
             patch('modules.sftp.handler.os.path.exists', return_value=True), \
             patch('modules.sftp.handler.os.unlink'), \
             patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)

            SFTPHandler(sftp_params).execute(log_callback=lambda lvl, msg: None)

            mock_encrypt.assert_called_once()
            call_args = mock_sftp.put.call_args[0]
            assert call_args[1] == sftp_params['destination_path'] + '.gpg'

    def test_no_passphrase_skips_encryption(self, sftp_params):
        """Brak hasła → transfer bez szyfrowania, destination_path bez .gpg."""
        sftp_params['encrypt'] = True
        sftp_params['gpg_passphrase'] = None

        with patch('modules.sftp.handler.encrypt_file') as mock_encrypt, \
             patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)

            SFTPHandler(sftp_params).execute(log_callback=lambda lvl, msg: None)

            mock_encrypt.assert_not_called()
            call_args = mock_sftp.put.call_args[0]
            assert call_args[1] == sftp_params['destination_path']

    def test_execute_with_encrypt_uses_encrypted_paths(self, sftp_params):
        sftp_params['encrypt'] = True
        sftp_params['gpg_passphrase'] = 'secret123'
        encrypted_tmp = '/tmp/file_abc.gpg'

        with patch('modules.sftp.handler.encrypt_file', return_value=encrypted_tmp) as mock_encrypt, \
             patch('modules.sftp.handler.os.path.exists', return_value=True), \
             patch('modules.sftp.handler.os.unlink') as mock_unlink, \
             patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)

            SFTPHandler(sftp_params).execute(log_callback=lambda lvl, msg: None)

            mock_encrypt.assert_called_once_with(
                sftp_params['source_path'], sftp_params['gpg_passphrase']
            )
            mock_sftp.put.assert_called_once()
            call_args = mock_sftp.put.call_args[0]
            assert call_args[0] == encrypted_tmp
            assert call_args[1] == sftp_params['destination_path'] + '.gpg'
            mock_unlink.assert_called_once_with(encrypted_tmp)

    def test_cleanup_encrypted_file_even_on_transfer_error(self, sftp_params):
        sftp_params['encrypt'] = True
        sftp_params['gpg_passphrase'] = 'secret123'
        encrypted_tmp = '/tmp/file_abc.gpg'

        with patch('modules.sftp.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.sftp.handler.os.path.exists', return_value=True), \
             patch('modules.sftp.handler.os.unlink') as mock_unlink, \
             patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_sftp.put.side_effect = OSError('No space left on device')
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(SFTPTransferError):
                SFTPHandler(sftp_params).execute(log_callback=lambda lvl, msg: None)

            mock_unlink.assert_called_once_with(encrypted_tmp)

    def test_ssh_key_auth_path(self):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            with patch('modules.sftp.handler.paramiko.PKey') as _:
                handler = SFTPHandler(self._make_params(ssh_key='-----BEGIN RSA PRIVATE KEY-----\ntest\n-----END RSA PRIVATE KEY-----', password=None))
                handler.execute(log_callback=lambda lvl, msg: None)
            # connect was called with pkey kwarg (not password)
            call_kwargs = mock_client.connect.call_args[1]
            assert 'pkey' in call_kwargs
            assert 'password' not in call_kwargs

    def test_strict_mode_without_key_raises_config_error(self, sftp_params):
        sftp_params['strict_host_key_checking'] = True
        sftp_params['known_host_key'] = None
        with pytest.raises(SFTPTransferError, match='CONFIG ERROR'):
            SFTPHandler(sftp_params).execute(log_callback=lambda lvl, msg: None)

    def test_strict_mode_with_empty_key_raises_config_error(self, sftp_params):
        sftp_params['strict_host_key_checking'] = True
        sftp_params['known_host_key'] = ''
        with pytest.raises(SFTPTransferError, match='CONFIG ERROR'):
            SFTPHandler(sftp_params).execute(log_callback=lambda lvl, msg: None)

    def test_gpg_passphrase_never_appears_in_logs(self, sftp_params):
        sftp_params['encrypt'] = True
        sftp_params['gpg_passphrase'] = 'super_secret_passphrase'
        encrypted_tmp = '/tmp/file_abc.gpg'

        with patch('modules.sftp.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.sftp.handler.os.path.exists', return_value=True), \
             patch('modules.sftp.handler.os.unlink'), \
             patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)

            logs = []
            SFTPHandler(sftp_params).execute(log_callback=lambda lvl, msg: logs.append(msg))

            all_log_text = ' '.join(logs)
            assert 'super_secret_passphrase' not in all_log_text


class TestSFTPChecksumVerification:
    def _make_params(self, **kwargs):
        defaults = {
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
            'verify_checksum': False,
        }
        defaults.update(kwargs)
        return defaults

    def _make_mock_ssh(self):
        mock_client = MagicMock()
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
        mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
        return mock_client

    def test_calls_verify_sftp_after_transfer(self):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.sftp.handler.verify_sftp') as mock_verify:
            MockSSH.return_value = self._make_mock_ssh()
            SFTPHandler(self._make_params(verify_checksum=True)).execute(lambda lvl, msg: None)
        mock_verify.assert_called_once_with(
            '/data/file.tar',
            MockSSH.return_value,
            '/backup/file.tar',
            mock.ANY,
        )

    def test_skips_verify_when_disabled(self):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.sftp.handler.verify_sftp') as mock_verify:
            MockSSH.return_value = self._make_mock_ssh()
            SFTPHandler(self._make_params(verify_checksum=False)).execute(lambda lvl, msg: None)
        mock_verify.assert_not_called()

    def test_raises_transfer_error_on_mismatch(self):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.sftp.handler.verify_sftp',
                   side_effect=ChecksumVerificationError('SHA-256 MISMATCH')):
            MockSSH.return_value = self._make_mock_ssh()
            with pytest.raises(SFTPTransferError, match='MISMATCH'):
                SFTPHandler(self._make_params(verify_checksum=True)).execute(lambda lvl, msg: None)

    def test_skips_verify_when_gpg_enabled(self):
        encrypted_tmp = '/tmp/file_abc.gpg'
        logs = []
        with patch('modules.sftp.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.sftp.handler.os.path.exists', return_value=True), \
             patch('modules.sftp.handler.os.unlink'), \
             patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.sftp.handler.verify_sftp') as mock_verify:
            MockSSH.return_value = self._make_mock_ssh()
            SFTPHandler(self._make_params(
                encrypt=True, gpg_passphrase='secret', verify_checksum=True,
            )).execute(lambda lvl, msg: logs.append((lvl, msg)))
        mock_verify.assert_not_called()
        assert any('SHA-256' in msg and 'pomijane' in msg for _, msg in logs)
