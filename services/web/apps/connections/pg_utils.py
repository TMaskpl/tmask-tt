import psycopg2


def list_tables(connection) -> list:
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
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
