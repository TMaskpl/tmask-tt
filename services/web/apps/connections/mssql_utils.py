import pyodbc


def _conn_string(connection) -> str:
    return (
        f'DRIVER={{ODBC Driver 18 for SQL Server}};'
        f'SERVER={connection.host},{connection.port};DATABASE={connection.db_name};'
        f'UID={connection.username};PWD={connection.password};TrustServerCertificate=yes;'
    )


def list_tables(connection) -> list:
    conn = pyodbc.connect(_conn_string(connection), timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
