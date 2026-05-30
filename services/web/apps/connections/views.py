import io
import posixpath
import re
import socket

import paramiko
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .forms import ConnectionForm
from .models import Connection
from .sftp_utils import list_directory, build_breadcrumbs
from .ssh_tester import test_connection as _test_connection

_CONNECTIONS_LIST = 'connections:list'

@login_required
def connection_list(request):
    connections = Connection.objects.filter(owner=request.user)
    return render(request, 'connections/list.html', {'connections': connections})

@login_required
def connection_create(request):
    form = ConnectionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        conn = form.save(commit=False)
        conn.owner = request.user
        conn.save()
        return redirect(_CONNECTIONS_LIST)
    return render(request, 'connections/form.html', {'form': form, 'action': 'CREATE'})

@login_required
def connection_edit(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    form = ConnectionForm(request.POST or None, instance=conn)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect(_CONNECTIONS_LIST)
    return render(request, 'connections/form.html', {'form': form, 'action': 'EDIT', 'conn': conn})

@login_required
@require_POST
def connection_delete(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    conn.delete()
    return redirect(_CONNECTIONS_LIST)

@login_required
def connection_test(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    result = _test_connection(conn)
    return JsonResponse({'success': result.success, 'message': result.message})

@login_required
def connection_scan_hostkey(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
            pass  # transport already has the host key from SSH handshake
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


@login_required
def browse_directory(request, pk):
    connection = get_object_or_404(Connection, pk=pk, owner=request.user)
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
