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
