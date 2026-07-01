from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN, ROLE_OPERATOR, ROLE_READONLY
from apps.transfers.models import TransferJob
from celery import current_app
from .forms import FlowForm
from .models import Flow

_FLOWS_LIST = 'flows:list'


@require_role(ROLE_READONLY)
def flow_list(request):
    flows = Flow.objects.all().select_related('source_conn', 'dest_conn')
    return render(request, 'flows/list.html', {'flows': flows})


@require_role(ROLE_ADMIN)
def flow_create(request):
    form = FlowForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        flow = form.save(commit=False)
        flow.owner = request.user
        flow.save()
        return redirect(_FLOWS_LIST)
    return render(request, 'flows/form.html', {'form': form, 'action': 'CREATE'})


@require_role(ROLE_ADMIN)
def flow_edit(request, pk):
    flow = get_object_or_404(Flow, pk=pk)
    form = FlowForm(request.POST or None, instance=flow, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect(_FLOWS_LIST)
    return render(request, 'flows/form.html', {'form': form, 'action': 'EDIT', 'flow': flow})


@require_role(ROLE_ADMIN)
@require_POST
def flow_delete(request, pk):
    flow = get_object_or_404(Flow, pk=pk)
    flow.delete()
    return redirect(_FLOWS_LIST)


@require_role(ROLE_OPERATOR)
@require_POST
def flow_run(request, pk):
    flow = get_object_or_404(Flow, pk=pk)
    with transaction.atomic():
        job = TransferJob.objects.create(
            owner=request.user,
            flow=flow,
            source_path=flow.source_path,
            destination_path=flow.dest_path,
        )
        def _dispatch():
            result = current_app.send_task('transfers.execute', kwargs={'job_id': job.pk})
            TransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)
        transaction.on_commit(_dispatch)
    return redirect('transfers:detail', pk=job.pk)
