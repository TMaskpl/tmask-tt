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

    def test_known_host_key_adds_userkownhostsfile(self):
        handler = RsyncHandler(self._make_params(
            strict_host_key_checking=True,
            known_host_key='192.168.1.10 ssh-rsa AAAAB3Nz...',
        ))
        opts = handler._build_ssh_options(known_hosts_path='/tmp/kh_test')
        assert 'UserKnownHostsFile=' in opts
        assert 'StrictHostKeyChecking=yes' in opts
        assert 'StrictHostKeyChecking=no' not in opts

    def test_strict_false_adds_stricthostkeychecking_no(self):
        handler = RsyncHandler(self._make_params(strict_host_key_checking=False))
        opts = handler._build_ssh_options()
        assert '-o StrictHostKeyChecking=no' in opts

    def test_strict_true_without_known_key_no_userkownhostsfile(self):
        handler = RsyncHandler(self._make_params(
            strict_host_key_checking=True,
            known_host_key=None,
        ))
        opts = handler._build_ssh_options()
        assert 'UserKnownHostsFile' not in opts
        assert 'StrictHostKeyChecking=no' not in opts

    def test_execute_creates_and_cleans_up_known_hosts_tempfile(self):
        params = self._make_params(
            strict_host_key_checking=True,
            known_host_key='192.168.1.10 ssh-rsa AAAA...',
        )
        created_paths = []

        def fake_popen(cmd, **kwargs):
            for part in cmd:
                if 'UserKnownHostsFile=' in part:
                    path = part.split('=', 1)[1].strip("'")
                    created_paths.append(path)
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(params).execute(log_callback=lambda lvl, msg: None)

        assert len(created_paths) == 1
        assert not __import__('os').path.exists(created_paths[0])

    def test_execute_with_encrypt_uses_encrypted_paths(self):
        params = self._make_params(encrypt=True, gpg_passphrase='secret123')
        encrypted_tmp = '/tmp/data_abc.gpg'

        with patch('modules.rsync.handler.encrypt_file', return_value=encrypted_tmp) as mock_encrypt, \
             patch('modules.rsync.handler.os.path.exists', return_value=True), \
             patch('modules.rsync.handler.os.unlink') as mock_unlink, \
             patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.wait.return_value = 0
            MockPopen.return_value = mock_proc

            RsyncHandler(params).execute(log_callback=lambda lvl, msg: None)

            mock_encrypt.assert_called_once_with(params['source_path'], params['gpg_passphrase'])
            cmd = MockPopen.call_args[0][0]
            assert encrypted_tmp in cmd
            expected_dest = f'{params["username"]}@{params["host"]}:{params["destination_path"]}.gpg'
            assert expected_dest in cmd
            mock_unlink.assert_called_once_with(encrypted_tmp)

    def test_cleanup_encrypted_file_even_on_transfer_error(self):
        params = self._make_params(encrypt=True, gpg_passphrase='secret123')
        encrypted_tmp = '/tmp/data_abc.gpg'

        with patch('modules.rsync.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.rsync.handler.os.path.exists', return_value=True), \
             patch('modules.rsync.handler.os.unlink') as mock_unlink, \
             patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['Permission denied\n'])
            mock_proc.wait.return_value = 255
            MockPopen.return_value = mock_proc

            with pytest.raises(RsyncTransferError):
                RsyncHandler(params).execute(log_callback=lambda lvl, msg: None)

            mock_unlink.assert_called_once_with(encrypted_tmp)


