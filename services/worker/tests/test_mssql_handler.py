import pytest
from unittest.mock import patch, MagicMock

from modules.mssql.handler import MssqlTransferHandler, MssqlTransferError
from modules.mssql.config import MSSQL_MAX_RETRIES


class TestMssqlSchemaIntrospection:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'srcpw',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'dstpw', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_lists_all_tables_when_table_name_not_set(self):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.pyodbc.connect') as mock_connect:
            cur = MagicMock()
            cur.fetchall.return_value = [('users',), ('orders',)]
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            assert handler._source_table_names() == ['users', 'orders']

    def test_single_table_when_table_name_set(self):
        handler = MssqlTransferHandler(self._make_params(table_name='users'))
        assert handler._source_table_names() == ['users']

    def test_introspects_columns_and_primary_key(self):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.pyodbc.connect') as mock_connect:
            columns_cur = MagicMock()
            columns_cur.fetchall.return_value = [
                ('id', 'int', None, 10, 0, 'NO'),
                ('name', 'varchar', 100, None, None, 'YES'),
            ]
            pk_cur = MagicMock()
            pk_cur.fetchall.return_value = [('id',)]
            conn = mock_connect.return_value.__enter__.return_value
            conn.cursor.return_value.__enter__.side_effect = [columns_cur, pk_cur]
            schema = handler._introspect_table('users')
            assert schema['columns'][0]['name'] == 'id'
            assert schema['columns'][0]['data_type'] == 'int'
            assert schema['columns'][1]['character_maximum_length'] == 100
            assert schema['primary_key'] == ['id']


class TestMssqlDdlGeneration:
    def _make_params(self):
        return {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'p',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'p', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }

    def test_generates_create_table_with_columns_and_pk(self):
        handler = MssqlTransferHandler(self._make_params())
        schema = {
            'columns': [
                {'name': 'id', 'data_type': 'int', 'character_maximum_length': None,
                 'numeric_precision': 10, 'numeric_scale': 0, 'is_nullable': False},
                {'name': 'name', 'data_type': 'varchar', 'character_maximum_length': 100,
                 'numeric_precision': None, 'numeric_scale': None, 'is_nullable': True},
            ],
            'primary_key': ['id'],
        }
        ddl = handler._build_create_table_sql('users', schema)
        assert 'DROP TABLE IF EXISTS [users]' in ddl
        assert 'CREATE TABLE [users]' in ddl
        assert '[id] int NOT NULL' in ddl
        assert '[name] varchar(100) NULL' in ddl
        assert 'PRIMARY KEY ([id])' in ddl

    def test_no_primary_key_clause_when_table_has_none(self):
        handler = MssqlTransferHandler(self._make_params())
        schema = {
            'columns': [{'name': 'id', 'data_type': 'int', 'character_maximum_length': None,
                         'numeric_precision': 10, 'numeric_scale': 0, 'is_nullable': False}],
            'primary_key': [],
        }
        ddl = handler._build_create_table_sql('log_events', schema)
        assert 'PRIMARY KEY' not in ddl

    def test_decimal_type_includes_precision_and_scale(self):
        handler = MssqlTransferHandler(self._make_params())
        schema = {
            'columns': [{'name': 'amount', 'data_type': 'decimal', 'character_maximum_length': None,
                         'numeric_precision': 18, 'numeric_scale': 2, 'is_nullable': False}],
            'primary_key': [],
        }
        ddl = handler._build_create_table_sql('payments', schema)
        assert '[amount] decimal(18,2) NOT NULL' in ddl

    def test_identifier_with_bracket_char_is_escaped(self):
        # Defense-in-depth: a table/column name containing ']' must not break
        # out of the bracket-quoted identifier or allow T-SQL injection.
        handler = MssqlTransferHandler(self._make_params())
        schema = {
            'columns': [{'name': 'we]ird', 'data_type': 'int', 'character_maximum_length': None,
                         'numeric_precision': 10, 'numeric_scale': 0, 'is_nullable': False}],
            'primary_key': ['we]ird'],
        }
        ddl = handler._build_create_table_sql('od]d table', schema)
        assert 'DROP TABLE IF EXISTS [od]]d table]' in ddl
        assert 'CREATE TABLE [od]]d table]' in ddl
        assert '[we]]ird] int NOT NULL' in ddl
        assert 'PRIMARY KEY ([we]]ird])' in ddl


class TestMssqlCommandBuilding:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'srcpw',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'dstpw', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_builds_sqlcmd_command(self, tmp_path):
        handler = MssqlTransferHandler(self._make_params())
        cmd = handler._build_sqlcmd_cmd(str(tmp_path / 'ddl.sql'))
        assert cmd[0] == 'sqlcmd'
        assert 'dst' in cmd

    def test_builds_bcp_out_command(self, tmp_path):
        handler = MssqlTransferHandler(self._make_params())
        cmd = handler._build_bcp_out_cmd('users', str(tmp_path / 'users.dat'))
        assert cmd[0] == 'bcp'
        assert 'users' in cmd and 'out' in cmd and 'src' in cmd and '-n' in cmd

    def test_builds_bcp_in_command(self, tmp_path):
        handler = MssqlTransferHandler(self._make_params())
        cmd = handler._build_bcp_in_cmd('users', str(tmp_path / 'users.dat'))
        assert cmd[0] == 'bcp'
        assert 'users' in cmd and 'in' in cmd and 'dst' in cmd and '-n' in cmd


