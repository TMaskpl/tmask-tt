import pytest
from unittest.mock import patch, MagicMock

from modules.mysql.handler import MysqlTransferHandler, MysqlTransferError
from modules.mysql.config import MYSQL_DUMP_MAX_RETRIES, MYSQL_DUMP_RETRY_DELAY


class TestMysqlTransferHandler:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': '10.0.0.1', 'source_port': 3306, 'source_username': 'root',
            'source_password': 'srcpass', 'source_db_name': 'proddb',
            'dest_host': '10.0.0.2', 'dest_port': 3306, 'dest_username': 'root',
            'dest_password': 'dstpass', 'dest_db_name': 'testdb',
            'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_builds_whole_db_mysqldump_command(self):
        handler = MysqlTransferHandler(self._make_params())
        cmd = handler._build_mysqldump_cmd()
        assert cmd[0] == 'mysqldump'
        assert '-h' in cmd and '10.0.0.1' in cmd
        assert '--single-transaction' in cmd
        assert '--set-gtid-purged=OFF' in cmd
        assert '--skip-lock-tables' in cmd
        assert cmd[-1] == 'proddb'

    def test_builds_single_table_mysqldump_command(self):
        handler = MysqlTransferHandler(self._make_params(table_name='users'))
        cmd = handler._build_mysqldump_cmd()
        assert cmd[-2:] == ['proddb', 'users']

    def test_builds_mysql_client_command(self):
        handler = MysqlTransferHandler(self._make_params())
        cmd = handler._build_mysql_cmd()
        assert cmd[0] == 'mysql'
        assert '10.0.0.2' in cmd
        assert 'testdb' in cmd


class TestMysqlCollationCompat:
    def _make_params(self):
        return {
            'source_host': 'a', 'source_port': 3306, 'source_username': 'u', 'source_password': 'p',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 3306, 'dest_username': 'u',
            'dest_password': 'p', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }

    def test_dest_version_below_8_strips_collation(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.pymysql.connect') as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = ('5.7.44-log',)
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cursor
            assert handler._dest_needs_collation_strip() is True

    def test_dest_version_8_or_above_does_not_strip(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.pymysql.connect') as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = ('8.0.35',)
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cursor
            assert handler._dest_needs_collation_strip() is False

    def test_dest_unreachable_defaults_to_no_strip_and_warns(self):
        import pymysql
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.pymysql.connect', side_effect=pymysql.OperationalError('down')):
            logs = []
            assert handler._dest_needs_collation_strip(log_callback=lambda lvl, msg: logs.append((lvl, msg))) is False
            assert any('COLLATION' in msg.upper() or 'VERSION' in msg.upper() for _, msg in logs)


class TestMysqlTransferExecute:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': 'a', 'source_port': 3306, 'source_username': 'u', 'source_password': 'srcpw',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 3306, 'dest_username': 'u',
            'dest_password': 'dstpw', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    def _mock_proc(self, stderr_lines, exit_code):
        proc = MagicMock()
        proc.stderr = iter(stderr_lines)
        proc.stdout = MagicMock()
        proc.wait.return_value = exit_code
        return proc

    def test_successful_transfer(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.MysqlTransferHandler._dest_needs_collation_strip', return_value=False), \
             patch('modules.mysql.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler.execute(log_callback=lambda lvl, msg: None)  # should not raise

    def test_mysql_pwd_env_never_in_argv(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.MysqlTransferHandler._dest_needs_collation_strip', return_value=False), \
             patch('modules.mysql.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler.execute(log_callback=lambda lvl, msg: None)
            for call in MockPopen.call_args_list:
                cmd = call.args[0]
                assert 'srcpw' not in cmd and 'dstpw' not in cmd
                assert 'MYSQL_PWD' in call.kwargs['env']

    def test_collation_stripped_when_dest_below_8(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.MysqlTransferHandler._dest_needs_collation_strip', return_value=True), \
             patch('modules.mysql.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]
            handler.execute(log_callback=lambda lvl, msg: None)
            sed_calls = [c for c in MockPopen.call_args_list if c.args[0][0] == 'sed']
            assert len(sed_calls) == 1

    def test_retries_on_failure_then_raises(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.MysqlTransferHandler._dest_needs_collation_strip', return_value=False), \
             patch('modules.mysql.handler.subprocess.Popen') as MockPopen, \
             patch('modules.mysql.handler.time.sleep'):
            MockPopen.side_effect = [self._mock_proc([], 1), self._mock_proc([], 1)] * MYSQL_DUMP_MAX_RETRIES
            with pytest.raises(MysqlTransferError):
                handler.execute(log_callback=lambda lvl, msg: None)


class TestMysqlVerifyRowCounts:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': 'a', 'source_port': 3306, 'source_username': 'u', 'source_password': 'p',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 3306, 'dest_username': 'u',
            'dest_password': 'p', 'dest_db_name': 'dst', 'table_name': 'users', 'verify_row_count': True,
        }
        defaults.update(kwargs)
        return defaults

    def test_matching_counts_logs_info_not_warn(self):
        # NOTE: fixed from the task brief's literal test code, which mocked
        # `pymysql.connect` as a context manager (`.return_value.__enter__...`)
        # even though _verify_row_counts (mirroring PgTransferHandler exactly)
        # assigns `src_conn = pymysql.connect(...)` directly and calls
        # `src_conn.cursor()` — not `with pymysql.connect(...) as conn:`. The
        # brief's mock chain was never actually exercised. Mirrors the working
        # pattern in test_postgres_handler.py::test_verify_row_count_logs_ok_on_match.
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.pymysql.connect') as mock_connect:
            cur = MagicMock()
            cur.fetchone.return_value = (5,)
            conn = MagicMock()
            conn.cursor.return_value.__enter__.return_value = cur
            mock_connect.return_value = conn
            logs = []
            handler._verify_row_counts(lambda lvl, msg: logs.append((lvl, msg)))
            assert not any(lvl == 'warn' for lvl, _ in logs)
            assert any(lvl == 'info' and 'ROW COUNT OK' in msg for lvl, msg in logs)

    def test_mismatched_counts_logs_warn(self):
        # See NOTE above — uses distinct src/dst connection mocks (mirrors
        # test_postgres_handler.py::test_verify_row_count_logs_warning_on_mismatch)
        # so the two SELECT COUNT(*) calls actually return different values.
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.pymysql.connect') as mock_connect:
            src_cursor = MagicMock()
            src_cursor.fetchone.return_value = (5,)
            dst_cursor = MagicMock()
            dst_cursor.fetchone.return_value = (3,)
            src_conn = MagicMock()
            src_conn.cursor.return_value.__enter__.return_value = src_cursor
            dst_conn = MagicMock()
            dst_conn.cursor.return_value.__enter__.return_value = dst_cursor
            mock_connect.side_effect = [src_conn, dst_conn]
            logs = []
            handler._verify_row_counts(lambda lvl, msg: logs.append((lvl, msg)))
            assert any(lvl == 'warn' and 'MISMATCH' in msg for lvl, msg in logs)
