import pytest

@pytest.fixture
def admin_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username='admin_test',
        password='testpass123',
        role='admin',
    )

@pytest.fixture
def regular_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username='user_test',
        password='testpass123',
        role='user',
    )

@pytest.fixture
def auth_client(client, regular_user):
    client.login(username='user_test', password='testpass123')
    return client

@pytest.fixture
def admin_client(client, admin_user):
    client.login(username='admin_test', password='testpass123')
    return client

@pytest.fixture
def make_connection():
    from apps.connections.models import Connection
    def _make(user, **kwargs):
        defaults = dict(name='Test', host='localhost', port=22,
                        username='u', password='p', protocol='sftp')
        defaults.update(kwargs)
        return Connection.objects.create(owner=user, **defaults)
    return _make

@pytest.fixture
def make_flow():
    from apps.flows.models import Flow
    from apps.connections.models import Connection
    def _make(user, **kwargs):
        src = Connection.objects.create(
            owner=user, name='FlowSrc', host='10.0.0.1', port=22,
            username='u', password='p', protocol='sftp',
        )
        dst = Connection.objects.create(
            owner=user, name='FlowDst', host='10.0.0.2', port=22,
            username='u', password='p', protocol='sftp',
        )
        defaults = dict(
            name='Test Flow',
            source_conn=src, source_path='/data/file.tar',
            dest_conn=dst,   dest_path='/backup/file.tar',
        )
        defaults.update(kwargs)
        return Flow.objects.create(owner=user, **defaults)
    return _make
