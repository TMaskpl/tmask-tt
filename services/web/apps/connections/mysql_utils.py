import pymysql


def list_tables(connection) -> list:
    conn = pymysql.connect(
        host=connection.host, port=connection.port, user=connection.username,
        password=connection.password, database=connection.db_name, connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name',
                (connection.db_name,),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


from .pg_utils import suggest_provider

_MYSQL_MASKABLE_TYPES = {'varchar', 'char', 'text', 'tinytext', 'mediumtext', 'longtext'}


def list_columns(connection, table_name: str) -> list:
    conn = pymysql.connect(
        host=connection.host, port=connection.port, user=connection.username,
        password=connection.password, database=connection.db_name, connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name, data_type FROM information_schema.columns '
                'WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position',
                (connection.db_name, table_name),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            'name': name, 'data_type': data_type, 'maskable': data_type in _MYSQL_MASKABLE_TYPES,
            'suggested_provider': suggest_provider(name),
        }
        for name, data_type in rows
    ]
