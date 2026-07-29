import os
import subprocess  # nosec B404
import tempfile
import time
from typing import Callable

import pyodbc

from modules.masking.faker_engine import mask_value

from .config import MSSQL_MAX_RETRIES, MSSQL_RETRY_DELAY


class MssqlTransferError(Exception):
    pass


class MssqlTransferHandler:
    def __init__(self, params: dict):
        self.params = params
        self._whole_db_scope = not self.params.get('table_name')

    def _quote_identifier(self, name: str) -> str:
        # pyodbc has no sql.Identifier()-equivalent safe-quoting API (unlike
        # psycopg2's psycopg2.sql module used in modules/postgres/handler.py).
        # MSSQL's bracket-quoting convention: wrap the identifier in [ ] and
        # double any ] characters found inside it — analogous to backtick-
        # doubling for MySQL (see modules/mysql/handler.py._quote_identifier).
        return '[' + name.replace(']', ']]') + ']'

    def _conn_string(self, host, port, db, user, password) -> str:
        return (
            f'DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={host},{port};DATABASE={db};'
            f'UID={user};PWD={password};TrustServerCertificate=yes;'
        )

    def _source_conn_string(self) -> str:
        p = self.params
        return self._conn_string(p['source_host'], p['source_port'], p['source_db_name'], p['source_username'], p['source_password'])

    def _dest_conn_string(self) -> str:
        p = self.params
        return self._conn_string(p['dest_host'], p['dest_port'], p['dest_db_name'], p['dest_username'], p['dest_password'])

    def _source_table_names(self) -> list:
        if self.params.get('table_name'):
            return [self.params['table_name']]
        with pyodbc.connect(self._source_conn_string(), timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME")
                return [row[0] for row in cur.fetchall()]

    def _introspect_table(self, table_name: str) -> dict:
        with pyodbc.connect(self._source_conn_string(), timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, '
                    'NUMERIC_SCALE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS '
                    'WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION',
                    table_name,
                )
                columns = [
                    {
                        'name': row[0], 'data_type': row[1], 'character_maximum_length': row[2],
                        'numeric_precision': row[3], 'numeric_scale': row[4], 'is_nullable': row[5] == 'YES',
                    }
                    for row in cur.fetchall()
                ]
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT kcu.COLUMN_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc '
                    'JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME '
                    "WHERE tc.TABLE_NAME = ? AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY' ORDER BY kcu.ORDINAL_POSITION",
                    table_name,
                )
                primary_key = [row[0] for row in cur.fetchall()]
        return {'columns': columns, 'primary_key': primary_key}

    _TYPES_WITH_LENGTH = {'varchar', 'nvarchar', 'char', 'nchar', 'varbinary', 'binary'}
    _TYPES_WITH_PRECISION_SCALE = {'decimal', 'numeric'}

    def _column_type_sql(self, col: dict) -> str:
        data_type = col['data_type']
        if data_type in self._TYPES_WITH_LENGTH and col['character_maximum_length']:
            length = col['character_maximum_length']
            return f'{data_type}({"max" if length == -1 else length})'
        if data_type in self._TYPES_WITH_PRECISION_SCALE and col['numeric_precision'] is not None:
            return f'{data_type}({col["numeric_precision"]},{col["numeric_scale"]})'
        return data_type

    def _build_create_table_sql(self, table_name: str, schema: dict) -> str:
        quoted_table = self._quote_identifier(table_name)
        column_lines = []
        for col in schema['columns']:
            nullability = 'NULL' if col['is_nullable'] else 'NOT NULL'
            column_lines.append(f'{self._quote_identifier(col["name"])} {self._column_type_sql(col)} {nullability}')
        if schema['primary_key']:
            pk_cols = ', '.join(self._quote_identifier(c) for c in schema['primary_key'])
            column_lines.append(f'PRIMARY KEY ({pk_cols})')
        columns_sql = ',\n    '.join(column_lines)
        return (
            f'DROP TABLE IF EXISTS {quoted_table};\n'
            f'CREATE TABLE {quoted_table} (\n    {columns_sql}\n);\n'
        )

    def _build_sqlcmd_cmd(self, ddl_path: str) -> list:
        p = self.params
        return [
            'sqlcmd', '-S', f'{p["dest_host"]},{p["dest_port"]}', '-d', p['dest_db_name'],
            '-U', p['dest_username'], '-P', p['dest_password'], '-i', ddl_path, '-b',
        ]

    def _build_bcp_out_cmd(self, table_name: str, out_path: str, native: bool = True) -> list:
        p = self.params
        mode_flag = '-n' if native else '-c'
        return [
            'bcp', table_name, 'out', out_path, '-S', f'{p["source_host"]},{p["source_port"]}',
            '-U', p['source_username'], '-P', p['source_password'], '-d', p['source_db_name'], mode_flag,
        ]

    def _build_bcp_in_cmd(self, table_name: str, in_path: str, native: bool = True) -> list:
        p = self.params
        mode_flag = '-n' if native else '-c'
        return [
            'bcp', table_name, 'in', in_path, '-S', f'{p["dest_host"]},{p["dest_port"]}',
            '-U', p['dest_username'], '-P', p['dest_password'], '-d', p['dest_db_name'], mode_flag,
        ]

    def _rules_for(self, table_name: str, log_callback: Callable[[str, str], None] = None) -> dict:
        rules = self.params.get('masking_rules', {}).get(table_name, {})
        if not rules and self._whole_db_scope and log_callback:
            log_callback('warn', f'Tabela "{table_name}" przesłana BEZ maskowania — brak zdefiniowanego profilu')
        return rules

    def _mask_dat_file(self, path: str, table_name: str, schema: dict) -> None:
        rules = self.params.get('masking_rules', {}).get(table_name, {})
        if not rules:
            return
        column_names = [c['name'] for c in schema['columns']]
        with open(path, 'r') as f:
            lines = f.readlines()
        with open(path, 'w') as f:
            for line in lines:
                values = line.rstrip('\n').split('\t')
                for i, col in enumerate(column_names):
                    if col in rules and i < len(values):
                        values[i] = mask_value(rules[col])
                f.write('\t'.join(values) + '\n')

    def _run_step(self, cmd: list, log_callback: Callable[[str, str], None]) -> int:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)  # nosec B603 — cmd built from validated connection params
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log_callback('info', line)
        return proc.wait()

    def _transfer_once(self, log_callback: Callable[[str, str], None]) -> bool:
        table_names = self._source_table_names()
        tmp_paths = []
        try:
            fd, ddl_path = tempfile.mkstemp(suffix='.sql')
            os.close(fd)
            tmp_paths.append(ddl_path)
            with open(ddl_path, 'w') as f:
                for table_name in table_names:
                    schema = self._introspect_table(table_name)
                    f.write(self._build_create_table_sql(table_name, schema))

            if self._run_step(self._build_sqlcmd_cmd(ddl_path), log_callback) != 0:
                return False

            for table_name in table_names:
                fd, data_path = tempfile.mkstemp(suffix='.dat')
                os.close(fd)
                tmp_paths.append(data_path)
                rules = self._rules_for(table_name, log_callback)
                native = not bool(rules)
                if self._run_step(self._build_bcp_out_cmd(table_name, data_path, native=native), log_callback) != 0:
                    return False
                if rules:
                    schema = self._introspect_table(table_name)
                    self._mask_dat_file(data_path, table_name, schema)
                if self._run_step(self._build_bcp_in_cmd(table_name, data_path, native=native), log_callback) != 0:
                    return False
            return True
        finally:
            for path in tmp_paths:
                if os.path.exists(path):
                    os.unlink(path)

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        for attempt in range(1, MSSQL_MAX_RETRIES + 1):
            log_callback('info', f'Starting MSSQL schema+data transfer (attempt {attempt})')
            try:
                transfer_ok = self._transfer_once(log_callback)
            except pyodbc.Error as e:
                raise MssqlTransferError(f'SCHEMA INTROSPECTION FAILED — {e}') from e
            if transfer_ok:
                log_callback('info', 'Transfer complete')
                if self.params.get('verify_row_count'):
                    self._verify_row_counts(log_callback)
                return
            if attempt < MSSQL_MAX_RETRIES:
                log_callback('warn', f'Transfer step failed, retrying in {MSSQL_RETRY_DELAY}s...')
                time.sleep(MSSQL_RETRY_DELAY)

        raise MssqlTransferError(f'TRANSFER FAILED — mssql transfer failed after {MSSQL_MAX_RETRIES} attempts')

    def _verify_row_counts(self, log_callback: Callable[[str, str], None]) -> None:
        try:
            src_conn = pyodbc.connect(self._source_conn_string(), timeout=10)
        except pyodbc.Error as e:
            log_callback('warn', f'ROW COUNT VERIFICATION SKIPPED — nie udało się połączyć ze źródłem: {e}')
            return
        try:
            dst_conn = pyodbc.connect(self._dest_conn_string(), timeout=10)
        except pyodbc.Error as e:
            src_conn.close()
            log_callback('warn', f'ROW COUNT VERIFICATION SKIPPED — nie udało się połączyć z celem: {e}')
            return
        try:
            tables = self._source_table_names()
            for table in tables:
                quoted_table = self._quote_identifier(table)
                with src_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM {quoted_table}')  # nosec B608 — identifier is safely quoted via _quote_identifier, not raw-interpolated
                    src_count = cur.fetchone()[0]
                with dst_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM {quoted_table}')  # nosec B608 — identifier is safely quoted via _quote_identifier, not raw-interpolated
                    dst_count = cur.fetchone()[0]
                if src_count != dst_count:
                    log_callback('warn', f'ROW COUNT MISMATCH w "{table}": source={src_count} dest={dst_count}')
                else:
                    log_callback('info', f'ROW COUNT OK w "{table}": {src_count}')
        except pyodbc.Error as e:
            log_callback('warn', f'ROW COUNT VERIFICATION FAILED — {e}')
        finally:
            src_conn.close()
            dst_conn.close()
