import psycopg2
import pytest
from psycopg2 import sql
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
            'masking_rules': {},
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
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]
            handler = PgTransferHandler(self._make_params())
            handler.execute(log_callback=lambda lvl, msg: None)  # should not raise

    def test_pgpassword_passed_via_env_not_argv(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]
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

    def test_verify_row_count_logs_ok_on_match(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.psycopg2.connect') as mock_connect:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]

            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (5,)
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_connect.return_value = mock_conn

            logs = []
            handler = PgTransferHandler(self._make_params(table_name='users', verify_row_count=True))
            handler.execute(log_callback=lambda lvl, msg: logs.append((lvl, msg)))

            assert any(lvl == 'info' and 'ROW COUNT OK' in msg for lvl, msg in logs)

    def test_verify_row_count_logs_warning_on_mismatch(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.psycopg2.connect') as mock_connect:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]

            src_cursor = MagicMock()
            src_cursor.fetchone.return_value = (10,)
            dst_cursor = MagicMock()
            dst_cursor.fetchone.return_value = (7,)
            src_conn = MagicMock()
            src_conn.cursor.return_value.__enter__.return_value = src_cursor
            dst_conn = MagicMock()
            dst_conn.cursor.return_value.__enter__.return_value = dst_cursor
            mock_connect.side_effect = [src_conn, dst_conn]

            logs = []
            handler = PgTransferHandler(self._make_params(table_name='users', verify_row_count=True))
            handler.execute(log_callback=lambda lvl, msg: logs.append((lvl, msg)))

            assert any(lvl == 'warn' and 'MISMATCH' in msg for lvl, msg in logs)

    def test_verify_row_count_skipped_when_disabled(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.psycopg2.connect') as mock_connect:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]
            handler = PgTransferHandler(self._make_params(verify_row_count=False))
            handler.execute(log_callback=lambda lvl, msg: None)
            mock_connect.assert_not_called()

    def test_verify_row_count_uses_safe_identifier_quoting_not_fstring(self):
        # Table name containing a double-quote — would break out of an f-string
        # f'SELECT COUNT(*) FROM "{table}"' and allow SQL injection.
        malicious_table = 'users"; DROP TABLE x;--'
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.psycopg2.connect') as mock_connect:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]

            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (5,)
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_connect.return_value = mock_conn

            handler = PgTransferHandler(self._make_params(table_name=malicious_table, verify_row_count=True))
            handler.execute(log_callback=lambda lvl, msg: None)  # should not raise

            assert mock_cursor.execute.call_count >= 1
            for call in mock_cursor.execute.call_args_list:
                executed = call.args[0]
                # Must be a safely-composed psycopg2.sql object, never a raw string
                # containing the unescaped table name spliced in (which is what
                # f'SELECT COUNT(*) FROM "{table}"' would produce).
                assert isinstance(executed, sql.Composed)
                assert not isinstance(executed, str)
                # The table name must be carried as sql.Identifier data — never
                # concatenated into a plain SQL string fragment.
                identifiers = [part for part in executed.seq if isinstance(part, sql.Identifier)]
                assert len(identifiers) == 1
                assert identifiers[0].strings == (malicious_table,)
                sql_fragments = [part for part in executed.seq if isinstance(part, sql.SQL)]
                for frag in sql_fragments:
                    assert malicious_table not in frag.string
                    assert 'DROP TABLE' not in frag.string

    def test_dest_connect_failure_degrades_to_warn_not_exception(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.psycopg2.connect') as mock_connect:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]

            src_conn = MagicMock()
            mock_connect.side_effect = [src_conn, psycopg2.OperationalError('could not connect to destination')]

            logs = []
            handler = PgTransferHandler(self._make_params(table_name='users', verify_row_count=True))
            handler.execute(log_callback=lambda lvl, msg: logs.append((lvl, msg)))  # should not raise

            src_conn.close.assert_called_once()
            assert any(lvl == 'warn' and 'ROW COUNT VERIFICATION SKIPPED' in msg for lvl, msg in logs)

    def test_comparison_loop_error_degrades_to_warn_not_exception(self):
        # Regression test: a psycopg2.Error raised during table discovery or the
        # per-table COUNT(*) comparison loop must NOT propagate out of
        # _verify_row_counts — it must degrade to a warn log line, and both
        # connections must still be closed via the finally block.
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.psycopg2.connect') as mock_connect:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]

            src_cursor = MagicMock()
            src_cursor.execute.side_effect = psycopg2.OperationalError('server closed the connection unexpectedly')
            src_conn = MagicMock()
            src_conn.cursor.return_value.__enter__.return_value = src_cursor
            dst_conn = MagicMock()
            mock_connect.side_effect = [src_conn, dst_conn]

            logs = []
            handler = PgTransferHandler(self._make_params(table_name='users', verify_row_count=True))
            handler.execute(log_callback=lambda lvl, msg: logs.append((lvl, msg)))  # should not raise

            src_conn.close.assert_called_once()
            dst_conn.close.assert_called_once()
            assert any(lvl == 'warn' and 'ROW COUNT VERIFICATION FAILED' in msg for lvl, msg in logs)

    def test_no_masking_rules_leaves_copy_data_untouched(self):
        handler = PgTransferHandler(self._make_params(masking_rules={}))
        dump_lines = [
            'CREATE TABLE users (id int, email text);\n',
            'COPY users (id, email) FROM stdin;\n',
            '1\tjan@firma.pl\n',
            '\\.\n',
        ]
        output = list(handler._relay_lines(iter(dump_lines)))
        assert output == dump_lines

    def test_masking_rule_replaces_configured_column_only(self):
        handler = PgTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        dump_lines = [
            'COPY users (id, email) FROM stdin;\n',
            '1\tjan@firma.pl\n',
            '\\.\n',
        ]
        output = list(handler._relay_lines(iter(dump_lines)))
        assert output[0] == 'COPY users (id, email) FROM stdin;\n'
        row = output[1].rstrip('\n').split('\t')
        assert row[0] == '1'
        assert row[1] != 'jan@firma.pl'
        assert output[2] == '\\.\n'

    def test_masking_rule_matches_schema_qualified_copy_header(self):
        # Real pg_dump always schema-qualifies COPY headers (public.users),
        # never bare table names — this test would have caught the original bug.
        handler = PgTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        dump_lines = [
            'COPY public.users (id, email) FROM stdin;\n',
            '1\tjan@firma.pl\n',
            '\\.\n',
        ]
        output = list(handler._relay_lines(iter(dump_lines)))
        row = output[1].rstrip('\n').split('\t')
        assert row[1] != 'jan@firma.pl'

    def test_strips_transaction_timeout_line(self):
        handler = PgTransferHandler(self._make_params(masking_rules={}))
        dump_lines = ['SET transaction_timeout = 0;\n', 'SELECT 1;\n']
        output = list(handler._relay_lines(iter(dump_lines)))
        assert output == ['SELECT 1;\n']

    def test_unmasked_table_in_same_dump_passes_through(self):
        handler = PgTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        dump_lines = [
            'COPY sessions (id, token) FROM stdin;\n',
            '1\tabc123\n',
            '\\.\n',
        ]
        output = list(handler._relay_lines(iter(dump_lines)))
        assert output[1] == '1\tabc123\n'

    def test_whole_db_scope_warns_once_on_table_without_profile(self):
        # table_name=None w params ⇒ scope CAŁA BAZA. Tabela 'sessions' nie ma
        # wpisu w masking_rules (brak profilu) ⇒ oczekujemy WARN w logu.
        handler = PgTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}}, table_name=None,
        ))
        warnings = []
        handler._log_callback = lambda level, msg: warnings.append((level, msg))
        handler._whole_db_scope = True
        dump_lines = ['COPY sessions (id, token) FROM stdin;\n', '1\tabc123\n', '\\.\n']
        list(handler._relay_lines(iter(dump_lines)))
        assert any(level == 'warn' and 'sessions' in msg and 'brak zdefiniowanego profilu' in msg for level, msg in warnings)

    def test_single_table_scope_does_not_warn_for_unmasked_table(self):
        # scope POJEDYNCZA TABELA — brak reguły dla tej tabeli jest świadomym
        # wyborem użytkownika, nie luką pokrycia jak w scope CAŁA BAZA. Zero WARN.
        handler = PgTransferHandler(self._make_params(masking_rules={}, table_name='sessions'))
        warnings = []
        handler._log_callback = lambda level, msg: warnings.append((level, msg))
        handler._whole_db_scope = False
        dump_lines = ['COPY sessions (id, token) FROM stdin;\n', '1\tabc123\n', '\\.\n']
        list(handler._relay_lines(iter(dump_lines)))
        assert warnings == []
