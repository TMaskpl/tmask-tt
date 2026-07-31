import json
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.models import ROLE_LEVEL, ROLE_OPERATOR
from apps.connections.models import Connection
from apps.flows.models import Flow
from apps.transfers.forms import _validate_transfer_path
from apps.transfers.models import TransferJob, STATUS_CHOICES
from celery import current_app
from .auth import require_api_token

_NOT_FOUND = 'Not found'
_FORBIDDEN = 'Operator or admin role required'
_LIST_PAGE_SIZE = 200


def _parse_status_filter(request, status_choices):
    """Reads ?status= from the query string and validates it against the
    given model's STATUS_CHOICES. Returns (status_or_None, error_response_or_None) —
    exactly one of the two is non-None."""
    status = request.GET.get('status')
    if not status:
        return None, None
    valid_values = [choice for choice, _ in status_choices]
    if status not in valid_values:
        error = JsonResponse(
            {'error': f"Invalid status. Choices: {', '.join(valid_values)}"},
            status=400,
        )
        return None, error
    return status, None


def _serialize_transfer_job(job):
    return {
        'job_id': job.pk,
        'status': job.status,
        'connection_id': job.connection_id,
        'flow_id': job.flow_id,
        'source_path': job.source_path,
        'destination_path': job.destination_path,
        'created_at': job.created_at.isoformat(),
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        'error': job.error_message or None,
    }


@csrf_exempt
@require_POST
@require_api_token
def trigger_connection(request, connection_id):
    if request.api_user.role_level < ROLE_LEVEL[ROLE_OPERATOR]:
        return JsonResponse({'error': _FORBIDDEN}, status=403)
    try:
        connection = Connection.objects.get(pk=connection_id)
    except Connection.DoesNotExist:
        return JsonResponse({'error': _NOT_FOUND}, status=404)

    try:
        data = json.loads(request.body)
    except ValueError:
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
    result = current_app.send_task('transfers.execute', kwargs={'job_id': job.pk})
    TransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)
    return JsonResponse({'job_id': job.pk}, status=202)


@csrf_exempt
@require_POST
@require_api_token
def trigger_flow(request, flow_id):
    if request.api_user.role_level < ROLE_LEVEL[ROLE_OPERATOR]:
        return JsonResponse({'error': _FORBIDDEN}, status=403)
    try:
        flow = Flow.objects.get(pk=flow_id)
    except Flow.DoesNotExist:
        return JsonResponse({'error': _NOT_FOUND}, status=404)

    job = TransferJob.objects.create(
        owner=request.api_user,
        flow=flow,
        source_path=flow.source_path,
        destination_path=flow.dest_path,
    )
    result = current_app.send_task('transfers.execute', kwargs={'job_id': job.pk})
    TransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)
    return JsonResponse({'job_id': job.pk}, status=202)


@require_api_token
def job_status(request, job_id):
    try:
        job = TransferJob.objects.get(pk=job_id)
    except TransferJob.DoesNotExist:
        return JsonResponse({'error': _NOT_FOUND}, status=404)

    return JsonResponse(_serialize_transfer_job(job))


@require_api_token
def job_list(request):
    status, error = _parse_status_filter(request, STATUS_CHOICES)
    if error:
        return error
    jobs = TransferJob.objects.all()
    if status:
        jobs = jobs.filter(status=status)
    jobs = jobs[:_LIST_PAGE_SIZE]
    return JsonResponse({'jobs': [_serialize_transfer_job(j) for j in jobs]})
