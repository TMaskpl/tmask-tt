from django.http import HttpResponse
from prometheus_client import CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST

from .auth import require_metrics_token
from .collectors import TmaskCollector


@require_metrics_token
def metrics_view(request):
    registry = CollectorRegistry()
    registry.register(TmaskCollector())
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
