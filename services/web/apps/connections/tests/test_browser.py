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

    def test_returns_200_for_other_users_connection(self, auth_client, admin_user, make_connection, mocker):
        conn = make_connection(admin_user)
        mocker.patch('apps.connections.views.list_directory', return_value=[])
        resp = auth_client.get(self._url(conn.pk))
        assert resp.status_code == 200

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

    def test_fragment_offers_current_directory_selection(self, auth_client, regular_user, make_connection, mocker):
        """A destination folder (e.g. /tmp) must be selectable directly. Directories are
        navigable (data-browse-open) but the current directory itself needs a 'use this
        folder' action carrying data-browse-select=current_path — otherwise browsing into
        a folder and closing leaves the destination field empty."""
        conn = make_connection(regular_user)
        mocker.patch('apps.connections.views.list_directory', return_value=[])
        resp = auth_client.get(self._url(conn.pk, path='/tmp'))
        assert resp.status_code == 200
        assert 'data-browse-select="/tmp"' in resp.content.decode()

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


@pytest.mark.django_db
class TestBrowseButtonCSPRegression:
    """Regression: BROWSE button must use data-browse-open, never onclick handlers.
    Inline onclick was CSP-blocked — this test prevents that regression."""

    def test_transfer_create_browse_button_uses_data_attribute(self, auth_client, regular_user, make_connection):
        make_connection(regular_user)
        resp = auth_client.get(reverse('transfers:create'))
        assert resp.status_code == 200
        html = resp.content.decode()
        assert 'data-browse-open' in html
        assert 'onclick' not in html

    def test_transfer_create_loads_browser_js_not_inline(self, auth_client):
        resp = auth_client.get(reverse('transfers:create'))
        assert resp.status_code == 200
        html = resp.content.decode()
        assert 'browser.js' in html
        assert 'function openBrowser' not in html

    def test_flows_form_browse_button_uses_data_attribute(self, admin_client, regular_user, make_connection):
        make_connection(regular_user)
        resp = admin_client.get(reverse('flows:create'))
        assert resp.status_code == 200
        html = resp.content.decode()
        assert 'data-browse-open' in html
        assert 'onclick' not in html

    def test_browse_fragment_uses_data_attributes_not_onclick(self, auth_client, regular_user, make_connection, mocker):
        conn = make_connection(regular_user)
        from types import SimpleNamespace
        entries = [
            SimpleNamespace(name='subdir', is_dir=True, full_path='/subdir', size=None),
            SimpleNamespace(name='file.txt', is_dir=False, full_path='/file.txt', size=128),
        ]
        mocker.patch('apps.connections.views.list_directory', return_value=entries)
        resp = auth_client.get(
            reverse('connections:browse', args=[conn.pk]) + '?path=/&field_id=id_source_path'
        )
        assert resp.status_code == 200
        html = resp.content.decode()
        assert 'data-browse-open' in html or 'data-browse-select' in html
        assert 'onclick' not in html

    def test_browse_fragment_path_with_hyphen_not_unicode_escaped(self, auth_client, regular_user, make_connection, mocker):
        """Regression: escapejs turned /tmp/srv1/dn-gpg.txt into /tmp/srv1/dn-gpg.txt in data attrs."""
        conn = make_connection(regular_user)
        from types import SimpleNamespace
        entries = [
            SimpleNamespace(name='dn-gpg.txt', is_dir=False, full_path='/tmp/srv1/dn-gpg.txt', size=10),
        ]
        mocker.patch('apps.connections.views.list_directory', return_value=entries)
        resp = auth_client.get(
            reverse('connections:browse', args=[conn.pk]) + '?path=/tmp/srv1&field_id=id_source_path'
        )
        assert resp.status_code == 200
        html = resp.content.decode()
        assert '/tmp/srv1/dn-gpg.txt' in html
        assert '\\u002D' not in html
