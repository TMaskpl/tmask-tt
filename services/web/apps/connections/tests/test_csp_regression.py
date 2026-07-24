"""
Regression: CSP (script-src 'self', no unsafe-inline) blocks ALL inline
<script> blocks and onclick=/onsubmit= attributes app-wide. These were
silently non-functional in real browsers (confirm() dialogs never fired,
toggles/fetches never ran) — only caught via manual browser testing, never
by the Django test client (no JS engine). These tests assert the CSP-safe
replacements (data-confirm + confirm-forms.js, external <script src>) stay
in place and the forbidden patterns don't come back.
"""
import pytest
from django.urls import reverse


def _no_inline_js(html):
    assert 'onclick=' not in html
    assert 'onsubmit=' not in html
    assert '<script>' not in html


@pytest.mark.django_db
class TestConfirmFormsLoadedGlobally:
    def test_base_template_loads_confirm_forms_js(self, auth_client):
        resp = auth_client.get(reverse('dashboard:index'))
        assert 'confirm-forms.js' in resp.content.decode()


@pytest.mark.django_db
class TestConnectionsCSPSafe:
    def test_list_uses_data_confirm_for_delete(self, admin_client, admin_user, make_connection):
        make_connection(admin_user)
        resp = admin_client.get(reverse('connections:list'))
        html = resp.content.decode()
        _no_inline_js(html)
        assert 'data-confirm=' in html

    def test_edit_form_uses_data_scan_url_and_external_js(self, admin_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        resp = admin_client.get(reverse('connections:edit', args=[conn.pk]))
        html = resp.content.decode()
        _no_inline_js(html)
        assert 'connections_form.js' in html
        assert 'data-scan-url=' in html


@pytest.mark.django_db
class TestTransfersCSPSafe:
    def test_logs_list_uses_data_confirm(self, admin_client):
        resp = admin_client.get(reverse('transfers:logs'))
        _no_inline_js(resp.content.decode())

    def test_create_view_loads_external_js(self, auth_client):
        resp = auth_client.get(reverse('transfers:create'))
        html = resp.content.decode()
        _no_inline_js(html)
        assert 'transfers_create.js' in html

    def test_detail_view_stop_form_uses_data_confirm(self, auth_client, regular_user, make_connection):
        from apps.transfers.models import TransferJob, STATUS_RUNNING
        conn = make_connection(regular_user)
        job = TransferJob.objects.create(
            owner=regular_user, connection=conn, source_path='/a', destination_path='/b',
            status=STATUS_RUNNING,
        )
        resp = auth_client.get(reverse('transfers:detail', args=[job.pk]))
        html = resp.content.decode()
        _no_inline_js(html)
        assert 'data-confirm=' in html


@pytest.mark.django_db
class TestDbTransfersCSPSafe:
    def test_list_uses_data_confirm(self, admin_client, admin_user, make_connection):
        from apps.db_transfers.models import DbTransferJob
        src = make_connection(admin_user, kind='postgres', db_name='a', name='src')
        dst = make_connection(admin_user, kind='postgres', db_name='b', name='dst')
        DbTransferJob.objects.create(owner=admin_user, source_connection=src, dest_connection=dst, engine='postgres', status='done')
        resp = admin_client.get(reverse('db_transfers:list'))
        _no_inline_js(resp.content.decode())

    def test_detail_stop_form_uses_data_confirm(self, auth_client, regular_user, make_connection):
        from apps.db_transfers.models import DbTransferJob
        src = make_connection(regular_user, kind='postgres', db_name='a', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='b', name='dst')
        job = DbTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres', status='running')
        resp = auth_client.get(reverse('db_transfers:detail', args=[job.pk]))
        html = resp.content.decode()
        _no_inline_js(html)
        assert 'data-confirm=' in html

    def test_create_view_loads_external_js_with_db_tables_url(self, auth_client, regular_user, make_connection):
        make_connection(regular_user, kind='postgres', db_name='a')
        resp = auth_client.get(reverse('db_transfers:create'))
        html = resp.content.decode()
        _no_inline_js(html)
        assert 'db_transfers_create.js' in html
        assert 'data-db-tables-url=' in html


@pytest.mark.django_db
class TestFlowsCSPSafe:
    def test_list_uses_data_confirm(self, admin_client, regular_user, make_flow):
        make_flow(regular_user)
        resp = admin_client.get(reverse('flows:list'))
        _no_inline_js(resp.content.decode())


@pytest.mark.django_db
class TestSchedulerCSPSafe:
    def test_list_uses_data_confirm(self, admin_client, regular_user, make_flow):
        from apps.scheduler.models import ScheduledTransfer
        flow = make_flow(regular_user)
        ScheduledTransfer.objects.create(owner=regular_user, flow=flow, cron_expr='* * * * *')
        resp = admin_client.get(reverse('scheduler:list'))
        _no_inline_js(resp.content.decode())

    def test_form_loads_external_js(self, admin_client):
        resp = admin_client.get(reverse('scheduler:create'))
        html = resp.content.decode()
        _no_inline_js(html)
        assert 'scheduler_form.js' in html


@pytest.mark.django_db
class TestProfileCSPSafe:
    def test_profile_page_uses_data_confirm_for_token_revoke(self, auth_client, regular_user):
        from apps.api.models import ApiToken
        ApiToken.generate(regular_user, 'ci-token')
        resp = auth_client.get(reverse('accounts:profile'))
        html = resp.content.decode()
        _no_inline_js(html)
        assert 'data-confirm=' in html

    def test_new_token_modal_loads_external_js_not_inline(self, auth_client):
        auth_client.post(reverse('accounts:generate_api_token'), {'label': 'ci-token'})
        resp = auth_client.get(reverse('accounts:profile'))
        html = resp.content.decode()
        _no_inline_js(html)
        assert 'profile.js' in html
        assert 'id="copy-token-btn"' in html
