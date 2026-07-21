from datetime import timedelta

import pytest
from django.utils import timezone

from apps.webhook_deliveries.models import WebhookDeliveryLog
from apps.webhook_deliveries.services import (
    circuit_is_open, record_success, record_failure, log_delivery,
    WEBHOOK_CIRCUIT_THRESHOLD, WEBHOOK_CIRCUIT_COOLDOWN_MINUTES,
)


@pytest.mark.django_db
class TestCircuitIsOpen:
    def test_false_when_never_opened(self, regular_user):
        assert circuit_is_open(regular_user) is False

    def test_true_when_open_until_in_future(self, regular_user):
        regular_user.webhook_circuit_open_until = timezone.now() + timedelta(minutes=5)
        assert circuit_is_open(regular_user) is True

    def test_false_when_open_until_in_past(self, regular_user):
        regular_user.webhook_circuit_open_until = timezone.now() - timedelta(minutes=5)
        assert circuit_is_open(regular_user) is False


@pytest.mark.django_db
class TestRecordFailure:
    def test_increments_failure_count(self, regular_user):
        record_failure(regular_user)
        regular_user.refresh_from_db()
        assert regular_user.webhook_failure_count == 1
        assert regular_user.webhook_circuit_open_until is None

    def test_opens_circuit_at_threshold(self, regular_user):
        regular_user.webhook_failure_count = WEBHOOK_CIRCUIT_THRESHOLD - 1
        regular_user.save(update_fields=['webhook_failure_count'])
        record_failure(regular_user)
        regular_user.refresh_from_db()
        assert regular_user.webhook_failure_count == WEBHOOK_CIRCUIT_THRESHOLD
        assert regular_user.webhook_circuit_open_until is not None
        expected = timezone.now() + timedelta(minutes=WEBHOOK_CIRCUIT_COOLDOWN_MINUTES)
        assert abs((regular_user.webhook_circuit_open_until - expected).total_seconds()) < 5

    def test_stays_closed_below_threshold(self, regular_user):
        regular_user.webhook_failure_count = WEBHOOK_CIRCUIT_THRESHOLD - 2
        regular_user.save(update_fields=['webhook_failure_count'])
        record_failure(regular_user)
        regular_user.refresh_from_db()
        assert regular_user.webhook_circuit_open_until is None


@pytest.mark.django_db
class TestRecordSuccess:
    def test_resets_failure_count_and_closes_circuit(self, regular_user):
        regular_user.webhook_failure_count = 4
        regular_user.webhook_circuit_open_until = timezone.now() + timedelta(minutes=10)
        regular_user.save(update_fields=['webhook_failure_count', 'webhook_circuit_open_until'])
        record_success(regular_user)
        regular_user.refresh_from_db()
        assert regular_user.webhook_failure_count == 0
        assert regular_user.webhook_circuit_open_until is None

    def test_no_op_when_already_clean(self, regular_user):
        record_success(regular_user)
        regular_user.refresh_from_db()
        assert regular_user.webhook_failure_count == 0
        assert regular_user.webhook_circuit_open_until is None


@pytest.mark.django_db
class TestLogDelivery:
    def test_creates_success_entry(self, regular_user):
        entry = log_delivery(regular_user, None, 'http://hooks.example.com/', success=True)
        assert entry.pk is not None
        assert entry.success is True
        assert entry.skipped is False
        assert WebhookDeliveryLog.objects.count() == 1

    def test_creates_skipped_entry(self, regular_user):
        entry = log_delivery(
            regular_user, None, 'http://hooks.example.com/',
            success=False, skipped=True, error_message='Circuit breaker otwarty',
        )
        assert entry.skipped is True
        assert entry.success is False
        assert entry.error_message == 'Circuit breaker otwarty'
