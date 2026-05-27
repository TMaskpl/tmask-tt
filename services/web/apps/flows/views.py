from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from apps.transfers.models import TransferJob
from apps.transfers.tasks import execute_transfer
from .forms import FlowForm
from .models import Flow

_FLOWS_LIST = 'flows:list'


@login_required
def flow_list(request):
    flows = Flow.objects.filter(owner=request.user).select_related('source_conn', 'dest_conn')
    return render(request, 'flows/list.html', {'flows': flows})


@login_required
def flow_create(request):
    form = FlowForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        flow = form.save(commit=False)
        flow.owner = request.user
        flow.save()
        return redirect(_FLOWS_LIST)
    return render(request, 'flows/form.html', {'form': form, 'action': 'CREATE'})


@login_required
def flow_edit(request, pk):
    flow = get_object_or_404(Flow, pk=pk, owner=request.user)
    form = FlowForm(request.POST or None, instance=flow, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect(_FLOWS_LIST)
    return render(request, 'flows/form.html', {'form': form, 'action': 'EDIT', 'flow': flow})


@login_required
@require_POST
def flow_delete(request, pk):
    flow = get_object_or_404(Flow, pk=pk, owner=request.user)
    flow.delete()
    return redirect(_FLOWS_LIST)


@login_required
@require_POST
def flow_run(request, pk):
    flow = get_object_or_404(Flow, pk=pk, owner=request.user)
    with transaction.atomic():
        job = TransferJob.objects.create(
            owner=request.user,
            flow=flow,
            source_path=flow.source_path,
            destination_path=flow.dest_path,
        )
        transaction.on_commit(lambda: execute_transfer.delay(job_id=job.pk))
    return redirect('transfers:detail', pk=job.pk)
