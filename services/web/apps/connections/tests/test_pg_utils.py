from unittest.mock import MagicMock, patch

import pytest

from apps.connections.pg_utils import list_tables


@pytest.mark.django_db
class TestListTables:
    def test_returns_table_names_sorted(self, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('orders',), ('users',)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        with patch('apps.connections.pg_utils.psycopg2.connect', return_value=mock_conn):
            tables = list_tables(conn)
        assert tables == ['orders', 'users']
        mock_conn.close.assert_called_once()
