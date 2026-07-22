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
