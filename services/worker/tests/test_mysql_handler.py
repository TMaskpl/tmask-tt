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
