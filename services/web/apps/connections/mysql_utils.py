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
