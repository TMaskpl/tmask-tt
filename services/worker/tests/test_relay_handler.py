import io
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


class TestRelayHandler:
    def test_happy_path_small_file(self, relay_params):
        source_params, dest_params = relay_params
        fake_data = b'hello relay'

        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            mock_src_client = MagicMock()
            mock_dst_client = MagicMock()
            MockSSH.side_effect = [mock_src_client, mock_dst_client]

            mock_src_sftp = MagicMock()
            mock_dst_sftp = MagicMock()
            mock_src_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_src_sftp)
            mock_src_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            mock_dst_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_dst_sftp)
            mock_dst_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)

            mock_stat = MagicMock()
            mock_stat.st_size = 10
            mock_src_sftp.stat.return_value = mock_stat

            def fake_getfo(remote_path, buf):
                buf.write(fake_data)
            mock_src_sftp.getfo.side_effect = fake_getfo

            logs = []
            RelayHandler(source_params, dest_params).execute(log_callback=lambda l, m: logs.append((l, m)))

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
                RelayHandler(source_params, dest_params).execute(log_callback=lambda l, m: None)

    def test_dest_auth_failure_raises_dest_error(self, relay_params):
        source_params, dest_params = relay_params
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            mock_src_client = MagicMock()
            mock_dst_client = MagicMock()
            MockSSH.side_effect = [mock_src_client, mock_dst_client]

            mock_src_sftp = MagicMock()
            mock_src_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_src_sftp)
            mock_src_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            mock_stat = MagicMock()
            mock_stat.st_size = 5
            mock_src_sftp.stat.return_value = mock_stat
            mock_src_sftp.getfo.side_effect = lambda p, buf: buf.write(b'x')

            mock_dst_client.connect.side_effect = paramiko.AuthenticationException()
            with pytest.raises(RelayTransferError, match='DEST ERROR'):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda l, m: None)

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
                RelayHandler(source_params, dest_params).execute(log_callback=lambda l, m: None)

    def test_tempfile_cleaned_up_on_dest_error(self, relay_params):
        source_params, dest_params = relay_params
        large_size = 200 * 1024 * 1024  # 200 MB — exceeds threshold

        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.tempfile.NamedTemporaryFile') as MockTmp, \
             patch('modules.relay.handler.os.path.exists', return_value=True), \
             patch('modules.relay.handler.os.unlink') as mock_unlink:

            mock_src_client = MagicMock()
            mock_dst_client = MagicMock()
            MockSSH.side_effect = [mock_src_client, mock_dst_client]

            mock_src_sftp = MagicMock()
            mock_src_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_src_sftp)
            mock_src_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            mock_stat = MagicMock()
            mock_stat.st_size = large_size
            mock_src_sftp.stat.return_value = mock_stat

            fake_tmp = MagicMock()
            fake_tmp.name = '/tmp/relay_test_abc'
            MockTmp.return_value = fake_tmp

            mock_dst_client.connect.side_effect = paramiko.AuthenticationException()

            with pytest.raises(RelayTransferError):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda l, m: None)

            mock_unlink.assert_called_once_with('/tmp/relay_test_abc')
