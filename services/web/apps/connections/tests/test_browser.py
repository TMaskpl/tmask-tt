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

    def test_browse_with_source_path_field_id(self, auth_client, regular_user, make_connection, mocker):
        """field_id id_source_path (transfers/flows context) passes validation and appears in fragment."""
        conn = make_connection(regular_user)
        mocker.patch('apps.connections.views.list_directory', return_value=[])
        resp = auth_client.get(self._url(conn.pk, field_id='id_source_path'))
        assert resp.status_code == 200
        assert 'id_source_path' in resp.content.decode()

    def test_browse_with_dest_path_field_id(self, auth_client, regular_user, make_connection, mocker):
        """field_id id_dest_path (flows context) passes validation and appears in fragment."""
        conn = make_connection(regular_user)
        mocker.patch('apps.connections.views.list_directory', return_value=[])
        resp = auth_client.get(self._url(conn.pk, field_id='id_dest_path'))
        assert resp.status_code == 200
        assert 'id_dest_path' in resp.content.decode()

    def test_list_directory_full_path_does_not_escape_parent(self, auth_client, regular_user, make_connection, mocker):
        """list_directory builds full_path as parent+'/'+name, not posixpath.join which can escape parent."""
        conn = make_connection(regular_user)

        mock_attr = mocker.MagicMock()
        mock_attr.filename = '/etc/passwd'
        mock_attr.st_mode = 0o100644
        mock_attr.st_size = 512

        mock_sftp = mocker.MagicMock()
        mock_sftp.listdir_attr.return_value = [mock_attr]
        mock_client = mocker.MagicMock()
        mock_client.open_sftp.return_value = mock_sftp

        mocker.patch('apps.connections.sftp_utils._build_client', return_value=mock_client)

        from apps.connections.sftp_utils import list_directory
        entries = list_directory(conn, '/home/user')

        assert len(entries) == 1
        assert entries[0].full_path != '/etc/passwd'
        assert '/home/user' in entries[0].full_path
