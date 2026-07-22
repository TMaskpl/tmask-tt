import os
import subprocess  # nosec B404
import tempfile
import time
from typing import Callable

import pyodbc

from .config import MSSQL_MAX_RETRIES, MSSQL_RETRY_DELAY


class MssqlTransferError(Exception):
    pass


class MssqlTransferHandler:
    def __init__(self, params: dict):
        self.params = params

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
