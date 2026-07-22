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
