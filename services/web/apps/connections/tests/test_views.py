import socket
from unittest.mock import MagicMock, patch

import paramiko
import psycopg2
import pytest
from django.urls import reverse
from apps.connections.models import Connection

@pytest.mark.django_db
class TestConnectionList:
    def test_requires_login(self, client):
        response = client.get(reverse('connections:list'))
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_shows_connections_from_all_users(self, auth_client, regular_user, admin_user, make_connection):
        make_connection(regular_user, name='Mine')
        make_connection(admin_user, name='NotMine')
        response = auth_client.get(reverse('connections:list'))
        assert response.status_code == 200
        conns = response.context['connections']
        assert {c.name for c in conns} == {'Mine', 'NotMine'}

@pytest.mark.django_db
class TestConnectionCreate:
    def test_create_connection(self, admin_client, admin_user):
        response = admin_client.post(reverse('connections:create'), {
            'name': 'New Server', 'kind': 'ssh', 'host': '10.0.0.1', 'port': 22,
            'username': 'root', 'password': 'pass', 'protocol': 'sftp',
            'compress': False, 'encrypt': False, 'strict_host_key_checking': True,
        })
        assert response.status_code == 302
        assert Connection.objects.filter(owner=admin_user, name='New Server').exists()

    def test_create_fails_without_credentials(self, admin_client):
        response = admin_client.post(reverse('connections:create'), {
            'name': 'X', 'host': 'h', 'port': 22, 'username': 'u',
            'protocol': 'sftp', 'compress': False, 'encrypt': False,
            'strict_host_key_checking': True,
        })
        assert response.status_code == 200
        assert response.context['form'].errors