class TestMssqlExecute:
    def _make_params(self):
        return {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'srcpw',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'dstpw', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }

    def _mock_proc(self, stdout_lines, exit_code):
        proc = MagicMock()
        proc.stdout = iter(stdout_lines)
        proc.wait.return_value = exit_code
        return proc

    def test_successful_transfer_and_temp_files_cleaned_up(self):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.MssqlTransferHandler._source_table_names', return_value=['users']), \
             patch('modules.mssql.handler.MssqlTransferHandler._introspect_table',
                   return_value={'columns': [{'name': 'id', 'data_type': 'int', 'character_maximum_length': None,
                                               'numeric_precision': 10, 'numeric_scale': 0, 'is_nullable': False}],
                                 'primary_key': ['id']}), \
             patch('modules.mssql.handler.subprocess.Popen') as MockPopen, \
             patch('modules.mssql.handler.os.path.exists', return_value=True), \
             patch('modules.mssql.handler.os.unlink') as mock_unlink:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]
            handler.execute(log_callback=lambda lvl, msg: None)
            assert mock_unlink.call_count >= 1

    def test_password_passed_via_argv_documented_risk(self):
        # sqlcmd/bcp have no env-var password option — this test pins the accepted,
        # documented trade-off rather than silently assuming otherwise.
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.MssqlTransferHandler._source_table_names', return_value=['users']), \
             patch('modules.mssql.handler.MssqlTransferHandler._introspect_table',
                   return_value={'columns': [{'name': 'id', 'data_type': 'int', 'character_maximum_length': None,
                                               'numeric_precision': 10, 'numeric_scale': 0, 'is_nullable': False}],
                                 'primary_key': ['id']}), \
             patch('modules.mssql.handler.subprocess.Popen') as MockPopen, \
             patch('modules.mssql.handler.os.path.exists', return_value=False):
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]
            handler.execute(log_callback=lambda lvl, msg: None)
            all_args = [arg for call in MockPopen.call_args_list for arg in call.args[0]]
            assert 'srcpw' in all_args or 'dstpw' in all_args

    def test_retries_on_ddl_failure_then_raises(self):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.MssqlTransferHandler._source_table_names', return_value=['users']), \
             patch('modules.mssql.handler.MssqlTransferHandler._introspect_table',
                   return_value={'columns': [{'name': 'id', 'data_type': 'int', 'character_maximum_length': None,
                                               'numeric_precision': 10, 'numeric_scale': 0, 'is_nullable': False}],
                                 'primary_key': ['id']}), \
             patch('modules.mssql.handler.subprocess.Popen') as MockPopen, \
             patch('modules.mssql.handler.os.path.exists', return_value=False), \
             patch('modules.mssql.handler.time.sleep'):
            MockPopen.side_effect = [self._mock_proc([], 1)] * (MSSQL_MAX_RETRIES * 3)
            with pytest.raises(MssqlTransferError):
                handler.execute(log_callback=lambda lvl, msg: None)


class TestMssqlVerifyRowCounts:
    def _make_params(self):
        return {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'p',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'p', 'dest_db_name': 'dst', 'table_name': 'users', 'verify_row_count': True,
        }

    def test_matching_counts_no_warn(self):
        # NOTE: fixed from the task brief's literal test code, which mocked
        # `pyodbc.connect` as a context manager (`.return_value.__enter__...`)
        # even though _verify_row_counts assigns `src_conn = pyodbc.connect(...)`
        # directly and calls `src_conn.cursor()` — not
        # `with pyodbc.connect(...) as conn:`. The brief's mock chain was never
        # actually exercised (same fix already applied in
        # test_mysql_handler.py::TestMysqlVerifyRowCounts for the identical bug).
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.pyodbc.connect') as mock_connect:
            cur = MagicMock()
            cur.fetchone.return_value = (7,)
            conn = MagicMock()
            conn.cursor.return_value.__enter__.return_value = cur
            mock_connect.return_value = conn
            logs = []
            handler._verify_row_counts(lambda lvl, msg: logs.append((lvl, msg)))
            assert not any(lvl == 'warn' for lvl, _ in logs)
            assert any(lvl == 'info' and 'ROW COUNT OK' in msg for lvl, msg in logs)

    def test_mismatched_counts_warns(self):
        # See NOTE above — uses distinct src/dst connection mocks so the two
        # SELECT COUNT(*) calls actually return different values.
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.pyodbc.connect') as mock_connect:
            src_cursor = MagicMock()
            src_cursor.fetchone.return_value = (7,)
            dst_cursor = MagicMock()
            dst_cursor.fetchone.return_value = (4,)
            src_conn = MagicMock()
            src_conn.cursor.return_value.__enter__.return_value = src_cursor
            dst_conn = MagicMock()
            dst_conn.cursor.return_value.__enter__.return_value = dst_cursor
            mock_connect.side_effect = [src_conn, dst_conn]
            logs = []
            handler._verify_row_counts(lambda lvl, msg: logs.append((lvl, msg)))
            assert any(lvl == 'warn' for lvl, _ in logs)
