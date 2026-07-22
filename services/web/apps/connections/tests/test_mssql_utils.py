from unittest.mock import patch, MagicMock
from apps.connections.mssql_utils import list_tables


class _Conn:
    host = 'h'; port = 1433; username = 'u'; password = 'p'; db_name = 'd'


def test_returns_table_names():
    with patch('apps.connections.mssql_utils.pyodbc.connect') as mock_connect:
        cur = MagicMock()
        cur.fetchall.return_value = [('users',), ('orders',)]
        mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
        assert list_tables(_Conn()) == ['users', 'orders']
