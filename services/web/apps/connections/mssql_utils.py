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


from .pg_utils import suggest_provider

_MSSQL_MASKABLE_TYPES = {'varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext'}


def list_columns(connection, table_name: str) -> list:
    conn = pyodbc.connect(_conn_string(connection), timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS '
                'WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION',
                table_name,
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            'name': row[0], 'data_type': row[1], 'maskable': row[1] in _MSSQL_MASKABLE_TYPES,
            'suggested_provider': suggest_provider(row[0]),
        }
        for row in rows
    ]
