import pytest
from unittest.mock import patch, MagicMock

from modules.rsync.handler import RsyncHandler, RsyncTransferError
from modules.rsync.config import RSYNC_MAX_RETRIES, RSYNC_RETRY_DELAY


class TestRsyncHandler:
    def _make_params(self, **kwargs):
        defaults = {
            'host': '192.168.1.10',
            'port': 22,
            'username': 'deploy',
            'password': None,
            'ssh_key': '/tmp/id_rsa',
            'source_path': '/data/',
            'destination_path': '/backup/',
            'compress': False,
            'encrypt': False,
            'strict_host_key_checking': False,
            'known_host_key': None,
        }
        defaults.update(kwargs)
        return defaults

    def test_builds_correct_rsync_command(self):
        handler = RsyncHandler(self._make_params())
        cmd = handler._build_command()
        assert cmd[0] == 'rsync'
        assert '-av' in cmd
        assert '--progress' in cmd
        dest = f'{self._make_params()["username"]}@{self._make_params()["host"]}:{self._make_params()["destination_path"]}'
        assert dest in cmd

    def test_compress_flag_added_when_enabled(self):
        handler = RsyncHandler(self._make_params(compress=True))
        cmd = handler._build_command()
        assert '--compress' in cmd

    def test_compress_flag_not_added_when_disabled(self):
        handler = RsyncHandler(self._make_params(compress=False))
        cmd = handler._build_command()
        assert '--compress' not in cmd

    def test_ssh_key_included_in_ssh_options(self):
        handler = RsyncHandler(self._make_params(ssh_key='/tmp/key.pem'))
        opts = handler._build_ssh_options()
        assert '-i /tmp/key.pem' in opts

    def test_auth_failure_raises_error(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['Permission denied (publickey).\n'])
            mock_proc.wait.return_value = 255
            MockPopen.return_value = mock_proc
            handler = RsyncHandler(self._make_params())
            with pytest.raises(RsyncTransferError, match='AUTH FAILED'):
                handler.execute(log_callback=lambda lvl, msg: None)

    def test_successful_rsync(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['sending incremental file list\n', 'file.tar\n'])
            mock_proc.wait.return_value = 0
            MockPopen.return_value = mock_proc
            handler = RsyncHandler(self._make_params())
            logs = []
            handler.execute(log_callback=lambda lvl, msg: logs.append((lvl, msg)))
            assert any('Transfer complete' in msg for _, msg in logs)

    def test_source_not_found_raises_error(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['No such file or directory\n'])
            mock_proc.wait.return_value = 23
            MockPopen.return_value = mock_proc
            handler = RsyncHandler(self._make_params())
            with pytest.raises(RsyncTransferError, match='SOURCE NOT FOUND'):
                handler.execute(log_callback=lambda lvl, msg: None)

    def test_insufficient_space_raises_error(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['No space left on device\n'])
            mock_proc.wait.return_value = 11
            MockPopen.return_value = mock_proc
            handler = RsyncHandler(self._make_params())
            with pytest.raises(RsyncTransferError, match='INSUFFICIENT SPACE'):
                handler.execute(log_callback=lambda lvl, msg: None)

    def test_retries_on_network_failure(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen, \
             patch('modules.rsync.handler.time.sleep') as mock_sleep:
            def make_proc(*args, **kwargs):
                m = MagicMock()
                m.stdout = iter([])
                m.wait.return_value = 10
                return m
            MockPopen.side_effect = make_proc
            handler = RsyncHandler(self._make_params())
            with pytest.raises(RsyncTransferError, match='TRANSFER FAILED'):
                handler.execute(log_callback=lambda lvl, msg: None)
            assert MockPopen.call_count == RSYNC_MAX_RETRIES
            assert mock_sleep.call_count == RSYNC_MAX_RETRIES - 1
            mock_sleep.assert_called_with(RSYNC_RETRY_DELAY)
