from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from apps.connections.pg_tester import test_connection as _test_pg_connection


@pytest.mark.django_db
class TestPgTesterMessages:
    def test_success_message(self, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb', host='10.0.0.5', port=5432)
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        with patch('apps.connections.pg_tester.psycopg2.connect', return_value=mock_conn):
            result = _test_pg_connection(conn)
        assert result.success is True
        assert result.message == 'CONNECTION OK'

    def test_failure_message_on_operational_error(self, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb', host='10.0.0.5', port=5432)
        with patch('apps.connections.pg_tester.psycopg2.connect', side_effect=psycopg2.OperationalError('connection refused')):
            result = _test_pg_connection(conn)
        assert result.success is False
        assert 'CONNECTION FAILED' in result.message
