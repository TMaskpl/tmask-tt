from dataclasses import dataclass
import pymysql


@dataclass
class MysqlTestResult:
    success: bool
    message: str


def test_connection(connection) -> MysqlTestResult:
    try:
        conn = pymysql.connect(
            host=connection.host, port=connection.port, user=connection.username,
            password=connection.password, database=connection.db_name, connect_timeout=10,
        )
        conn.close()
        return MysqlTestResult(True, 'CONNECTION OK')
    except pymysql.OperationalError as e:
        return MysqlTestResult(False, f'CONNECTION FAILED — {e}'.strip())
