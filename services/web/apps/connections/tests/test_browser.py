import pytest
from django.urls import reverse
from types import SimpleNamespace


@pytest.mark.django_db
class TestBrowseDirectory:
    def _url(self, pk, path='/', field_id='id_destination_path'):
        return reverse('connections:browse', args=[pk]) + f'?path={path}&field_id={field_id}'

    def test_requires_login(self, client, regular_user, make_connection):
        conn = make_connection(regular_user)
        resp = client.get(self._url(conn.pk))
        assert resp.status_code == 302
        assert '/login/' in resp['Location']

    def test_returns_fragment_for_valid_path(self, auth_client, regular_user, make_connection, mocker):
        conn = make_connection(regular_user)
        entries = [
            SimpleNamespace(name='docs', is_dir=True, full_path='/docs', size=None),
            SimpleNamespace(name='file.txt', is_dir=False, full_path='/file.txt', size=512),
        ]
        mocker.patch('apps.connections.views.list_directory', return_value=entries)

        resp = auth_client.get(self._url(conn.pk))

        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'docs' in content
        assert 'file.txt' in content

    def test_returns_404_for_other_users_connection(self, auth_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        resp = auth_client.get(self._url(conn.pk))
        assert resp.status_code == 404

    def test_renders_error_message_on_ssh_failure(self, auth_client, regular_user, make_connection, mocker):
        conn = make_connection(regular_user)
        mocker.patch(
            'apps.connections.views.list_directory',
            side_effect=Exception('Connection refused'),
        )

        resp = auth_client.get(self._url(conn.pk))

        assert resp.status_code == 200
        assert 'Connection refused' in resp.content.decode()

    def test_empty_directory_shows_empty_message(self, auth_client, regular_user, make_connection, mocker):
        conn = make_connection(regular_user)
        mocker.patch('apps.connections.views.list_directory', return_value=[])

        resp = auth_client.get(self._url(conn.pk))

        assert resp.status_code == 200
        assert 'pusty katalog' in resp.content.decode()

    def test_field_id_passed_through_to_fragment(self, auth_client, regular_user, make_connection, mocker):
        conn = make_connection(regular_user)
        mocker.patch('apps.connections.views.list_directory', return_value=[])

        resp = auth_client.get(self._url(conn.pk, field_id='id_dest_path'))

        assert resp.status_code == 200
        assert 'id_dest_path' in resp.content.decode()
