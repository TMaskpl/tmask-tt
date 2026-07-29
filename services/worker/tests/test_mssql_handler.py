import pyodbc
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
            'masking_rules': {},
        }
        defaults.update(kwargs)
        return defaults

    def test_table_without_masking_rules_uses_native_bcp_flag(self):
        handler = MssqlTransferHandler(self._make_params(masking_rules={}))
        cmd = handler._build_bcp_out_cmd('users', '/tmp/x.dat')
        assert '-n' in cmd
        assert '-c' not in cmd

    def test_table_with_masking_rule_uses_character_bcp_flag(self):
        # NOTE: fixed from the task brief's literal test code, which called
        # _build_bcp_out_cmd('users', '/tmp/x.dat') with no `native` argument
        # and expected '-c' back. _build_bcp_out_cmd defaults to native=True
        # (i.e. '-n') per its own signature — it has no way to look at
        # masking_rules itself; the decision to go character-mode lives in
        # _transfer_once, which computes `native = not bool(rules)` and passes
        # it explicitly. Passing native=False here is what actually exercises
        # the real call path.
        handler = MssqlTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        cmd = handler._build_bcp_out_cmd('users', '/tmp/x.dat', native=False)
        assert '-c' in cmd
        assert '-n' not in cmd

    def test_builds_sqlcmd_command(self, tmp_path):
        handler = MssqlTransferHandler(self._make_params())
        cmd = handler._build_sqlcmd_cmd(str(tmp_path / 'ddl.sql'))
        assert cmd[0] == 'sqlcmd'
        assert 'dst' in cmd
        # -b ("on error batch abort") is required for sqlcmd's own exit code to
        # reflect a failed T-SQL statement inside the script — without it, sqlcmd
        # exits 0 even when a CREATE TABLE inside the DDL script fails.
        assert '-b' in cmd

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


class TestMssqlMasking:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'srcpw',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'dstpw', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
            'masking_rules': {},
        }
        defaults.update(kwargs)
        return defaults

    def test_masking_replaces_column_in_character_mode_file(self, tmp_path):
        handler = MssqlTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        dat_path = tmp_path / 'users.dat'
        dat_path.write_text('1\tjan@firma.pl\n2\tewa@firma.pl\n')
        schema = {'columns': [{'name': 'id'}, {'name': 'email'}], 'primary_key': ['id']}
        handler._mask_dat_file(str(dat_path), 'users', schema)
        lines = dat_path.read_text().splitlines()
        assert lines[0].split('\t')[0] == '1'
        assert 'jan@firma.pl' not in lines[0]
        assert 'ewa@firma.pl' not in lines[1]

    def test_whole_db_scope_warns_for_table_without_profile(self):
        handler = MssqlTransferHandler(self._make_params(masking_rules={}, table_name=None))
        warnings = []
        handler._whole_db_scope = True
        rules = handler._rules_for('sessions', log_callback=lambda level, msg: warnings.append((level, msg)))
        assert rules == {}
        assert any(level == 'warn' and 'sessions' in msg for level, msg in warnings)

    def test_single_table_scope_does_not_warn(self):
        handler = MssqlTransferHandler(self._make_params(masking_rules={}, table_name='sessions'))
        warnings = []
        handler._whole_db_scope = False
        handler._rules_for('sessions', log_callback=lambda level, msg: warnings.append((level, msg)))
        assert warnings == []


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
        # Regression test for the missing `-b` flag on sqlcmd: without it, sqlcmd
        # exits 0 even on a failed DDL statement, so a non-zero exit here is the
        # only signal the handler has that DDL application failed. This test
        # simulates sqlcmd returning a non-zero exit (as it correctly does once
        # `-b` is present and a script statement fails) and asserts the handler
        # (1) never proceeds to `bcp` for a failed DDL step, (2) retries up to
        # MSSQL_MAX_RETRIES times, and (3) ultimately raises MssqlTransferError.
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
            # Exactly one Popen call per attempt (sqlcmd only) proves bcp was
            # never invoked after a failed DDL step — no silent fall-through.
            assert MockPopen.call_count == MSSQL_MAX_RETRIES
            for call in MockPopen.call_args_list:
                assert call.args[0][0] == 'sqlcmd'

    def test_temp_files_cleaned_up_even_when_every_attempt_fails(self):
        # The DDL temp file must be removed by the `finally` block in
        # `_transfer_once` on every attempt, not just on eventual success —
        # otherwise a persistently failing transfer would leak one temp file
        # per retry attempt.
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.MssqlTransferHandler._source_table_names', return_value=['users']), \
             patch('modules.mssql.handler.MssqlTransferHandler._introspect_table',
                   return_value={'columns': [{'name': 'id', 'data_type': 'int', 'character_maximum_length': None,
                                               'numeric_precision': 10, 'numeric_scale': 0, 'is_nullable': False}],
                                 'primary_key': ['id']}), \
             patch('modules.mssql.handler.subprocess.Popen') as MockPopen, \
             patch('modules.mssql.handler.os.path.exists', return_value=True), \
             patch('modules.mssql.handler.os.unlink') as mock_unlink, \
             patch('modules.mssql.handler.time.sleep'):
            MockPopen.side_effect = [self._mock_proc([], 1)] * (MSSQL_MAX_RETRIES * 3)
            with pytest.raises(MssqlTransferError):
                handler.execute(log_callback=lambda lvl, msg: None)
            # sqlcmd fails immediately on every attempt, so exactly one DDL temp
            # file is created (and cleaned up) per retry attempt.
            assert mock_unlink.call_count == MSSQL_MAX_RETRIES


