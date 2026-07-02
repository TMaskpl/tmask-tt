from celery import current_app
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_OPERATOR, ROLE_READONLY
from .models import TransferJob, STATUS_RUNNING, STATUS_PENDING
from .forms import TransferForm


@require_role(ROLE_OPERATOR)
def transfer_create(request):
    form = TransferForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        uploaded = form.cleaned_data['upload']
        dest = form.cleaned_data['source_path']
        try:
            with open(dest, 'wb') as fh:
                for chunk in uploaded.chunks():
                    fh.write(chunk)
        except OSError as exc:
            form.add_error(None, f'Nie udało się zapisać pliku: {exc}')
            return render(request, 'transfers/create.html', {'form': form})
        with transaction.atomic():
            job = form.save(commit=False)
            job.owner = request.user
            job.source_path = form.cleaned_data['source_path']
            job.save()
            passphrase = (form.cleaned_data.get('gpg_passphrase') or '').strip() or None

            def _dispatch():
                result = current_app.send_task('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': passphrase})
                TransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)
            transaction.on_commit(_dispatch)
        return redirect('transfers:detail', pk=job.pk)
    return render(request, 'transfers/create.html', {'form': form})


@require_role(ROLE_READONLY)
def transfer_detail(request, pk):
    job = get_object_or_404(
        TransferJob.objects.select_related('connection', 'flow', 'flow__source_conn', 'flow__dest_conn'),
        pk=pk,
    )
    return render(request, 'transfers/create.html', {'job': job})


@require_role(ROLE_READONLY)
def log_fragment(request, pk):
    job = get_object_or_404(TransferJob, pk=pk)
    logs = job.logs.all()
    still_running = job.status == STATUS_RUNNING
    return render(request, 'transfers/log_fragment.html', {
        'job': job, 'logs': logs, 'still_running': still_running
    })


@require_role(ROLE_READONLY)
def transfer_logs(request):
    jobs = TransferJob.objects.all().select_related('connection', 'flow')
    return render(request, 'logs/list.html', {'jobs': jobs})


@require_role(ROLE_OPERATOR)
@require_POST
def transfer_stop(request, pk):
    with transaction.atomic():
        job = get_object_or_404(TransferJob.objects.select_for_update(), pk=pk)
        if job.status not in (STATUS_PENDING, STATUS_RUNNING):
            messages.error(request, 'Transfer nie jest aktywny.')
            return redirect('transfers:detail', pk=job.pk)
        if job.celery_task_id:
            current_app.control.revoke(job.celery_task_id, terminate=True, signal='SIGTERM')
        job.mark_cancelled(by=request.user)
    messages.success(request, 'Transfer zatrzymany.')
    return redirect('transfers:detail', pk=job.pk)
