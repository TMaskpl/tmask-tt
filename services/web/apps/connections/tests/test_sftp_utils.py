import stat as stat_module
from types import SimpleNamespace

import pytest

from apps.connections.sftp_utils import build_breadcrumbs, list_directory


def _conn(**kwargs):
    defaults = dict(
        host='localhost', port=22, username='u', password='pass',
        ssh_key=None, strict_host_key_checking=False, known_host_key=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestBuildBreadcrumbs:
    def test_root_returns_single_crumb(self):
        result = build_breadcrumbs('/')
        assert result == [{'label': '/', 'path': '/'}]

    def test_nested_path_returns_all_crumbs(self):
        result = build_breadcrumbs('/home/user')
        assert result == [
            {'label': '/', 'path': '/'},
            {'label': 'home', 'path': '/home'},
            {'label': 'user', 'path': '/home/user'},
        ]

    def test_trailing_slash_ignored(self):
        result = build_breadcrumbs('/home/')
        assert len(result) == 2
        assert result[-1]['path'] == '/home'


class TestListDirectory:
    def test_sorts_dirs_before_files(self, mocker):
        conn = _conn()
        file_attr = SimpleNamespace(
            filename='readme.txt',
            st_mode=stat_module.S_IFREG | 0o644,
            st_size=512,
        )
        dir_attr = SimpleNamespace(
            filename='docs',
            st_mode=stat_module.S_IFDIR | 0o755,
            st_size=4096,
        )
        mock_client = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mock_client)
        mock_sftp = mocker.MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.listdir_attr.return_value = [file_attr, dir_attr]

        result = list_directory(conn, '/')

        assert result[0].name == 'docs'
        assert result[0].is_dir is True
        assert result[1].name == 'readme.txt'
        assert result[1].is_dir is False

    def test_full_path_constructed_correctly(self, mocker):
        conn = _conn()
        attr = SimpleNamespace(
            filename='archive.tar',
            st_mode=stat_module.S_IFREG | 0o644,
            st_size=1024,
        )
        mock_client = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mock_client)
        mock_sftp = mocker.MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.listdir_attr.return_value = [attr]

        result = list_directory(conn, '/home/user')

        assert result[0].full_path == '/home/user/archive.tar'

    def test_empty_directory_returns_empty_list(self, mocker):
        conn = _conn()
        mock_client = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mock_client)
        mock_sftp = mocker.MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.listdir_attr.return_value = []

        result = list_directory(conn, '/')

        assert result == []

    def test_uses_ssh_key_when_provided(self, mocker):
        conn = _conn(ssh_key='--- FAKE KEY ---', password=None)
        mock_client = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mock_client)
        mock_pkey = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.PKey.from_private_key', return_value=mock_pkey)
        mock_sftp = mocker.MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.listdir_attr.return_value = []

        list_directory(conn, '/')

        call_kwargs = mock_client.connect.call_args.kwargs
        assert call_kwargs['pkey'] == mock_pkey
        assert 'password' not in call_kwargs

    def test_raises_when_no_credentials(self):
        conn = _conn(password=None, ssh_key=None)

        with pytest.raises(ValueError, match='Brak danych uwierzytelniania'):
            list_directory(conn, '/')

    def test_raises_when_strict_host_key_missing(self, mocker):
        conn = _conn(strict_host_key_checking=True, known_host_key=None)
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mocker.MagicMock())

        with pytest.raises(ValueError, match='strict_host_key_checking wymaga known_host_key'):
            list_directory(conn, '/')

    def test_closes_connection_on_sftp_error(self, mocker):
        conn = _conn()
        mock_client = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mock_client)
        mock_sftp = mocker.MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.listdir_attr.side_effect = IOError('permission denied')

        with pytest.raises(IOError):
            list_directory(conn, '/restricted')

        mock_sftp.close.assert_called_once()
        mock_client.close.assert_called_once()
