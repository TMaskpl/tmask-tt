import stat as stat_module
import pytest
import paramiko
from unittest.mock import MagicMock, patch

from modules.relay.handler import RelayHandler, RelayTransferError


@pytest.fixture
def relay_params():
    source = {
        'host': '10.0.0.1', 'port': 22, 'username': 'src_user',
        'password': 'secret', 'ssh_key': None,
        'source_path': '/data/file.tar',
        'strict_host_key_checking': False, 'known_host_key': None,
    }
    dest = {
        'host': '10.0.0.2', 'port': 22, 'username': 'dst_user',
        'password': 'secret', 'ssh_key': None,
        'destination_path': '/backup/file.tar',
        'strict_host_key_checking': False, 'known_host_key': None,
    }
    return source, dest


def _setup_two_clients(MockSSH):
    mock_src_client = MagicMock()
    mock_dst_client = MagicMock()
    MockSSH.side_effect = [mock_src_client, mock_dst_client]

    mock_src_sftp = MagicMock()
    mock_dst_sftp = MagicMock()
    mock_src_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_src_sftp)
    mock_src_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
    mock_dst_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_dst_sftp)
    mock_dst_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)

    return mock_src_client, mock_dst_client, mock_src_sftp, mock_dst_sftp


def _file_stat(size=10):
    s = MagicMock()
    s.st_mode = stat_module.S_IFREG
    s.st_size = size
    return s


def _dir_stat():
    s = MagicMock()
    s.st_mode = stat_module.S_IFDIR
    return s


class TestRelayHandler:
    def test_happy_path_small_file(self, relay_params):
        source_params, dest_params = relay_params
        fake_data = b'hello relay'

        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            _, _, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)

            mock_src_sftp.stat.return_value = _file_stat(size=len(fake_data))

            def fake_getfo(remote_path, buf):
                buf.write(fake_data)
            mock_src_sftp.getfo.side_effect = fake_getfo

            logs = []
            RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: logs.append((level, m)))

            mock_src_sftp.getfo.assert_called_once()
            mock_dst_sftp.putfo.assert_called_once()
            assert any('Transfer complete' in msg for _, msg in logs)

    def test_source_auth_failure_raises_source_error(self, relay_params):
        source_params, dest_params = relay_params
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            mock_src_client = MagicMock()
            MockSSH.return_value = mock_src_client
            mock_src_client.connect.side_effect = paramiko.AuthenticationException()
            with pytest.raises(RelayTransferError, match='SOURCE ERROR'):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: None)

    def test_dest_auth_failure_raises_dest_error(self, relay_params):
        source_params, dest_params = relay_params
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            mock_src_client = MagicMock()
            mock_dst_client = MagicMock()
            MockSSH.side_effect = [mock_src_client, mock_dst_client]
            mock_dst_client.connect.side_effect = paramiko.AuthenticationException()
            with pytest.raises(RelayTransferError, match='DEST ERROR'):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: None)

    def test_source_file_not_found_raises_error(self, relay_params):
        source_params, dest_params = relay_params
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            mock_src_client = MagicMock()
            MockSSH.return_value = mock_src_client
            mock_src_sftp = MagicMock()
            mock_src_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_src_sftp)
            mock_src_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            mock_src_sftp.stat.side_effect = FileNotFoundError('/data/file.tar')
            with pytest.raises(RelayTransferError, match='SOURCE ERROR — FILE NOT FOUND'):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: None)

    def test_tempfile_cleaned_up_on_dest_error(self, relay_params):
        source_params, dest_params = relay_params
        large_size = 200 * 1024 * 1024  # 200 MB — exceeds threshold

        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.tempfile.NamedTemporaryFile') as MockTmp, \
             patch('modules.relay.handler.os.path.exists', return_value=True), \
             patch('modules.relay.handler.os.unlink') as mock_unlink:

            _, _, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)

            mock_src_sftp.stat.return_value = _file_stat(size=large_size)

            fake_tmp = MagicMock()
            fake_tmp.name = '/tmp/relay_test_abc'
            MockTmp.return_value = fake_tmp

            mock_dst_sftp.put.side_effect = OSError('No space left on device')

            with pytest.raises(RelayTransferError):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: None)

            mock_unlink.assert_called_once_with('/tmp/relay_test_abc')

    def test_verify_called_when_enabled(self, relay_params):
        relay_params[0]['verify_checksum'] = True
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.verify_relay') as mock_verify:
            mock_src_client, mock_dst_client, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)
            mock_src_sftp.stat.return_value = _file_stat(size=10)
            from modules.relay.handler import RelayHandler
            RelayHandler(*relay_params).execute(log_callback=lambda lvl, msg: None)
            mock_verify.assert_called_once()

    def test_verify_skipped_when_disabled(self, relay_params):
        relay_params[0]['verify_checksum'] = False
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.verify_relay') as mock_verify:
            mock_src_client, mock_dst_client, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)
            mock_src_sftp.stat.return_value = _file_stat(size=10)
            from modules.relay.handler import RelayHandler
            RelayHandler(*relay_params).execute(log_callback=lambda lvl, msg: None)
            mock_verify.assert_not_called()

    def test_mismatch_raises_relay_error_single_file(self, relay_params):
        relay_params[0]['verify_checksum'] = True
        from modules.checksum.handler import ChecksumVerificationError
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.verify_relay',
                   side_effect=ChecksumVerificationError('SHA-256 MISMATCH: ...')):
            mock_src_client, mock_dst_client, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)
            mock_src_sftp.stat.return_value = _file_stat(size=10)
            from modules.relay.handler import RelayHandler, RelayTransferError
            with pytest.raises(RelayTransferError, match="MISMATCH"):
                RelayHandler(*relay_params).execute(log_callback=lambda lvl, msg: None)

    def test_mismatch_directory_fail_fast(self, relay_params):
        relay_params[0]['verify_checksum'] = True
        from modules.checksum.handler import ChecksumVerificationError
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.verify_relay',
                   side_effect=ChecksumVerificationError('SHA-256 MISMATCH: ...')):
            mock_src_client, mock_dst_client, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)
            # źródło to katalog z 3 plikami
            mock_src_sftp.stat.return_value = _dir_stat()
            entries = []
            for i in range(3):
                e = _file_stat(size=10)
                e.filename = f'file{i}.bin'
                entries.append(e)
            mock_src_sftp.listdir_attr.return_value = entries
            from modules.relay.handler import RelayHandler, RelayTransferError
            with pytest.raises(RelayTransferError, match="MISMATCH"):
                RelayHandler(*relay_params).execute(log_callback=lambda lvl, msg: None)
            # fail-fast: tylko pierwszy plik przesłany przed przerwaniem
            assert mock_dst_sftp.putfo.call_count + mock_dst_sftp.put.call_count == 1


