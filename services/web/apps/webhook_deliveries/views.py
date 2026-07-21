from django.shortcuts import render

from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_READONLY
from .models import WebhookDeliveryLog
from .services import circuit_is_open

_PAGE_SIZE = 200


@require_role(ROLE_READONLY)
def webhook_deliveries_list(request):
    deliveries = WebhookDeliveryLog.objects.filter(user=request.user).select_related('job')[:_PAGE_SIZE]
    return render(request, 'webhook_deliveries/list.html', {
        'deliveries': deliveries,
        'circuit_open': circuit_is_open(request.user),
        'circuit_open_until': request.user.webhook_circuit_open_until,
    })
