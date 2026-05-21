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