class TestRelayHandlerStrictMode:
    def test_strict_mode_without_key_raises_config_error(self, relay_params):
        source_params, dest_params = relay_params
        source_params['strict_host_key_checking'] = True
        source_params['known_host_key'] = None
        with pytest.raises(RelayTransferError, match='CONFIG ERROR'):
            RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: None)

    def test_strict_mode_with_empty_key_raises_config_error(self, relay_params):
        source_params, dest_params = relay_params
        source_params['strict_host_key_checking'] = True
        source_params['known_host_key'] = ''
        with pytest.raises(RelayTransferError, match='CONFIG ERROR'):
            RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: None)

    def test_strict_mode_dest_without_key_raises_config_error(self, relay_params):
        source_params, dest_params = relay_params
        dest_params['strict_host_key_checking'] = True
        dest_params['known_host_key'] = None
        with pytest.raises(RelayTransferError, match='CONFIG ERROR'):
            RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: None)


class TestRelayHandlerDirectory:
    def test_directory_transfers_all_files(self, relay_params):
        source_params, dest_params = relay_params
        source_params['source_path'] = '/data/dir'
        dest_params['destination_path'] = '/backup/dir'

        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            _, _, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)

            mock_src_sftp.stat.return_value = _dir_stat()

            file1 = MagicMock()
            file1.filename = 'a.txt'
            file1.st_mode = stat_module.S_IFREG
            file1.st_size = 5

            file2 = MagicMock()
            file2.filename = 'b.txt'
            file2.st_mode = stat_module.S_IFREG
            file2.st_size = 7

            mock_src_sftp.listdir_attr.return_value = [file1, file2]
            mock_src_sftp.getfo.side_effect = lambda path, buf: buf.write(b'x')

            logs = []
            RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: logs.append((level, m)))

            assert mock_src_sftp.getfo.call_count == 2
            assert mock_dst_sftp.putfo.call_count == 2
            assert any('2 file(s)' in msg for _, msg in logs)

        mock_src_sftp.listdir_attr.assert_called_once_with('/data/dir')

    def test_directory_skips_subdirectories(self, relay_params):
        source_params, dest_params = relay_params
        source_params['source_path'] = '/data/dir'
        dest_params['destination_path'] = '/backup/dir'

        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            _, _, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)

            mock_src_sftp.stat.return_value = _dir_stat()

            file1 = MagicMock()
            file1.filename = 'file.txt'
            file1.st_mode = stat_module.S_IFREG
            file1.st_size = 3

            subdir = MagicMock()
            subdir.filename = 'subdir'
            subdir.st_mode = stat_module.S_IFDIR
            subdir.st_size = 0

            mock_src_sftp.listdir_attr.return_value = [file1, subdir]
            mock_src_sftp.getfo.side_effect = lambda path, buf: buf.write(b'x')

            logs = []
            RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: logs.append((level, m)))

            assert mock_src_sftp.getfo.call_count == 1
            assert mock_dst_sftp.putfo.call_count == 1
            assert any('1 file(s)' in msg for _, msg in logs)

    def test_empty_directory_no_transfer(self, relay_params):
        source_params, dest_params = relay_params
        source_params['source_path'] = '/data/empty'

        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            _, _, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)

            mock_src_sftp.stat.return_value = _dir_stat()
            mock_src_sftp.listdir_attr.return_value = []

            logs = []
            RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: logs.append((level, m)))

            mock_src_sftp.getfo.assert_not_called()
            mock_dst_sftp.putfo.assert_not_called()
            assert any('empty' in msg.lower() for _, msg in logs)

    def test_directory_listdir_failure_raises_error(self, relay_params):
        source_params, dest_params = relay_params
        source_params['source_path'] = '/data/dir'

        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            _, _, mock_src_sftp, _ = _setup_two_clients(MockSSH)

            mock_src_sftp.stat.return_value = _dir_stat()
            mock_src_sftp.listdir_attr.side_effect = IOError('Permission denied')

            with pytest.raises(RelayTransferError, match='SOURCE ERROR'):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda level, m: None)
