from dataclasses import dataclass
import pyodbc


@dataclass
class MssqlTestResult:
    success: bool
    message: str


def _conn_string(connection) -> str:
    return (
        f'DRIVER={{ODBC Driver 18 for SQL Server}};'
        f'SERVER={connection.host},{connection.port};DATABASE={connection.db_name};'
        f'UID={connection.username};PWD={connection.password};TrustServerCertificate=yes;'
    )


def test_connection(connection) -> MssqlTestResult:
    try:
        conn = pyodbc.connect(_conn_string(connection), timeout=10)
        conn.close()
        return MssqlTestResult(True, 'CONNECTION OK')
    except pyodbc.OperationalError as e:
        return MssqlTestResult(False, f'CONNECTION FAILED — {e}'.strip())
