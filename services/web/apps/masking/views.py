import psycopg2
import pymysql
import pyodbc
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN, ROLE_READONLY
from apps.audit_log.services import log_created, log_updated, log_deleted, diff_fields
from apps.connections.models import Connection, KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL
from apps.connections.pg_utils import list_columns as _list_pg_columns
from apps.connections.mysql_utils import list_columns as _list_mysql_columns
from apps.connections.mssql_utils import list_columns as _list_mssql_columns
from .forms import MaskingRuleForm
from .models import MaskingRule

_MASKING_LIST = 'masking:list'
MASKING_RULE_TRACKED_FIELDS = ['connection', 'table_name', 'column_name', 'faker_provider']


@require_role(ROLE_READONLY)
def masking_list(request):
    rules = MaskingRule.objects.select_related('connection', 'created_by').all()
    return render(request, 'masking/list.html', {'rules': rules})


@require_role(ROLE_ADMIN)
def masking_create(request):
    form = MaskingRuleForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        rule = form.save(commit=False)
        rule.created_by = request.user
        rule.save()
        log_created(request.user, rule)
        return redirect(_MASKING_LIST)
    return render(request, 'masking/form.html', {'form': form, 'action': 'CREATE'})


@require_role(ROLE_ADMIN)
def masking_edit(request, pk):
    rule = get_object_or_404(MaskingRule, pk=pk)
    old = MaskingRule.objects.get(pk=pk)
    form = MaskingRuleForm(request.POST or None, instance=rule)
    if request.method == 'POST' and form.is_valid():
        updated = form.save()
        changes = diff_fields(old, updated, MASKING_RULE_TRACKED_FIELDS)
        log_updated(request.user, updated, changes)
        return redirect(_MASKING_LIST)
    return render(request, 'masking/form.html', {'form': form, 'action': 'EDIT'})


@require_role(ROLE_ADMIN)
@require_POST
def masking_delete(request, pk):
    rule = get_object_or_404(MaskingRule, pk=pk)
    log_deleted(request.user, rule)
    rule.delete()
    return redirect(_MASKING_LIST)


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
