import json
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.connections.models import Connection
from apps.flows.models import Flow
from apps.transfers.forms import _validate_transfer_path
from apps.transfers.models import TransferJob
from apps.transfers.tasks import execute_transfer
from .auth import require_api_token


@csrf_exempt
@require_POST
@require_api_token
def trigger_connection(request, connection_id):
    try:
        connection = Connection.objects.get(pk=connection_id, owner=request.api_user)
    except Connection.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        data = {}

    source_path = data.get('source_path', '').strip()
    destination_path = data.get('destination_path', '').strip()

    if not source_path:
        return JsonResponse({'error': 'source_path required'}, status=400)
    if not destination_path:
        return JsonResponse({'error': 'destination_path required'}, status=400)

    try:
        _validate_transfer_path(source_path)
        _validate_transfer_path(destination_path)
    except ValidationError as exc:
        return JsonResponse({'error': exc.message}, status=400)

    job = TransferJob.objects.create(
        owner=request.api_user,
        connection=connection,
        source_path=source_path,
        destination_path=destination_path,
    )
    execute_transfer.delay(job_id=job.pk)
    return JsonResponse({'job_id': job.pk}, status=202)


@csrf_exempt
@require_POST
@require_api_token
def trigger_flow(request, flow_id):
    try:
        flow = Flow.objects.get(pk=flow_id, owner=request.api_user)
    except Flow.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    job = TransferJob.objects.create(
        owner=request.api_user,
        flow=flow,
        source_path=flow.source_path,
        destination_path=flow.dest_path,
    )
    execute_transfer.delay(job_id=job.pk)
    return JsonResponse({'job_id': job.pk}, status=202)


@require_api_token
def job_status(request, job_id):
    try:
        job = TransferJob.objects.get(pk=job_id, owner=request.api_user)
    except TransferJob.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    return JsonResponse({
        'job_id': job.pk,
        'status': job.status,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        'error': job.error_message,
    })
