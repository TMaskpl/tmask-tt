import pytest
from apps.connections import portability
from apps.connections.models import Connection


@pytest.mark.django_db
class TestExportConfig:
    def test_export_has_format_version_and_kdf(self, regular_user, make_connection):
        make_connection(regular_user, name='C1')
        data = portability.export_config(regular_user, 'pass123')
        assert data['format'] == 'tmask-transporter-config'
        assert data['version'] == 1
        assert 'salt' in data['kdf']
        assert data['check']

    def test_export_secrets_not_plaintext(self, regular_user, make_connection):
        make_connection(regular_user, name='C1', password='supersecret', ssh_key='PRIVATEKEY')
        data = portability.export_config(regular_user, 'pass123')
        blob = str(data)
        assert 'supersecret' not in blob
        assert 'PRIVATEKEY' not in blob
        row = data['connections'][0]
        assert row['password_enc'] and row['password_enc'] != 'supersecret'

    def test_export_only_owners_records(self, regular_user, admin_user, make_connection):
        make_connection(regular_user, name='Mine')
        make_connection(admin_user, name='Theirs')
        data = portability.export_config(regular_user, 'pass123')
        assert [c['name'] for c in data['connections']] == ['Mine']