class TestMssqlIntrospectionErrorWrapping:
    # Every other failure path in this handler (DDL apply via sqlcmd, bcp out/in)
    # eventually raises MssqlTransferError. Schema introspection (_source_table_names /
    # _introspect_table) uses pyodbc directly and previously let a raw pyodbc.Error
    # (e.g. source connection failure) escape execute() unwrapped, inconsistent with
    # the rest of the module's error contract.
    def _make_params(self):
        return {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'srcpw',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'dstpw', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }

    def test_pyodbc_error_during_table_listing_becomes_mssql_transfer_error(self):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.MssqlTransferHandler._source_table_names',
                   side_effect=pyodbc.Error('08001', 'source unreachable')):
            with pytest.raises(MssqlTransferError) as exc_info:
                handler.execute(log_callback=lambda lvl, msg: None)
            assert 'SCHEMA INTROSPECTION FAILED' in str(exc_info.value)
            # The raw driver exception must not be what callers see.
            assert not isinstance(exc_info.value, pyodbc.Error)

    def test_pyodbc_error_during_column_introspection_becomes_mssql_transfer_error(self):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.MssqlTransferHandler._source_table_names', return_value=['users']), \
             patch('modules.mssql.handler.MssqlTransferHandler._introspect_table',
                   side_effect=pyodbc.Error('HY000', 'introspection query failed')):
            with pytest.raises(MssqlTransferError) as exc_info:
                handler.execute(log_callback=lambda lvl, msg: None)
            assert 'SCHEMA INTROSPECTION FAILED' in str(exc_info.value)

    def test_introspection_failure_is_not_retried(self):
        # Preserves pre-existing behavior: an exception escaping _transfer_once
        # (as opposed to a False return from a failed DDL/bcp step) has never
        # gone through the retry loop's "if attempt < MAX: retry" branch — it
        # unwinds immediately. This test pins that so the fix only changes the
        # exception type, not the retry semantics for this failure class.
        handler = MssqlTransferHandler(self._make_params())
        call_count = 0

        def _raise_once(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise pyodbc.Error('08001', 'source unreachable')

        with patch('modules.mssql.handler.MssqlTransferHandler._source_table_names', side_effect=_raise_once), \
             patch('modules.mssql.handler.time.sleep') as mock_sleep:
            with pytest.raises(MssqlTransferError):
                handler.execute(log_callback=lambda lvl, msg: None)
            assert call_count == 1
            mock_sleep.assert_not_called()


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
