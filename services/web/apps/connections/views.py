import io
import json
import posixpath
import re
import socket
from datetime import date

import paramiko
import psycopg2
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN, ROLE_READONLY
from .portability import export_config, import_config, PassphraseError
from .forms import ConnectionForm
from .models import Connection, KIND_POSTGRES
from .sftp_utils import list_directory, build_breadcrumbs
from .ssh_tester import test_connection as _test_connection
from .pg_tester import test_connection as _test_pg_connection
from .pg_utils import list_tables as _list_pg_tables

_CONNECTIONS_LIST = 'connections:list'
_MAX_IMPORT_BYTES = 1024 * 1024

@require_role(ROLE_READONLY)
def connection_list(request):
    connections = Connection.objects.all()
    return render(request, 'connections/list.html', {'connections': connections})

@require_role(ROLE_ADMIN)
def connection_create(request):
    form = ConnectionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        conn = form.save(commit=False)
        conn.owner = request.user
        conn.save()
        return redirect(_CONNECTIONS_LIST)
    return render(request, 'connections/form.html', {'form': form, 'action': 'CREATE'})

@require_role(ROLE_ADMIN)
def connection_edit(request, pk):
    conn = get_object_or_404(Connection, pk=pk)
    form = ConnectionForm(request.POST or None, instance=conn)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect(_CONNECTIONS_LIST)
    return render(request, 'connections/form.html', {'form': form, 'action': 'EDIT', 'conn': conn})

@require_role(ROLE_ADMIN)
@require_POST
def connection_delete(request, pk):
    conn = get_object_or_404(Connection, pk=pk)
    conn.delete()
    return redirect(_CONNECTIONS_LIST)

@require_role(ROLE_READONLY)
def connection_test(request, pk):
    conn = get_object_or_404(Connection, pk=pk)
    if conn.kind == KIND_POSTGRES:
        result = _test_pg_connection(conn)
    else:
        result = _test_connection(conn)
    return render(request, 'connections/_test_result.html', {'result': result})

@require_role(ROLE_ADMIN)
def connection_scan_hostkey(request, pk):
    conn = get_object_or_404(Connection, pk=pk)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507 — scan_hostkey view is designed to discover unknown host keys
    host_key = None
    try:
        connect_kwargs = {
            'hostname': conn.host,
            'port': conn.port,
            'username': conn.username,
            'timeout': 10,
            'look_for_keys': False,
            'allow_agent': False,
        }
        if conn.ssh_key:
            connect_kwargs['pkey'] = paramiko.PKey.from_private_key(io.StringIO(conn.ssh_key))
        elif conn.password:
            connect_kwargs['password'] = conn.password
        try:
            client.connect(**connect_kwargs)
        except paramiko.AuthenticationException:
            pass
        transport = client.get_transport()
        if transport:
            host_key = transport.get_remote_server_key()
    except (socket.timeout, socket.gaierror):
        return JsonResponse({'success': False, 'message': f'CONNECTION TIMEOUT — {conn.host} nieosiągalny'})
    except paramiko.SSHException as e:
        return JsonResponse({'success': False, 'message': f'SSH ERROR — {e}'})
    finally:
        client.close()

    if not host_key:
        return JsonResponse({'success': False, 'message': 'Nie udało się pobrać klucza hosta'})

    known_host_entry = f'{conn.host} {host_key.get_name()} {host_key.get_base64()}'
    return JsonResponse({'success': True, 'known_host_key': known_host_entry})


@require_role(ROLE_READONLY)
def browse_directory(request, pk):
    connection = get_object_or_404(Connection, pk=pk)
    raw_path = request.GET.get('path', '/')
    path = '/' + posixpath.normpath(raw_path).lstrip('/')
    field_id = request.GET.get('field_id', '')
    if not re.match(r'^[A-Za-z0-9_-]{1,64}$', field_id):
        field_id = ''
    try:
        entries = list_directory(connection, path)
        error = None
    except Exception as e:
        entries = []
        error = str(e)
    return render(request, 'connections/browser_fragment.html', {
        'entries': entries,
        'breadcrumbs': build_breadcrumbs(path),
        'error': error,
        'conn_pk': pk,
        'current_path': path,
        'field_id': field_id,
    })


@require_role(ROLE_READONLY)
def connection_pg_tables(request):
    raw_source_connection = request.GET.get('source_connection')
    tables = []
    error = None
    conn_id = None
    if raw_source_connection:
        try:
            conn_id = int(raw_source_connection)
        except ValueError:
            conn_id = None
    # A non-numeric/invalid value is treated the same as "nothing selected" —
    # only a value that actually parsed counts as a real selection for the template.
    source_connection = conn_id
    if conn_id is not None:
        conn = Connection.objects.filter(pk=conn_id, kind=KIND_POSTGRES).first()
        if conn:
            try:
                tables = _list_pg_tables(conn)
            except psycopg2.Error as e:
                error = f'Błąd połączenia z bazą źródłową — {e}'.strip()
    return render(request, 'connections/_pg_tables_options.html', {
        'tables': tables,
        'source_connection': source_connection,
        'error': error,
    })


@require_role(ROLE_ADMIN)
@require_POST
def connection_export(request):
    passphrase = request.POST.get('passphrase', '')
    if not passphrase:
        messages.error(request, 'Podaj hasło do zaszyfrowania eksportu.')
        return redirect(_CONNECTIONS_LIST)
    data = export_config(request.user, passphrase)
    response = JsonResponse(data)
    response['Content-Disposition'] = (
        f'attachment; filename=tmask-config-{date.today().isoformat()}.json'
    )
    return response


@require_role(ROLE_ADMIN)
@require_POST
def connection_import(request):
    passphrase = request.POST.get('passphrase', '')
    upload = request.FILES.get('file')
    if not passphrase or upload is None:
        messages.error(request, 'Wybierz plik i podaj hasło.')
        return redirect(_CONNECTIONS_LIST)
    if upload.size > _MAX_IMPORT_BYTES:
        messages.error(request, 'Plik jest za duży (limit 1 MB).')
        return redirect(_CONNECTIONS_LIST)
    try:
        data = json.loads(upload.read().decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        messages.error(request, 'Nieprawidłowy plik konfiguracji.')
        return redirect(_CONNECTIONS_LIST)
    try:
        result = import_config(request.user, data, passphrase)
    except PassphraseError:
        messages.error(request, 'Błędne hasło lub uszkodzony plik.')
        return redirect(_CONNECTIONS_LIST)
    except (ValueError, KeyError):
        messages.error(request, 'Nieprawidłowy plik konfiguracji.')
        return redirect(_CONNECTIONS_LIST)
    messages.success(
        request,
        f'Dodano {result.conn_added} połączeń (pominięto {result.conn_skipped}), '
        f'{result.flow_added} flows (pominięto {result.flow_skipped}, '
        f'nierozwiązanych {result.flow_unresolved}).'
    )
    return redirect(_CONNECTIONS_LIST)
