from unittest.mock import patch, MagicMock

import pytest

from apps.connections.mysql_utils import list_columns, list_tables


class _Conn:
    host = 'h'; port = 3306; username = 'u'; password = 'p'; db_name = 'd'


def test_returns_table_names():
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [('users',), ('orders',)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    with patch('apps.connections.mysql_utils.pymysql.connect', return_value=mock_conn):
        tables = list_tables(_Conn())
    assert tables == ['users', 'orders']
    mock_conn.close.assert_called_once()


def test_closes_connection_when_query_raises():
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = RuntimeError('boom')
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    with patch('apps.connections.mysql_utils.pymysql.connect', return_value=mock_conn):
        with pytest.raises(RuntimeError, match='boom'):
            list_tables(_Conn())
    mock_conn.close.assert_called_once()


class TestListColumns:
    @patch('apps.connections.mysql_utils.pymysql.connect')
    def test_marks_varchar_as_maskable(self, mock_connect):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [('phone', 'varchar'), ('created_at', 'datetime')]
        mock_connect.return_value.cursor.return_value.__enter__.return_value = mock_cur
        result = list_columns(MagicMock(host='h', port=3306, username='u', password='p', db_name='db'), 'users')
        assert result[0]['maskable'] is True
        assert result[0]['suggested_provider'] == 'phone_number'
        assert result[1]['maskable'] is False
