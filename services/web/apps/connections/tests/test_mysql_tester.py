from unittest.mock import patch, MagicMock
import pymysql
from apps.connections.mysql_tester import test_connection as _test_mysql_connection


class _Conn:
    host = 'h'; port = 3306; username = 'u'; password = 'p'; db_name = 'd'


def test_success():
    with patch('apps.connections.mysql_tester.pymysql.connect') as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        result = _test_mysql_connection(_Conn())
        assert result.success is True
        mock_conn.close.assert_called_once()


def test_failure():
    with patch('apps.connections.mysql_tester.pymysql.connect', side_effect=pymysql.OperationalError('refused')):
        result = _test_mysql_connection(_Conn())
        assert result.success is False
        assert 'refused' in result.message
