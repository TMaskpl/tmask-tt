import pytest
from django.db.utils import IntegrityError
from apps.connections.models import Connection, KIND_POSTGRES
from apps.masking.models import MaskingRule
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def _make_connection(**kwargs):
    defaults = {
        'name': 'prod-pg', 'host': '10.0.0.1', 'port': 5432, 'username': 'postgres',
        'password': 'pw', 'kind': KIND_POSTGRES, 'db_name': 'proddb',
    }
    defaults.update(kwargs)
    owner = User.objects.create_user(username='owner', password='x')
    return Connection.objects.create(owner=owner, **defaults)


class TestMaskingRule:
    def test_str_includes_connection_table_column_and_provider_label(self):
        conn = _make_connection()
        rule = MaskingRule.objects.create(
            connection=conn, table_name='users', column_name='email', faker_provider='email',
        )
        assert str(rule) == 'prod-pg.users.email → E-mail'

    def test_unique_together_connection_table_column(self):
        conn = _make_connection()
        MaskingRule.objects.create(
            connection=conn, table_name='users', column_name='email', faker_provider='email',
        )
        with pytest.raises(IntegrityError):
            MaskingRule.objects.create(
                connection=conn, table_name='users', column_name='email', faker_provider='name',
            )
