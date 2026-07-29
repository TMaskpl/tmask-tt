import pytest
from apps.connections.models import Connection, KIND_POSTGRES, KIND_SSH
from apps.masking.forms import MaskingRuleForm
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


class TestMaskingRuleForm:
    def test_connection_queryset_excludes_ssh_connections(self):
        owner = User.objects.create_user(username='o3', password='x')
        Connection.objects.create(
            owner=owner, name='ssh-host', host='h', port=22, username='u', kind=KIND_SSH,
        )
        pg = Connection.objects.create(
            owner=owner, name='pg', host='h', port=5432, username='u', password='p',
            kind=KIND_POSTGRES, db_name='db',
        )
        form = MaskingRuleForm()
        assert list(form.fields['connection'].queryset) == [pg]
