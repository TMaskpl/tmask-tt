import json
import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.connections import portability
from apps.connections.models import Connection


@pytest.mark.django_db
class TestExportView:
    def test_export_requires_login(self, client):
        r = client.post(reverse('connections:export'), {'passphrase': 'x'})
        assert r.status_code == 302
        assert '/accounts/login' in r.url

    def test_export_returns_json_attachment(self, auth_client, regular_user, make_connection):
        make_connection(regular_user, name='C1')
        r = auth_client.post(reverse('connections:export'), {'passphrase': 'pw'})
        assert r.status_code == 200
        assert r['Content-Type'] == 'application/json'
        assert 'attachment' in r['Content-Disposition']
        assert json.loads(r.content)['format'] == 'tmask-transporter-config'

    def test_export_requires_passphrase(self, auth_client):
        r = auth_client.post(reverse('connections:export'), {'passphrase': ''})
        assert r.status_code == 302


@pytest.mark.django_db
class TestImportView:
    def test_import_requires_login(self, client):
        r = client.post(reverse('connections:import'))
        assert r.status_code == 302
        assert '/accounts/login' in r.url

    def test_import_creates_records(self, auth_client, regular_user, admin_user, make_connection):
        make_connection(admin_user, name='Imported', host='9.9.9.9', password='sek')
        data = portability.export_config(admin_user, 'pw')
        upload = SimpleUploadedFile('cfg.json', json.dumps(data).encode(), content_type='application/json')
        r = auth_client.post(reverse('connections:import'), {'passphrase': 'pw', 'file': upload})
        assert r.status_code == 302
        c = Connection.objects.get(owner=regular_user, name='Imported')
        assert c.password == 'sek'

    def test_import_wrong_passphrase_shows_error(self, auth_client, regular_user, admin_user, make_connection):
        make_connection(admin_user, name='X', password='s')
        data = portability.export_config(admin_user, 'right')
        upload = SimpleUploadedFile('cfg.json', json.dumps(data).encode(), content_type='application/json')
        r = auth_client.post(reverse('connections:import'), {'passphrase': 'wrong', 'file': upload}, follow=True)
        assert Connection.objects.filter(owner=regular_user).count() == 0
        assert any('Błędne hasło' in str(m) for m in r.context['messages'])

    def test_import_malformed_file_shows_error(self, auth_client, regular_user):
        upload = SimpleUploadedFile('cfg.json', b'not json', content_type='application/json')
        r = auth_client.post(reverse('connections:import'), {'passphrase': 'pw', 'file': upload}, follow=True)
        assert any('Nieprawidłowy' in str(m) for m in r.context['messages'])
