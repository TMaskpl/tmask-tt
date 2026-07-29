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


_PG_MASKABLE_TYPES = {'character varying', 'varchar', 'text', 'char', 'character'}

_SUGGESTION_KEYWORDS = [
    (('first_name', 'given_name', 'firstname'), 'first_name'),
    (('last_name', 'surname', 'lastname'), 'last_name'),
    (('email', 'mail'), 'email'),
    (('phone', 'tel', 'mobile'), 'phone_number'),
    (('street', 'address1', 'address_line'), 'street_address'),
    (('city', 'town'), 'city'),
    (('zip', 'postcode', 'postal'), 'postcode'),
    (('country',), 'country'),
    (('company', 'employer', 'organization'), 'company'),
    (('job', 'title', 'position'), 'job_title'),
    (('name', 'fullname'), 'name'),
]


def suggest_provider(column_name: str) -> str | None:
    lowered = column_name.lower()
    for keywords, provider in _SUGGESTION_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return provider
    return None


def list_columns(connection, table_name: str) -> list:
    conn = psycopg2.connect(
        host=connection.host, port=connection.port, user=connection.username,
        password=connection.password, dbname=connection.db_name, connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name, data_type FROM information_schema.columns '
                "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
                (table_name,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            'name': name, 'data_type': data_type, 'maskable': data_type in _PG_MASKABLE_TYPES,
            'suggested_provider': suggest_provider(name),
        }
        for name, data_type in rows
    ]
