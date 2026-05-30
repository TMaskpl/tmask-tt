import io
import os
import stat
import tempfile
from types import SimpleNamespace

import paramiko


def _build_client(connection):
    client = paramiko.SSHClient()
    if connection.strict_host_key_checking:
        if not connection.known_host_key:
            raise ValueError('strict_host_key_checking wymaga known_host_key')
        with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
            f.write(connection.known_host_key)
            tmp_path = f.name
        try:
            client.load_host_keys(tmp_path)
        finally:
            os.unlink(tmp_path)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507 — user disabled strict_host_key_checking
    return client


def list_directory(connection, path):
    """List remote directory entries via SFTP, sorted: dirs first then files."""
    if not connection.password and not connection.ssh_key:
        raise ValueError('Brak danych uwierzytelniania')

    client = _build_client(connection)
    try:
        connect_kwargs = {
            'hostname': connection.host,
            'port': connection.port,
            'username': connection.username,
            'timeout': 10,
            'look_for_keys': False,
            'allow_agent': False,
        }
        if connection.ssh_key:
            try:
                connect_kwargs['pkey'] = paramiko.PKey.from_private_key(io.StringIO(connection.ssh_key))
            except paramiko.SSHException as e:
                raise ValueError(f'Błąd klucza SSH: {e}') from e
        else:
            connect_kwargs['password'] = connection.password

        client.connect(**connect_kwargs)
        sftp = client.open_sftp()
        try:
            attrs = sftp.listdir_attr(path)
        finally:
            sftp.close()
    finally:
        client.close()

    entries = []
    for attr in attrs:
        is_dir = stat.S_ISDIR(attr.st_mode)
        entries.append(SimpleNamespace(
            name=attr.filename,
            is_dir=is_dir,
            full_path=path.rstrip('/') + '/' + attr.filename,
            size=attr.st_size if not is_dir else None,
        ))
    return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))


def build_breadcrumbs(path):
    """Return list of {'label', 'path'} dicts for each component of path."""
    parts = [p for p in path.split('/') if p]
    crumbs = [{'label': '/', 'path': '/'}]
    for i, part in enumerate(parts):
        crumbs.append({
            'label': part,
            'path': '/' + '/'.join(parts[:i + 1]),
        })
    return crumbs