@pytest.mark.django_db
class TestConnectionScanHostkey:
    def test_requires_login(self, client, regular_user, make_connection):
        conn = make_connection(regular_user)
        response = client.get(reverse('connections:scan_hostkey', args=[conn.pk]))
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_admin_can_scan_hostkey_for_other_users_connection(self, admin_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_key = MagicMock()
        mock_key.get_name.return_value = 'ssh-rsa'
        mock_key.get_base64.return_value = 'AAAAB3NzaC1yc2EAAAA'
        mock_transport = MagicMock()
        mock_transport.get_remote_server_key.return_value = mock_key
        mock_client = MagicMock()
        mock_client.get_transport.return_value = mock_transport

        with patch('apps.connections.views.paramiko.SSHClient', return_value=mock_client):
            response = admin_client.get(reverse('connections:scan_hostkey', args=[conn.pk]))

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'ssh-rsa' in data['known_host_key']
        assert conn.host in data['known_host_key']

    def test_returns_host_key_on_success(self, admin_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_key = MagicMock()
        mock_key.get_name.return_value = 'ssh-rsa'
        mock_key.get_base64.return_value = 'AAAAB3NzaC1yc2EAAAA'
        mock_transport = MagicMock()
        mock_transport.get_remote_server_key.return_value = mock_key
        mock_client = MagicMock()
        mock_client.get_transport.return_value = mock_transport

        with patch('apps.connections.views.paramiko.SSHClient', return_value=mock_client):
            response = admin_client.get(reverse('connections:scan_hostkey', args=[conn.pk]))

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'ssh-rsa' in data['known_host_key']
        assert conn.host in data['known_host_key']

    def test_returns_error_on_network_failure(self, admin_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_client = MagicMock()
        mock_client.connect.side_effect = socket.gaierror('name resolution failed')
        mock_client.get_transport.return_value = None

        with patch('apps.connections.views.paramiko.SSHClient', return_value=mock_client):
            response = admin_client.get(reverse('connections:scan_hostkey', args=[conn.pk]))

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'TIMEOUT' in data['message']

    def test_captures_key_even_after_auth_failure(self, admin_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_key = MagicMock()
        mock_key.get_name.return_value = 'ecdsa-sha2-nistp256'
        mock_key.get_base64.return_value = 'AAAAE2VjZHNh'
        mock_transport = MagicMock()
        mock_transport.get_remote_server_key.return_value = mock_key
        mock_client = MagicMock()
        mock_client.connect.side_effect = paramiko.AuthenticationException
        mock_client.get_transport.return_value = mock_transport

        with patch('apps.connections.views.paramiko.SSHClient', return_value=mock_client):
            response = admin_client.get(reverse('connections:scan_hostkey', args=[conn.pk]))

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'ecdsa-sha2-nistp256' in data['known_host_key']

    def test_returns_error_when_no_transport(self, admin_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_client = MagicMock()
        mock_client.connect.side_effect = paramiko.AuthenticationException
        mock_client.get_transport.return_value = None

        with patch('apps.connections.views.paramiko.SSHClient', return_value=mock_client):
            response = admin_client.get(reverse('connections:scan_hostkey', args=[conn.pk]))

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False


@pytest.mark.django_db
class TestConnectionEdit:
    def test_edit_form_renders_with_existing_data(self, admin_client, regular_user, make_connection):
        conn = make_connection(regular_user, name='EditMe', host='10.1.1.1')
        response = admin_client.get(reverse('connections:edit', args=[conn.pk]))
        assert response.status_code == 200
        assert b'EditMe' in response.content

    def test_edit_saves_changes(self, admin_client, regular_user, make_connection):
        conn = make_connection(regular_user, name='Old Name')
        response = admin_client.post(reverse('connections:edit', args=[conn.pk]), {
            'name': 'New Name', 'kind': 'ssh', 'host': '10.0.0.1', 'port': 22,
            'username': 'root', 'password': 'pass', 'protocol': 'sftp',
            'compress': False, 'encrypt': False, 'strict_host_key_checking': True,
        })
        assert response.status_code == 302
        conn.refresh_from_db()
        assert conn.name == 'New Name'

    def test_edit_returns_200_for_other_users_connection(self, admin_client, regular_user, make_connection):
        conn = make_connection(regular_user, name='AdminConn')
        response = admin_client.get(reverse('connections:edit', args=[conn.pk]))
        assert response.status_code == 200

    def test_operator_cannot_edit_connection(self, auth_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        response = auth_client.get(reverse('connections:edit', args=[conn.pk]))
        assert response.status_code == 403

    def test_readonly_cannot_edit_connection(self, readonly_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        response = readonly_client.post(reverse('connections:edit', args=[conn.pk]), {'name': 'Hacked'})
        assert response.status_code == 403


@pytest.mark.django_db
class TestConnectionTest:
    def test_returns_success_html_fragment(self, auth_client, regular_user, make_connection):
        from apps.connections.ssh_tester import SSHTestResult
        conn = make_connection(regular_user)
        with patch('apps.connections.views._test_connection',
                   return_value=SSHTestResult(success=True, message='CONNECTION OK — 10.0.0.1:22')):
            response = auth_client.get(reverse('connections:test', args=[conn.pk]))
        assert response.status_code == 200
        assert response['Content-Type'].startswith('text/html')
        body = response.content.decode()
        assert 'class="test-ok"' in body
        assert 'class="test-fail"' not in body
        # myślnik musi renderować się jako prawdziwy znak unicode, nie jako uciekniety — z JSON
        assert 'CONNECTION OK — 10.0.0.1:22' in body
        assert '\\u2014' not in body

    def test_returns_failure_html_fragment(self, auth_client, regular_user, make_connection):
        from apps.connections.ssh_tester import SSHTestResult
        conn = make_connection(regular_user)
        with patch('apps.connections.views._test_connection',
                   return_value=SSHTestResult(success=False, message='AUTH FAILED — brak danych')):
            response = auth_client.get(reverse('connections:test', args=[conn.pk]))
        assert response.status_code == 200
        body = response.content.decode()
        assert 'class="test-fail"' in body
        assert 'class="test-ok"' not in body
        assert 'AUTH FAILED — brak danych' in body

    def test_returns_200_for_other_users_connection(self, auth_client, admin_user, make_connection):
        from apps.connections.ssh_tester import SSHTestResult
        conn = make_connection(admin_user)
        with patch('apps.connections.views._test_connection',
                   return_value=SSHTestResult(success=True, message='CONNECTION OK')):
            response = auth_client.get(reverse('connections:test', args=[conn.pk]))
        assert response.status_code == 200


@pytest.mark.django_db
class TestBrowseDirectory:
    def test_returns_directory_entries(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_entries = [{'name': 'file.tar', 'is_dir': False, 'size': 1024}]
        with patch('apps.connections.views.list_directory', return_value=mock_entries):
            response = auth_client.get(
                reverse('connections:browse', args=[conn.pk]),
                {'path': '/data/'},
            )
        assert response.status_code == 200
        assert b'file.tar' in response.content

    def test_returns_error_on_sftp_failure(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        with patch('apps.connections.views.list_directory',
                   side_effect=Exception('Permission denied')):
            response = auth_client.get(
                reverse('connections:browse', args=[conn.pk]),
                {'path': '/restricted/'},
            )
        assert response.status_code == 200
        assert b'Permission denied' in response.content

    def test_returns_200_for_other_users_connection(self, auth_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        with patch('apps.connections.views.list_directory', return_value=[]):
            response = auth_client.get(reverse('connections:browse', args=[conn.pk]))
        assert response.status_code == 200

    def test_invalid_field_id_is_sanitized(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        with patch('apps.connections.views.list_directory', return_value=[]):
            response = auth_client.get(
                reverse('connections:browse', args=[conn.pk]),
                {'path': '/', 'field_id': '../../etc/passwd'},
            )
        assert response.status_code == 200
        assert response.context['field_id'] == ''


@pytest.mark.django_db
class TestConnectionDelete:
    def test_delete_own_connection(self, admin_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        response = admin_client.post(reverse('connections:delete', args=[conn.pk]))
        assert response.status_code == 302
        assert not Connection.objects.filter(pk=conn.pk).exists()

    def test_operator_gets_403_deleting_connection(self, auth_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        response = auth_client.post(reverse('connections:delete', args=[conn.pk]))
        assert response.status_code == 403


@pytest.mark.django_db
class TestOrgWideVisibility:
    def test_operator_sees_connection_created_by_another_user(self, auth_client, django_user_model, make_connection):
        other = django_user_model.objects.create_user(username='other1', password='p', role='admin')
        make_connection(other, name='SharedConn')
        resp = auth_client.get('/connections/')
        assert b'SharedConn' in resp.content

    def test_readonly_can_view_connection_list(self, readonly_client, django_user_model, make_connection):
        other = django_user_model.objects.create_user(username='other2', password='p', role='admin')
        make_connection(other, name='VisibleToReadonly')
        resp = readonly_client.get('/connections/')
        assert resp.status_code == 200
        assert b'VisibleToReadonly' in resp.content

    def test_operator_cannot_create_connection(self, auth_client):
        resp = auth_client.post('/connections/new/', {
            'name': 'X', 'host': 'h', 'port': 22, 'username': 'u', 'protocol': 'sftp',
        })
        assert resp.status_code == 403

    def test_readonly_cannot_delete_connection(self, readonly_client, django_user_model, make_connection):
        other = django_user_model.objects.create_user(username='other3', password='p', role='admin')
        conn = make_connection(other)
        resp = readonly_client.post(f'/connections/{conn.pk}/delete/')
        assert resp.status_code == 403

    def test_admin_can_edit_connection_created_by_another_user(self, admin_client, django_user_model, make_connection):
        other = django_user_model.objects.create_user(username='other4', password='p', role='admin')
        conn = make_connection(other, name='ToEdit')
        resp = admin_client.get(f'/connections/{conn.pk}/edit/')
        assert resp.status_code == 200

    def test_operator_can_test_connection_created_by_another_user(self, auth_client, django_user_model, make_connection, monkeypatch):
        from apps.connections import views as connections_views
        other = django_user_model.objects.create_user(username='other5', password='p', role='admin')
        conn = make_connection(other)
        monkeypatch.setattr(
            connections_views, '_test_connection',
            lambda c: type('R', (), {'success': True, 'message': 'ok'})(),
        )
        resp = auth_client.get(f'/connections/{conn.pk}/test/')
        assert resp.status_code == 200


@pytest.mark.django_db
class TestConnectionTestBranchesByKind:
    def test_uses_pg_tester_for_postgres_kind(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        with patch('apps.connections.pg_tester.psycopg2.connect', return_value=mock_conn):
            response = auth_client.get(reverse('connections:test', args=[conn.pk]))
        assert response.status_code == 200
        assert b'CONNECTION OK' in response.content

    def test_uses_ssh_tester_for_ssh_kind(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_client = MagicMock()
        with patch('apps.connections.ssh_tester.paramiko.SSHClient', return_value=mock_client):
            response = auth_client.get(reverse('connections:test', args=[conn.pk]))
        assert response.status_code == 200
        assert b'CONNECTION OK' in response.content


@pytest.mark.django_db
class TestConnectionCreatePostgresKind:
    def test_create_postgres_connection_requires_db_name(self, admin_client):
        response = admin_client.post(reverse('connections:create'), {
            'name': 'PG', 'kind': 'postgres', 'host': '10.0.0.5', 'port': 5432,
            'username': 'postgres', 'password': 'pass',
            'protocol': 'sftp', 'compress': False, 'encrypt': False,
            'strict_host_key_checking': True,
        })
        assert response.status_code == 200
        assert response.context['form'].errors

    def test_create_postgres_connection_success(self, admin_client):
        response = admin_client.post(reverse('connections:create'), {
            'name': 'PG', 'kind': 'postgres', 'host': '10.0.0.5', 'port': 5432,
            'username': 'postgres', 'password': 'pass', 'db_name': 'proddb',
            'protocol': 'sftp', 'compress': False, 'encrypt': False,
            'strict_host_key_checking': True,
        })
        assert response.status_code == 302
        conn = Connection.objects.get(name='PG')
        assert conn.kind == 'postgres'
        assert conn.db_name == 'proddb'


@pytest.mark.django_db
class TestConnectionPgTables:
    def test_returns_options_fragment(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        with patch('apps.connections.views._list_pg_tables', return_value=['users', 'orders']):
            response = auth_client.get(reverse('connections:pg_tables'), {'source_connection': conn.pk})
        assert response.status_code == 200
        assert b'<option value="users">users</option>' in response.content
        assert b'<option value="orders">orders</option>' in response.content

    def test_empty_when_no_connection_id(self, auth_client):
        response = auth_client.get(reverse('connections:pg_tables'))
        assert response.status_code == 200
        assert b'wybierz' in response.content.lower()

    def test_non_numeric_connection_id_does_not_500(self, auth_client):
        response = auth_client.get(reverse('connections:pg_tables'), {'source_connection': 'abc'})
        assert response.status_code == 200
        assert 'wybierz najpierw source connection' in response.content.decode().lower()

    def test_connection_error_renders_distinct_message(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        with patch('apps.connections.views._list_pg_tables', side_effect=psycopg2.OperationalError('unreachable')):
            response = auth_client.get(reverse('connections:pg_tables'), {'source_connection': conn.pk})
        assert response.status_code == 200
        content = response.content.decode().lower()
        assert 'błąd połączenia' in content
        assert 'wybierz najpierw source connection' not in content

    def test_empty_table_list_renders_distinct_message(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        with patch('apps.connections.views._list_pg_tables', return_value=[]):
            response = auth_client.get(reverse('connections:pg_tables'), {'source_connection': conn.pk})
        assert response.status_code == 200
        content = response.content.decode().lower()
        assert 'brak tabel' in content
        assert 'wybierz najpierw source connection' not in content