class TestRsyncDryRun:
    def _make_params(self, **kwargs):
        defaults = {
            'host': '192.168.1.10',
            'port': 22,
            'username': 'deploy',
            'password': None,
            'ssh_key': None,
            'source_path': '/data/',
            'destination_path': '/backup/',
            'compress': False,
            'encrypt': False,
            'gpg_passphrase': None,
            'strict_host_key_checking': False,
            'known_host_key': None,
            'dry_run': False,
            'verify_checksum': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_dry_run_command_includes_flag(self):
        handler = RsyncHandler(self._make_params())
        cmd = handler._build_command(dry_run=True)
        assert '--dry-run' in cmd

    def test_real_command_excludes_dry_run_flag(self):
        handler = RsyncHandler(self._make_params())
        cmd = handler._build_command(dry_run=False)
        assert '--dry-run' not in cmd

    def test_dry_run_runs_before_real_transfer(self):
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(list(cmd))
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params(dry_run=True)).execute(lambda lvl, msg: None)

        assert len(calls) == 2
        assert '--dry-run' in calls[0]
        assert '--dry-run' not in calls[1]

    def test_dry_run_failure_aborts_transfer(self):
        call_count = [0]

        def fake_popen(cmd, **kwargs):
            call_count[0] += 1
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 1
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            with pytest.raises(RsyncTransferError, match='DRY-RUN FAILED'):
                RsyncHandler(self._make_params(dry_run=True)).execute(lambda lvl, msg: None)

        assert call_count[0] == 1  # tylko dry-run, właściwy transfer nie wywołany

    def test_dry_run_skipped_when_disabled(self):
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(list(cmd))
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params(dry_run=False)).execute(lambda lvl, msg: None)

        assert len(calls) == 1
        assert '--dry-run' not in calls[0]

    def test_dry_run_uses_encrypted_path_when_gpg_enabled(self):
        encrypted_tmp = '/tmp/data_abc.gpg'
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(list(cmd))
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.rsync.handler.os.path.exists', return_value=True), \
             patch('modules.rsync.handler.os.unlink'), \
             patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params(
                dry_run=True, encrypt=True, gpg_passphrase='secret',
            )).execute(lambda lvl, msg: None)

        assert len(calls) == 2
        assert '--dry-run' in calls[0]
        assert encrypted_tmp in calls[0]   # dry-run uses encrypted path
        assert '--dry-run' not in calls[1]
        assert encrypted_tmp in calls[1]   # real transfer also uses encrypted path


