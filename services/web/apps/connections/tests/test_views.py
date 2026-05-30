import socket
from unittest.mock import MagicMock, patch

import paramiko
import pytest
from django.urls import reverse
from apps.connections.models import Connection

@pytest.mark.django_db
class TestConnectionList:
    def test_requires_login(self, client):
        response = client.get(reverse('connections:list'))
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_shows_only_own_connections(self, auth_client, regular_user, admin_user, make_connection):
        make_connection(regular_user, name='Mine')
        make_connection(admin_user, name='NotMine')
        response = auth_client.get(reverse('connections:list'))
        assert response.status_code == 200
        conns = response.context['connections']
        assert all(c.owner == regular_user for c in conns)

@pytest.mark.django_db
class TestConnectionCreate:
    def test_create_connection(self, auth_client, regular_user):
        response = auth_client.post(reverse('connections:create'), {
            'name': 'New Server', 'host': '10.0.0.1', 'port': 22,
            'username': 'root', 'password': 'pass', 'protocol': 'sftp',
            'compress': False, 'encrypt': False, 'strict_host_key_checking': True,
        })
        assert response.status_code == 302
        assert Connection.objects.filter(owner=regular_user, name='New Server').exists()

    def test_create_fails_without_credentials(self, auth_client):
        response = auth_client.post(reverse('connections:create'), {
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

    def test_returns_404_for_other_users_connection(self, auth_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        response = auth_client.get(reverse('connections:scan_hostkey', args=[conn.pk]))
        assert response.status_code == 404

    def test_returns_host_key_on_success(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_key = MagicMock()
        mock_key.get_name.return_value = 'ssh-rsa'
        mock_key.get_base64.return_value = 'AAAAB3NzaC1yc2EAAAA'
        mock_transport = MagicMock()
        mock_transport.get_remote_server_key.return_value = mock_key
        mock_client = MagicMock()
        mock_client.get_transport.return_value = mock_transport

        with patch('apps.connections.views.paramiko.SSHClient', return_value=mock_client):
            response = auth_client.get(reverse('connections:scan_hostkey', args=[conn.pk]))

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'ssh-rsa' in data['known_host_key']
        assert conn.host in data['known_host_key']

    def test_returns_error_on_network_failure(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_client = MagicMock()
        mock_client.connect.side_effect = socket.gaierror('name resolution failed')
        mock_client.get_transport.return_value = None

        with patch('apps.connections.views.paramiko.SSHClient', return_value=mock_client):
            response = auth_client.get(reverse('connections:scan_hostkey', args=[conn.pk]))

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'TIMEOUT' in data['message']

    def test_captures_key_even_after_auth_failure(self, auth_client, regular_user, make_connection):
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
            response = auth_client.get(reverse('connections:scan_hostkey', args=[conn.pk]))

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'ecdsa-sha2-nistp256' in data['known_host_key']

    def test_returns_error_when_no_transport(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_client = MagicMock()
        mock_client.connect.side_effect = paramiko.AuthenticationException
        mock_client.get_transport.return_value = None

        with patch('apps.connections.views.paramiko.SSHClient', return_value=mock_client):
            response = auth_client.get(reverse('connections:scan_hostkey', args=[conn.pk]))

        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False


@pytest.mark.django_db
class TestConnectionEdit:
    def test_edit_form_renders_with_existing_data(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, name='EditMe', host='10.1.1.1')
        response = auth_client.get(reverse('connections:edit', args=[conn.pk]))
        assert response.status_code == 200
        assert b'EditMe' in response.content

    def test_edit_saves_changes(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, name='Old Name')
        response = auth_client.post(reverse('connections:edit', args=[conn.pk]), {
            'name': 'New Name', 'host': '10.0.0.1', 'port': 22,
            'username': 'root', 'password': 'pass', 'protocol': 'sftp',
            'compress': False, 'encrypt': False, 'strict_host_key_checking': True,
        })
        assert response.status_code == 302
        conn.refresh_from_db()
        assert conn.name == 'New Name'

    def test_edit_404_for_other_users_connection(self, auth_client, admin_user, make_connection):
        conn = make_connection(admin_user, name='AdminConn')
        response = auth_client.get(reverse('connections:edit', args=[conn.pk]))
        assert response.status_code == 404


@pytest.mark.django_db
class TestConnectionTest:
    def test_returns_success_json(self, auth_client, regular_user, make_connection):
        from apps.connections.ssh_tester import SSHTestResult
        conn = make_connection(regular_user)
        with patch('apps.connections.views._test_connection',
                   return_value=SSHTestResult(success=True, message='CONNECTION OK')):
            response = auth_client.get(reverse('connections:test', args=[conn.pk]))
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'CONNECTION OK' in data['message']

    def test_returns_failure_json(self, auth_client, regular_user, make_connection):
        from apps.connections.ssh_tester import SSHTestResult
        conn = make_connection(regular_user)
        with patch('apps.connections.views._test_connection',
                   return_value=SSHTestResult(success=False, message='AUTH FAILED')):
            response = auth_client.get(reverse('connections:test', args=[conn.pk]))
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert 'AUTH FAILED' in data['message']

    def test_404_for_other_users_connection(self, auth_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        response = auth_client.get(reverse('connections:test', args=[conn.pk]))
        assert response.status_code == 404


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

    def test_404_for_other_users_connection(self, auth_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        response = auth_client.get(reverse('connections:browse', args=[conn.pk]))
        assert response.status_code == 404

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
    def test_delete_own_connection(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        response = auth_client.post(reverse('connections:delete', args=[conn.pk]))
        assert response.status_code == 302
        assert not Connection.objects.filter(pk=conn.pk).exists()

    def test_cannot_delete_other_users_connection(self, auth_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        response = auth_client.post(reverse('connections:delete', args=[conn.pk]))
        assert response.status_code == 404
