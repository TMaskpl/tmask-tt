from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.webhook_deliveries.models import WebhookDeliveryLog


@pytest.mark.django_db
class TestWebhookDeliveriesList:
    def test_requires_login(self, client):
        response = client.get(reverse('webhook_deliveries:list'))
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_regular_user_can_view_own_page(self, auth_client):
        response = auth_client.get(reverse('webhook_deliveries:list'))
        assert response.status_code == 200

    def test_shows_only_own_deliveries_newest_first(self, auth_client, regular_user, admin_user):
        mine_older = WebhookDeliveryLog.objects.create(
            user=regular_user, url='http://a.example.com/', success=True,
        )
        mine_newer = WebhookDeliveryLog.objects.create(
            user=regular_user, url='http://b.example.com/', success=False,
        )
        WebhookDeliveryLog.objects.create(
            user=admin_user, url='http://not-mine.example.com/', success=True,
        )
        response = auth_client.get(reverse('webhook_deliveries:list'))
        deliveries = list(response.context['deliveries'])
        assert [d.pk for d in deliveries] == [mine_newer.pk, mine_older.pk]

    def test_circuit_open_false_by_default(self, auth_client):
        response = auth_client.get(reverse('webhook_deliveries:list'))
        assert response.context['circuit_open'] is False

    def test_circuit_open_true_when_user_locked(self, auth_client, regular_user):
        regular_user.webhook_circuit_open_until = timezone.now() + timedelta(minutes=10)
        regular_user.save(update_fields=['webhook_circuit_open_until'])
        response = auth_client.get(reverse('webhook_deliveries:list'))
        assert response.context['circuit_open'] is True
        assert 'CIRCUIT BREAKER' in response.content.decode()
