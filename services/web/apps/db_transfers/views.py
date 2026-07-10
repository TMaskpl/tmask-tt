from celery import current_app
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN, ROLE_OPERATOR, ROLE_READONLY
from .models import PgTransferJob, STATUS_RUNNING, STATUS_PENDING
from .forms import PgTransferForm


@require_role(ROLE_READONLY)
def db_transfer_list(request):
    jobs = PgTransferJob.objects.all().select_related('source_connection', 'dest_connection')
    return render(request, 'db_transfers/list.html', {'jobs': jobs})


@require_role(ROLE_OPERATOR)
def db_transfer_create(request):
    form = PgTransferForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            job = form.save(commit=False)
            job.owner = request.user
            job.save()

            def _dispatch():
                result = current_app.send_task('db_transfers.execute', kwargs={'job_id': job.pk})
                PgTransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)
            transaction.on_commit(_dispatch)
        return redirect('db_transfers:detail', pk=job.pk)
    return render(request, 'db_transfers/create.html', {'form': form})


@require_role(ROLE_READONLY)
def db_transfer_detail(request, pk):
    job = get_object_or_404(
        PgTransferJob.objects.select_related('source_connection', 'dest_connection'), pk=pk
    )
    return render(request, 'db_transfers/detail.html', {'job': job})


@require_role(ROLE_READONLY)
def log_fragment(request, pk):
    job = get_object_or_404(PgTransferJob, pk=pk)
    logs = job.logs.all()
    still_running = job.status == STATUS_RUNNING
    return render(request, 'db_transfers/log_fragment.html', {
        'job': job, 'logs': logs, 'still_running': still_running,
    })


@require_role(ROLE_OPERATOR)
@require_POST
def db_transfer_stop(request, pk):
    with transaction.atomic():
        job = get_object_or_404(PgTransferJob.objects.select_for_update(), pk=pk)
        if job.status not in (STATUS_PENDING, STATUS_RUNNING):
            messages.error(request, 'Transfer nie jest aktywny.')
            return redirect('db_transfers:detail', pk=job.pk)
        if job.celery_task_id:
            current_app.control.revoke(job.celery_task_id, terminate=True, signal='SIGTERM')
        job.mark_cancelled(by=request.user)
    messages.success(request, 'Transfer zatrzymany.')
    return redirect('db_transfers:detail', pk=job.pk)


@require_role(ROLE_ADMIN)
@require_POST
def db_transfer_delete(request, pk):
    job = get_object_or_404(PgTransferJob, pk=pk)
    if job.status in (STATUS_PENDING, STATUS_RUNNING):
        messages.error(request, 'Nie można usunąć aktywnego transferu — najpierw zatrzymaj.')
        return redirect('db_transfers:detail', pk=job.pk)
    job.delete()
    return redirect('db_transfers:list')
