import pytest
from apps.connections.models import Connection

@pytest.mark.django_db
class TestConnection:
    def test_create_connection_with_password(self, regular_user):
        conn = Connection.objects.create(
            owner=regular_user,
            name='Test Server',
            host='192.168.1.10',
            port=22,
            username='deploy',
            password='secret123',
            protocol='sftp',
        )
        assert conn.pk is not None
        assert conn.password == 'secret123'

    def test_password_stored_encrypted_in_db(self, regular_user):
        conn = Connection.objects.create(
            owner=regular_user, name='S', host='h', port=22,
            username='u', password='mypassword', protocol='sftp',
        )
        from django.db import connection as db_conn
        with db_conn.cursor() as cursor:
            cursor.execute('SELECT password FROM connections_connection WHERE id=%s', [conn.pk])
            raw = cursor.fetchone()[0]
        assert raw != 'mypassword'

    def test_connection_owner_isolation(self, regular_user, admin_user):
        Connection.objects.create(
            owner=admin_user, name='Admin conn', host='h', port=22,
            username='u', password='p', protocol='sftp',
        )
        assert Connection.objects.filter(owner=regular_user).count() == 0

    def test_str_representation(self, regular_user):
        conn = Connection(owner=regular_user, name='Prod', host='1.2.3.4', port=22, protocol='sftp')
        assert 'Prod' in str(conn)
        assert '1.2.3.4' in str(conn)

    def test_default_port_is_22(self, regular_user):
        conn = Connection(owner=regular_user, name='X', host='h', username='u', protocol='sftp')
        assert conn.port == 22

    def test_strict_host_key_checking_default_true(self, regular_user):
        conn = Connection(owner=regular_user, name='X', host='h', username='u', protocol='sftp')
        assert conn.strict_host_key_checking is True

    def test_dry_run_before_transfer_default_false(self, regular_user):
        conn = Connection(
            owner=regular_user, name='X', host='h', username='u', protocol='rsync'
        )
        assert conn.dry_run_before_transfer is False

    def test_verify_checksum_default_false(self, regular_user):
        conn = Connection(
            owner=regular_user, name='X', host='h', username='u', protocol='sftp'
        )
        assert conn.verify_checksum is False

    def test_kind_defaults_to_ssh(self, regular_user):
        conn = Connection(owner=regular_user, name='X', host='h', username='u', protocol='sftp')
        assert conn.kind == 'ssh'

    def test_can_create_postgres_kind_connection(self, regular_user):
        conn = Connection.objects.create(
            owner=regular_user, name='PG', host='10.0.0.5', port=5432,
            username='postgres', password='pass', db_name='proddb', kind='postgres',
        )
        assert conn.pk is not None
        assert conn.kind == 'postgres'
        assert conn.db_name == 'proddb'

    def test_clean_requires_db_name_for_postgres_kind(self, regular_user):
        from django.core.exceptions import ValidationError
        conn = Connection(owner=regular_user, name='PG', host='h', username='u', kind='postgres', db_name='')
        with pytest.raises(ValidationError):
            conn.clean()

    def test_clean_does_not_require_db_name_for_ssh_kind(self, regular_user):
        conn = Connection(owner=regular_user, name='X', host='h', username='u', kind='ssh', protocol='sftp')
        conn.clean()  # should not raise
