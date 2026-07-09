import pytest
from unittest.mock import patch, MagicMock

from modules.postgres.handler import PgTransferHandler, PgTransferError
from modules.postgres.config import PG_DUMP_MAX_RETRIES, PG_DUMP_RETRY_DELAY


class TestPgTransferHandler:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': '10.0.0.1', 'source_port': 5432, 'source_username': 'postgres',
            'source_password': 'srcpass', 'source_db_name': 'proddb',
            'dest_host': '10.0.0.2', 'dest_port': 5432, 'dest_username': 'postgres',
            'dest_password': 'dstpass', 'dest_db_name': 'testdb',
            'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_builds_whole_db_pg_dump_command(self):
        handler = PgTransferHandler(self._make_params())
        cmd = handler._build_pg_dump_cmd()
        assert cmd[0] == 'pg_dump'
        assert '-h' in cmd and '10.0.0.1' in cmd
        assert '--clean' in cmd and '--if-exists' in cmd and '--no-owner' in cmd and '--no-privileges' in cmd
        assert '--table' not in cmd
        assert cmd[-1] == 'proddb'

    def test_builds_single_table_pg_dump_command(self):
        handler = PgTransferHandler(self._make_params(table_name='users'))
        cmd = handler._build_pg_dump_cmd()
        assert '--table' in cmd
        assert cmd[cmd.index('--table') + 1] == 'users'

    def test_builds_psql_command(self):
        handler = PgTransferHandler(self._make_params())
        cmd = handler._build_psql_cmd()
        assert cmd[0] == 'psql'
        assert '10.0.0.2' in cmd
        assert 'testdb' in cmd

    def _mock_proc(self, stderr_lines, exit_code):
        proc = MagicMock()
        proc.stderr = iter(stderr_lines)
        proc.wait.return_value = exit_code
        return proc

    def test_successful_transfer_returns_without_error(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler = PgTransferHandler(self._make_params())
            handler.execute(log_callback=lambda lvl, msg: None)  # should not raise

    def test_pgpassword_passed_via_env_not_argv(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler = PgTransferHandler(self._make_params())
            handler.execute(log_callback=lambda lvl, msg: None)

            dump_call = MockPopen.call_args_list[0]
            psql_call = MockPopen.call_args_list[1]
            dump_argv = dump_call.args[0]
            psql_argv = psql_call.args[0]
            assert not any('srcpass' in str(a) for a in dump_argv)
            assert not any('dstpass' in str(a) for a in psql_argv)
            assert dump_call.kwargs['env']['PGPASSWORD'] == 'srcpass'
            assert psql_call.kwargs['env']['PGPASSWORD'] == 'dstpass'

    def test_auth_failure_raises_without_retry(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.time.sleep') as mock_sleep:
            dump_proc = self._mock_proc(['pg_dump: error: connection to server failed'], 1)
            psql_proc = self._mock_proc(['psql: error: password authentication failed for user "postgres"'], 1)
            MockPopen.side_effect = [dump_proc, psql_proc]
            handler = PgTransferHandler(self._make_params())
            with pytest.raises(PgTransferError, match='AUTH FAILED'):
                handler.execute(log_callback=lambda lvl, msg: None)
            mock_sleep.assert_not_called()

    def test_transient_failure_retries_then_succeeds(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.time.sleep'):
            fail_dump = self._mock_proc(['pg_dump: error: server closed the connection unexpectedly'], 1)
            fail_psql = self._mock_proc([], 1)
            ok_dump = self._mock_proc([], 0)
            ok_psql = self._mock_proc([], 0)
            MockPopen.side_effect = [fail_dump, fail_psql, ok_dump, ok_psql]
            handler = PgTransferHandler(self._make_params())
            handler.execute(log_callback=lambda lvl, msg: None)  # should not raise
            assert MockPopen.call_count == 4

    def test_exhausted_retries_raises(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.time.sleep'):
            MockPopen.side_effect = [
                self._mock_proc(['server closed the connection unexpectedly'], 1),
                self._mock_proc([], 1),
            ] * PG_DUMP_MAX_RETRIES
            handler = PgTransferHandler(self._make_params())
            with pytest.raises(PgTransferError, match='TRANSFER FAILED'):
                handler.execute(log_callback=lambda lvl, msg: None)
            assert MockPopen.call_count == PG_DUMP_MAX_RETRIES * 2