class TestBuildSshCmdPrefix:
    def _make_params(self, **kwargs):
        defaults = {
            'host': '192.168.1.10',
            'port': 22,
            'username': 'deploy',
            'password': None,
            'ssh_key': None,
            'source_path': '/data/file.tar',
            'destination_path': '/backup/file.tar',
            'compress': False,
            'encrypt': False,
            'gpg_passphrase': None,
            'strict_host_key_checking': False,
            'known_host_key': None,
            'dry_run': False,
            'verify_checksum': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_basic_command_structure(self):
        handler = RsyncHandler(self._make_params())
        prefix = handler._build_ssh_cmd_prefix()
        assert prefix[0] == 'ssh'
        assert '-p' in prefix
        assert '22' in prefix
        assert 'deploy@192.168.1.10' in prefix

    def test_ssh_key_included(self):
        handler = RsyncHandler(self._make_params(ssh_key='/home/user/.ssh/id_rsa'))
        prefix = handler._build_ssh_cmd_prefix()
        assert '-i' in prefix
        assert '/home/user/.ssh/id_rsa' in prefix

    def test_strict_host_key_checking_with_known_hosts(self):
        handler = RsyncHandler(self._make_params(strict_host_key_checking=True))
        prefix = handler._build_ssh_cmd_prefix(known_hosts_path='/tmp/known_hosts')
        options_str = ' '.join(prefix)
        assert 'UserKnownHostsFile' in options_str
        assert 'StrictHostKeyChecking=yes' in options_str

    def test_strict_host_key_checking_disabled(self):
        handler = RsyncHandler(self._make_params(strict_host_key_checking=False))
        prefix = handler._build_ssh_cmd_prefix()
        assert 'StrictHostKeyChecking=no' in prefix

    def test_invalid_port_raises(self):
        handler = RsyncHandler(self._make_params(port=99999))
        with pytest.raises(ValueError, match='Invalid port'):
            handler._build_ssh_cmd_prefix()


class TestRsyncChecksumVerification:
    def _make_params(self, **kwargs):
        defaults = {
            'host': '192.168.1.10',
            'port': 22,
            'username': 'deploy',
            'password': None,
            'ssh_key': None,
            'source_path': '/data/file.tar',
            'destination_path': '/backup/file.tar',
            'compress': False,
            'encrypt': False,
            'gpg_passphrase': None,
            'strict_host_key_checking': False,
            'known_host_key': None,
            'dry_run': False,
            'verify_checksum': False,
        }
        defaults.update(kwargs)
        return defaults

    def _popen_ok(self):
        m = MagicMock()
        m.stdout = iter([])
        m.wait.return_value = 0
        return m

    def test_calls_verify_rsync_after_successful_transfer(self):
        with patch('modules.rsync.handler.subprocess.Popen', return_value=self._popen_ok()), \
             patch('modules.rsync.handler.verify_rsync') as mock_verify:
            RsyncHandler(self._make_params(verify_checksum=True)).execute(lambda lvl, msg: None)
        mock_verify.assert_called_once()
        call_args = mock_verify.call_args
        assert call_args[0][0] == '/data/file.tar'    # source_path
        assert call_args[0][2] == '/backup/file.tar'  # destination_path

    def test_skips_verify_when_disabled(self):
        with patch('modules.rsync.handler.subprocess.Popen', return_value=self._popen_ok()), \
             patch('modules.rsync.handler.verify_rsync') as mock_verify:
            RsyncHandler(self._make_params(verify_checksum=False)).execute(lambda lvl, msg: None)
        mock_verify.assert_not_called()

    def test_raises_transfer_error_on_mismatch(self):
        from modules.checksum.handler import ChecksumVerificationError
        with patch('modules.rsync.handler.subprocess.Popen', return_value=self._popen_ok()), \
             patch('modules.rsync.handler.verify_rsync',
                   side_effect=ChecksumVerificationError('SHA-256 MISMATCH')):
            with pytest.raises(RsyncTransferError, match='MISMATCH'):
                RsyncHandler(self._make_params(verify_checksum=True)).execute(lambda lvl, msg: None)

    def test_skips_verify_when_gpg_enabled(self):
        encrypted_tmp = '/tmp/data_abc.gpg'
        logs = []
        with patch('modules.rsync.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.rsync.handler.os.path.exists', return_value=True), \
             patch('modules.rsync.handler.os.unlink'), \
             patch('modules.rsync.handler.subprocess.Popen', return_value=self._popen_ok()), \
             patch('modules.rsync.handler.verify_rsync') as mock_verify:
            RsyncHandler(self._make_params(
                encrypt=True, gpg_passphrase='secret', verify_checksum=True,
            )).execute(lambda lvl, msg: logs.append((lvl, msg)))
        mock_verify.assert_not_called()
        assert any('SHA-256' in msg and 'pomijane' in msg for _, msg in logs)


class TestRsyncHandlerPreview:
    def _make_params(self, **kwargs):
        defaults = {
            'host': '192.168.1.10',
            'port': 22,
            'username': 'deploy',
            'password': None,
            'ssh_key': None,
            'source_path': '/data/',
            'destination_path': '/backup/',
            'compress': False,
            'encrypt': False,
            'gpg_passphrase': None,
            'strict_host_key_checking': False,
            'known_host_key': None,
        }
        defaults.update(kwargs)
        return defaults

    def test_returns_exit_code_and_output_on_success(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['sending incremental file list\n', 'file.tar\n'])
            mock_proc.wait.return_value = 0
            MockPopen.return_value = mock_proc
            result = RsyncHandler(self._make_params()).preview(lambda lvl, msg: None)
            assert result['exit_code'] == 0
            assert 'file.tar' in result['output']

    def test_returns_nonzero_exit_code_instead_of_raising(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['Permission denied (publickey).\n'])
            mock_proc.wait.return_value = 255
            MockPopen.return_value = mock_proc
            result = RsyncHandler(self._make_params()).preview(lambda lvl, msg: None)
            assert result['exit_code'] == 255
            assert 'Permission denied' in result['output']

    def test_uses_dry_run_flag_in_command(self):
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(list(cmd))
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params()).preview(lambda lvl, msg: None)

        assert len(calls) == 1
        assert '--dry-run' in calls[0]

    def test_does_not_execute_real_transfer(self):
        call_count = [0]

        def fake_popen(cmd, **kwargs):
            call_count[0] += 1
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params()).preview(lambda lvl, msg: None)

        assert call_count[0] == 1  # tylko dry-run, żadnego drugiego wywołania

    def test_prepends_host_key_warning_when_verification_disabled(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['sending incremental file list\n'])
            mock_proc.wait.return_value = 0
            MockPopen.return_value = mock_proc
            result = RsyncHandler(self._make_params(strict_host_key_checking=False)).preview(
                lambda lvl, msg: None
            )
            assert 'Host key verification DISABLED' in result['output']

    def test_uses_encrypted_path_when_gpg_enabled(self):
        encrypted_tmp = '/tmp/data_abc.gpg'
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(list(cmd))
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.rsync.handler.os.path.exists', return_value=True), \
             patch('modules.rsync.handler.os.unlink'), \
             patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params(encrypt=True, gpg_passphrase='secret')).preview(
                lambda lvl, msg: None
            )

        assert len(calls) == 1
        assert encrypted_tmp in calls[0]

    def test_creates_and_cleans_up_known_hosts_tempfile(self):
        params = self._make_params(
            strict_host_key_checking=True,
            known_host_key='192.168.1.10 ssh-rsa AAAA...',
        )
        created_paths = []

        def fake_popen(cmd, **kwargs):
            for part in cmd:
                if 'UserKnownHostsFile=' in part:
                    path = part.split('=', 1)[1].strip("'")
                    created_paths.append(path)
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(params).preview(lambda lvl, msg: None)

        assert len(created_paths) == 1
        assert not __import__('os').path.exists(created_paths[0])
