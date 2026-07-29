import pytest
from django.test import Client
from unittest.mock import patch
from apps.connections.models import Connection, KIND_POSTGRES
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def readonly_client():
    User.objects.create_user(username='ro', password='x', role='readonly')
    client = Client()
    client.login(username='ro', password='x')
    return client


@pytest.fixture
def pg_connection():
    owner = User.objects.create_user(username='owner2', password='x')
    return Connection.objects.create(
        owner=owner, name='prod-pg', host='h', port=5432, username='u', password='p',
        kind=KIND_POSTGRES, db_name='db',
    )


class TestMaskingColumnsView:
    @patch('apps.masking.views._list_pg_columns')
    def test_returns_maskable_columns_for_postgres_connection(self, mock_list, readonly_client, pg_connection):
        mock_list.return_value = [
            {'name': 'email', 'data_type': 'varchar', 'maskable': True, 'suggested_provider': 'email'},
        ]
        response = readonly_client.get(
            '/masking/columns/', {'connection': pg_connection.pk, 'table_name': 'users'}
        )
        assert response.status_code == 200
        assert b'email (varchar)' in response.content

    def test_missing_params_returns_empty_select(self, readonly_client):
        response = readonly_client.get('/masking/columns/')
        assert response.status_code == 200
        assert b'wybierz kolumn' not in response.content

    def test_non_numeric_connection_param_does_not_crash(self, readonly_client):
        response = readonly_client.get(
            '/masking/columns/', {'connection': 'not-a-number', 'table_name': 'users'}
        )
        assert response.status_code == 200
