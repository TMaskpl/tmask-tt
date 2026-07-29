from unittest.mock import MagicMock, patch

import pytest

from apps.connections.pg_utils import list_columns, list_tables, suggest_provider


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


class TestSuggestProvider:
    def test_matches_email_keyword(self):
        assert suggest_provider('user_email') == 'email'

    def test_matches_first_name_before_generic_name(self):
        assert suggest_provider('first_name') == 'first_name'

    def test_no_match_returns_none(self):
        assert suggest_provider('internal_ref_code') is None


class TestListColumns:
    @patch('apps.connections.pg_utils.psycopg2.connect')
    def test_marks_varchar_as_maskable_with_suggestion(self, mock_connect):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [('email', 'character varying'), ('id', 'integer')]
        mock_connect.return_value.cursor.return_value.__enter__.return_value = mock_cur
        result = list_columns(MagicMock(host='h', port=5432, username='u', password='p', db_name='db'), 'users')
        assert result[0] == {
            'name': 'email', 'data_type': 'character varying', 'maskable': True, 'suggested_provider': 'email',
        }
        assert result[1] == {
            'name': 'id', 'data_type': 'integer', 'maskable': False, 'suggested_provider': None,
        }
