import pytest
from apps.connections.forms import ConnectionForm
from apps.connections.models import KIND_MYSQL, KIND_MSSQL


@pytest.mark.django_db
class TestConnectionFormDbKinds:
    def test_mysql_without_db_name_invalid(self):
        form = ConnectionForm({'name': 'x', 'kind': KIND_MYSQL, 'host': 'h', 'port': 3306,
                                'username': 'u', 'password': 'p', 'db_name': ''})
        assert not form.is_valid()

    def test_mssql_without_password_invalid(self):
        form = ConnectionForm({'name': 'x', 'kind': KIND_MSSQL, 'host': 'h', 'port': 1433,
                                'username': 'u', 'db_name': 'db'})
        assert not form.is_valid()
