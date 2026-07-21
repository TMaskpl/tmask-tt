from unittest.mock import patch, MagicMock
import pyodbc
from apps.connections.mssql_tester import test_connection as _test_mssql_connection


class _Conn:
    host = 'h'; port = 1433; username = 'u'; password = 'p'; db_name = 'd'


def test_success():
    with patch('apps.connections.mssql_tester.pyodbc.connect') as mock_connect:
        mock_connect.return_value = MagicMock()
        result = _test_mssql_connection(_Conn())
        assert result.success is True


def test_failure():
    with patch('apps.connections.mssql_tester.pyodbc.connect', side_effect=pyodbc.OperationalError('refused')):
        result = _test_mssql_connection(_Conn())
        assert result.success is False
