from datetime import timedelta

from django.utils import timezone

from .models import WebhookDeliveryLog

WEBHOOK_CIRCUIT_THRESHOLD = 5
WEBHOOK_CIRCUIT_COOLDOWN_MINUTES = 15
CIRCUIT_SKIPPED_MESSAGE = 'Circuit breaker otwarty — dostarczenie pominięte'


def circuit_is_open(user) -> bool:
    return bool(user.webhook_circuit_open_until and user.webhook_circuit_open_until > timezone.now())


def record_success(user) -> None:
    if user.webhook_failure_count or user.webhook_circuit_open_until:
        user.webhook_failure_count = 0
        user.webhook_circuit_open_until = None
        user.save(update_fields=['webhook_failure_count', 'webhook_circuit_open_until'])


def record_failure(user) -> None:
    user.webhook_failure_count += 1
    if user.webhook_failure_count >= WEBHOOK_CIRCUIT_THRESHOLD:
        user.webhook_circuit_open_until = timezone.now() + timedelta(minutes=WEBHOOK_CIRCUIT_COOLDOWN_MINUTES)
    user.save(update_fields=['webhook_failure_count', 'webhook_circuit_open_until'])


def log_delivery(user, job, url: str, *, success: bool, skipped: bool = False, error_message: str = '') -> WebhookDeliveryLog:
    return WebhookDeliveryLog.objects.create(
        user=user, job=job, url=url, success=success, skipped=skipped, error_message=error_message,
    )
