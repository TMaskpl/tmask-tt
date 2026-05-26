from django.http import JsonResponse
from .auth import require_api_token
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


@csrf_exempt
@require_POST
@require_api_token
def trigger_connection(request, connection_id):
    return JsonResponse({'status': 'not implemented'}, status=501)


@csrf_exempt
@require_POST
@require_api_token
def trigger_flow(request, flow_id):
    return JsonResponse({'status': 'not implemented'}, status=501)


@require_api_token
def job_status(request, job_id):
    return JsonResponse({'status': 'not implemented'}, status=501)
