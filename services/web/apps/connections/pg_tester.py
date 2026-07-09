from dataclasses import dataclass

import psycopg2


@dataclass
class PgTestResult:
    success: bool
    message: str


def test_connection(connection) -> PgTestResult:
    try:
        conn = psycopg2.connect(
            host=connection.host,
            port=connection.port,
            user=connection.username,
            password=connection.password,
            dbname=connection.db_name,
            connect_timeout=10,
        )
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT 1')
                cur.fetchone()
        finally:
            conn.close()
        return PgTestResult(True, 'CONNECTION OK')
    except psycopg2.OperationalError as e:
        return PgTestResult(False, f'CONNECTION FAILED — {e}'.strip())
