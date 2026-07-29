import psycopg2
import pymysql
import pyodbc
from django.shortcuts import render
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_READONLY
from apps.connections.models import Connection, KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL
from apps.connections.pg_utils import list_columns as _list_pg_columns
from apps.connections.mysql_utils import list_columns as _list_mysql_columns
from apps.connections.mssql_utils import list_columns as _list_mssql_columns


@require_role(ROLE_READONLY)
def masking_columns(request):
    raw_connection = request.GET.get('connection')
    table_name = request.GET.get('table_name')
    columns = []
    error = None
    conn_id = None
    if raw_connection:
        try:
            conn_id = int(raw_connection)
        except ValueError:
            conn_id = None
    # A non-numeric/invalid value is treated the same as "nothing selected" —
    # only a value that actually parsed counts as a real selection.
    if conn_id is not None and table_name:
        conn = Connection.objects.filter(
            pk=conn_id, kind__in=[KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL]
        ).first()
        if conn:
            try:
                if conn.kind == KIND_POSTGRES:
                    columns = _list_pg_columns(conn, table_name)
                elif conn.kind == KIND_MYSQL:
                    columns = _list_mysql_columns(conn, table_name)
                elif conn.kind == KIND_MSSQL:
                    columns = _list_mssql_columns(conn, table_name)
            except (psycopg2.Error, pymysql.Error, pyodbc.Error) as e:
                error = f'Błąd połączenia z bazą źródłową — {e}'.strip()
    return render(request, 'masking/_columns_options.html', {'columns': columns, 'error': error})
