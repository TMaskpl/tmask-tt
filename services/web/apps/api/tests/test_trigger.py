import json
import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestTriggerConnectionEndpoint:
    def _url(self, connection_id):
        return reverse('api:trigger_connection', args=[connection_id])

    def _post(self, client, connection_id, raw_key, body):
        return client.post(
            self._url(connection_id),
            data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )

    def test_valid_trigger_returns_202_with_job_id(
        self, client, regular_user, make_connection, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.current_app.send_task')
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, conn.pk, raw_key, {
            'source_path': '/data/file.tar',
            'destination_path': '/backup/',
        })
        assert response.status_code == 202
        data = response.json()
        assert 'job_id' in data
        assert isinstance(data['job_id'], int)

    def test_valid_trigger_creates_transfer_job(
        self, client, regular_user, make_connection, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.current_app.send_task')
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        self._post(client, conn.pk, raw_key, {
            'source_path': '/data/file.tar',
            'destination_path': '/backup/',
        })
        from apps.transfers.models import TransferJob
        job = TransferJob.objects.get(owner=regular_user, connection=conn)
        assert job.source_path == '/data/file.tar'
        assert job.destination_path == '/backup/'

    def test_valid_trigger_calls_celery_task(
        self, client, regular_user, make_connection, make_api_token, mocker
    ):
        mock_delay = mocker.patch('apps.api.views.current_app.send_task')
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, conn.pk, raw_key, {
            'source_path': '/data/file.tar',
            'destination_path': '/backup/',
        })
        data = response.json()
        mock_delay.assert_called_once_with('transfers.execute', kwargs={'job_id': data['job_id']})

    def test_wrong_owner_connection_returns_404(
        self, client, regular_user, admin_user, make_connection, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.current_app.send_task')
        other_conn = make_connection(admin_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, other_conn.pk, raw_key, {
            'source_path': '/data/file.tar',
            'destination_path': '/backup/',
        })
        assert response.status_code == 404

    def test_missing_source_path_returns_400(
        self, client, regular_user, make_connection, make_api_token
    ):
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, conn.pk, raw_key, {
            'destination_path': '/backup/',
        })
        assert response.status_code == 400
        assert 'source_path' in response.json()['error']

    def test_missing_destination_path_returns_400(
        self, client, regular_user, make_connection, make_api_token
    ):
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, conn.pk, raw_key, {
            'source_path': '/data/file.tar',
        })
        assert response.status_code == 400
        assert 'destination_path' in response.json()['error']

    def test_no_token_returns_403(self, client, regular_user, make_connection):
        conn = make_connection(regular_user)
        response = client.post(
            self._url(conn.pk),
            data=json.dumps({'source_path': '/x', 'destination_path': '/y'}),
            content_type='application/json',
        )
        assert response.status_code == 403

    def test_get_method_returns_405(self, client, regular_user, make_connection, make_api_token):
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = client.get(
            self._url(conn.pk),
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )
        assert response.status_code == 405


@pytest.mark.django_db
class TestTriggerFlowEndpoint:
    def _url(self, flow_id):
        return reverse('api:trigger_flow', args=[flow_id])

    def _post(self, client, flow_id, raw_key, body=None):
        return client.post(
            self._url(flow_id),
            data=json.dumps(body or {}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )

    def test_valid_trigger_returns_202_with_job_id(
        self, client, regular_user, make_flow, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.current_app.send_task')
        flow = make_flow(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, flow.pk, raw_key)
        assert response.status_code == 202
        assert 'job_id' in response.json()

    def test_valid_trigger_creates_job_with_flow_paths(
        self, client, regular_user, make_flow, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.current_app.send_task')
        flow = make_flow(regular_user)
        _, raw_key = make_api_token(regular_user)
        self._post(client, flow.pk, raw_key)
        from apps.transfers.models import TransferJob
        job = TransferJob.objects.get(owner=regular_user, flow=flow)
        assert job.source_path == flow.source_path
        assert job.destination_path == flow.dest_path

    def test_wrong_owner_flow_returns_404(
        self, client, regular_user, admin_user, make_flow, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.current_app.send_task')
        other_flow = make_flow(admin_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, other_flow.pk, raw_key)
        assert response.status_code == 404

    def test_no_token_returns_403(self, client, regular_user, make_flow):
        flow = make_flow(regular_user)
        response = client.post(
            self._url(flow.pk),
            data=json.dumps({}),
            content_type='application/json',
        )
        assert response.status_code == 403

    def test_get_method_returns_405(self, client, regular_user, make_flow, make_api_token):
        flow = make_flow(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = client.get(self._url(flow.pk), HTTP_AUTHORIZATION=f'Token {raw_key}')
        assert response.status_code == 405
