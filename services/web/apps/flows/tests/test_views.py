import pytest
from django.urls import reverse
from apps.flows.models import Flow
from apps.transfers.models import TransferJob, STATUS_PENDING


@pytest.mark.django_db
class TestFlowListView:
    def test_requires_login(self, client):
        response = client.get(reverse('flows:list'))
        assert response.status_code == 302
        assert '/accounts/login/' in response['Location']

    def test_shows_only_own_flows(self, auth_client, regular_user, admin_user, make_flow):
        make_flow(regular_user, name='My Flow')
        make_flow(admin_user, name='Other Flow')
        response = auth_client.get(reverse('flows:list'))
        assert response.status_code == 200
        assert b'My Flow' in response.content
        assert b'Other Flow' not in response.content


@pytest.mark.django_db
class TestFlowCreateView:
    def test_create_form_renders(self, auth_client):
        response = auth_client.get(reverse('flows:create'))
        assert response.status_code == 200

    def test_create_flow(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, name='Src', host='10.0.0.1')
        dst = make_connection(regular_user, name='Dst', host='10.0.0.2')
        response = auth_client.post(reverse('flows:create'), {
            'name': 'New Flow',
            'source_conn': src.pk,
            'source_path': '/data/file.tar',
            'dest_conn': dst.pk,
            'dest_path': '/backup/file.tar',
        })
        assert response.status_code == 302
        assert Flow.objects.filter(owner=regular_user, name='New Flow').exists()

    def test_cannot_see_other_users_connections(self, auth_client, admin_user, make_connection):
        admin_conn = make_connection(admin_user, name='AdminConn')
        response = auth_client.get(reverse('flows:create'))
        assert response.status_code == 200
        assert b'AdminConn' not in response.content


@pytest.mark.django_db
class TestFlowRunView:
    def test_run_creates_transfer_job(self, auth_client, regular_user, make_flow, mocker, django_capture_on_commit_callbacks):
        mock_delay = mocker.patch('apps.flows.views.current_app.send_task')
        flow = make_flow(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            response = auth_client.post(reverse('flows:run', args=[flow.pk]))
        assert response.status_code == 302
        job = TransferJob.objects.get(owner=regular_user, flow=flow)
        assert job.status == STATUS_PENDING
        assert job.source_path == flow.source_path
        assert job.destination_path == flow.dest_path
        mock_delay.assert_called_once_with('transfers.execute', kwargs={'job_id': job.pk})

    def test_run_requires_post(self, auth_client, regular_user, make_flow):
        flow = make_flow(regular_user)
        response = auth_client.get(reverse('flows:run', args=[flow.pk]))
        assert response.status_code == 405

    def test_cannot_run_other_users_flow(self, auth_client, admin_user, make_flow):
        flow = make_flow(admin_user)
        response = auth_client.post(reverse('flows:run', args=[flow.pk]))
        assert response.status_code == 404


@pytest.mark.django_db
class TestFlowDeleteView:
    def test_delete_removes_flow(self, auth_client, regular_user, make_flow):
        flow = make_flow(regular_user)
        response = auth_client.post(reverse('flows:delete', args=[flow.pk]))
        assert response.status_code == 302
        assert not Flow.objects.filter(pk=flow.pk).exists()

    def test_cannot_delete_other_users_flow(self, auth_client, admin_user, make_flow):
        flow = make_flow(admin_user)
        response = auth_client.post(reverse('flows:delete', args=[flow.pk]))
        assert response.status_code == 404
