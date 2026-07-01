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


@pytest.mark.django_db
class TestImportConfig:
    def test_roundtrip_restores_secrets(self, regular_user, admin_user, make_connection):
        make_connection(regular_user, name='Prod', host='1.2.3.4',
                        password='topsecret', ssh_key='KEYDATA')
        data = portability.export_config(regular_user, 'pw')
        result = portability.import_config(admin_user, data, 'pw')
        assert result.conn_added == 1
        c = Connection.objects.get(owner=admin_user, name='Prod')
        assert c.host == '1.2.3.4'
        assert c.password == 'topsecret'
        assert c.ssh_key == 'KEYDATA'

    def test_import_wrong_passphrase_raises(self, regular_user, admin_user, make_connection):
        make_connection(regular_user, name='Prod', password='x')
        data = portability.export_config(regular_user, 'right')
        with pytest.raises(portability.PassphraseError):
            portability.import_config(admin_user, data, 'wrong')
        assert Connection.objects.filter(owner=admin_user).count() == 0

    def test_import_skips_existing_by_name(self, regular_user, admin_user, make_connection):
        make_connection(regular_user, name='Dup', host='orig')
        data = portability.export_config(regular_user, 'pw')
        make_connection(admin_user, name='Dup', host='local')
        result = portability.import_config(admin_user, data, 'pw')
        assert result.conn_added == 0
        assert result.conn_skipped == 1
        assert Connection.objects.get(owner=admin_user, name='Dup').host == 'local'

    def test_flow_references_resolved_by_name(self, regular_user, admin_user, make_flow):
        make_flow(regular_user, name='Relay1')
        data = portability.export_config(regular_user, 'pw')
        result = portability.import_config(admin_user, data, 'pw')
        assert result.flow_added == 1
        from apps.flows.models import Flow
        fl = Flow.objects.get(owner=admin_user, name='Relay1')
        assert fl.source_conn.owner == admin_user
        assert fl.source_conn.name == 'FlowSrc'
        assert fl.dest_conn.name == 'FlowDst'

    def test_flow_with_missing_connection_unresolved(self, regular_user, admin_user, make_flow):
        make_flow(regular_user, name='Relay1')
        data = portability.export_config(regular_user, 'pw')
        data['connections'] = []  # usuń połączenia, flow nie ma czego rozwiązać
        result = portability.import_config(admin_user, data, 'pw')
        assert result.flow_added == 0
        assert result.flow_unresolved == 1

    def test_import_corrupt_secret_token_raises(self, regular_user, admin_user, make_connection):
        # check przechodzi (poprawne hasło), ale token sekretu uszkodzony → PassphraseError, brak zapisu
        make_connection(regular_user, name='C', password='secret')
        data = portability.export_config(regular_user, 'pw')
        data['connections'][0]['password_enc'] = data['check'][:-4] + 'XXXX'
        with pytest.raises(portability.PassphraseError):
            portability.import_config(admin_user, data, 'pw')
        assert Connection.objects.filter(owner=admin_user).count() == 0
