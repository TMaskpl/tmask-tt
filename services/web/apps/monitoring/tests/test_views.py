from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestMetricsView:
    def test_requires_bearer_token(self, client):
        response = client.get(reverse('monitoring:metrics'))
        assert response.status_code == 401

    def test_rejects_wrong_token(self, client, settings):
        settings.METRICS_TOKEN = 'correct-token'
        response = client.get(reverse('monitoring:metrics'), HTTP_AUTHORIZATION='Bearer wrong-token')
        assert response.status_code == 401

    def test_rejects_non_ascii_token_with_401_not_500(self, client, settings):
        settings.METRICS_TOKEN = 'correct-token'
        response = client.get(reverse('monitoring:metrics'), HTTP_AUTHORIZATION='Bearer \xff\xff')
        assert response.status_code == 401

    def test_returns_prometheus_text_with_correct_token(self, client, settings):
        settings.METRICS_TOKEN = 'correct-token'
        with patch('apps.monitoring.collectors.redis.Redis') as MockRedis:
            MockRedis.from_url.return_value.llen.return_value = 0
            response = client.get(reverse('monitoring:metrics'), HTTP_AUTHORIZATION='Bearer correct-token')
        assert response.status_code == 200
        assert response['Content-Type'].startswith('text/plain')
        body = response.content.decode()
        assert 'tmask_transfer_jobs_total' in body
        assert 'tmask_transfer_duration_seconds' in body
        assert 'tmask_celery_queue_length' in body
