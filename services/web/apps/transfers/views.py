from celery import current_app
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from .models import TransferJob, STATUS_RUNNING
from .forms import TransferForm


@login_required
def transfer_create(request):
    form = TransferForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            job = form.save(commit=False)
            job.owner = request.user
            job.save()
            passphrase = (form.cleaned_data.get('gpg_passphrase') or '').strip() or None
            transaction.on_commit(
                lambda: current_app.send_task('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': passphrase})
            )
        return redirect('transfers:detail', pk=job.pk)
    return render(request, 'transfers/create.html', {'form': form})


@login_required
def transfer_detail(request, pk):
    job = get_object_or_404(
        TransferJob.objects.select_related('connection', 'flow', 'flow__source_conn', 'flow__dest_conn'),
        pk=pk, owner=request.user,
    )
    return render(request, 'transfers/create.html', {'job': job})


@login_required
def log_fragment(request, pk):
    job = get_object_or_404(TransferJob, pk=pk, owner=request.user)
    logs = job.logs.all()
    still_running = job.status == STATUS_RUNNING
    return render(request, 'transfers/log_fragment.html', {
        'job': job, 'logs': logs, 'still_running': still_running
    })


@login_required
def transfer_logs(request):
    jobs = TransferJob.objects.filter(owner=request.user).select_related('connection', 'flow')
    return render(request, 'logs/list.html', {'jobs': jobs})
