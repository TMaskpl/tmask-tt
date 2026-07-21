from celery import current_app
from celery.result import AsyncResult
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN, ROLE_OPERATOR, ROLE_READONLY
from apps.connections.models import Connection
from .models import TransferJob, STATUS_RUNNING, STATUS_PENDING
from .forms import TransferForm

TRANSFERS_CREATE_TEMPLATE = 'transfers/create.html'
TRANSFERS_DETAIL = 'transfers:detail'


def _connection_protocols():
    return dict(Connection.objects.values_list('pk', 'protocol'))


def _write_upload(local_path: str, uploaded) -> str | None:
    """Writes an uploaded file to local_path. Returns an error string on
    failure (OSError message), or None on success."""
    try:
        with open(local_path, 'wb') as fh:
            for chunk in uploaded.chunks():
                fh.write(chunk)
        return None
    except OSError as exc:
        return str(exc)


def _dispatch_transfer(job, passphrase):
    result = current_app.send_task('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': passphrase})
    TransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)


@require_role(ROLE_OPERATOR)
def transfer_create(request):
    form = TransferForm(request.POST or None, request.FILES or None, user=request.user)
    ctx = {'form': form, 'connection_protocols': _connection_protocols()}
    if request.method == 'POST' and form.is_valid():
        uploads = form.cleaned_data['upload']
        passphrase = (form.cleaned_data.get('gpg_passphrase') or '').strip() or None

        if len(uploads) == 1:
            uploaded = uploads[0]
            local_path = form.cleaned_data['source_path']
            err = _write_upload(local_path, uploaded)
            if err:
                form.add_error(None, f'Nie udało się zapisać pliku: {err}')
                return render(request, TRANSFERS_CREATE_TEMPLATE, ctx)
            with transaction.atomic():
                job = form.save(commit=False)
                job.owner = request.user
                job.source_path = local_path
                job.save()
                transaction.on_commit(lambda: _dispatch_transfer(job, passphrase))
            return redirect(TRANSFERS_DETAIL, pk=job.pk)

        # Batch upload: destination_path is validated as a directory in
        # TransferForm.clean() — each file lands at destination_path/<filename>,
        # one independent TransferJob per file (same infra as single-file:
        # own log, own progress bar, own notifications).
        connection = form.cleaned_data['connection']
        dest_dir = form.cleaned_data['destination_path']
        to_create = []
        for uploaded in uploads:
            local_path = f'{settings.TRANSFERS_DIR}/{uploaded.name}'
            err = _write_upload(local_path, uploaded)
            if err:
                form.add_error(None, f'Nie udało się zapisać pliku {uploaded.name}: {err}')
                return render(request, TRANSFERS_CREATE_TEMPLATE, ctx)
            to_create.append((local_path, f'{dest_dir}{uploaded.name}'))

        with transaction.atomic():
            jobs = [
                TransferJob.objects.create(
                    owner=request.user, connection=connection,
                    source_path=local_path, destination_path=job_dest,
                )
                for local_path, job_dest in to_create
            ]

            def _dispatch_all():
                for job in jobs:
                    _dispatch_transfer(job, passphrase)
            transaction.on_commit(_dispatch_all)

        messages.success(request, f'Uruchomiono {len(jobs)} transferów.')
        return redirect('transfers:logs')
    return render(request, TRANSFERS_CREATE_TEMPLATE, ctx)


@require_role(ROLE_OPERATOR)
def transfer_dry_run(request):
    form = TransferForm(request.POST or None, request.FILES or None, user=request.user)
    ctx_base = {'connection_protocols': _connection_protocols()}
    if request.method == 'POST' and form.is_valid():
        uploads = form.cleaned_data['upload']
        if len(uploads) > 1:
            form.add_error(None, 'Dry-run obsługuje tylko jeden plik na raz.')
            return render(request, TRANSFERS_CREATE_TEMPLATE, {**ctx_base, 'form': form})
        connection = form.cleaned_data['connection']
        if connection.protocol != 'rsync':
            form.add_error(None, 'Dry-run jest dostępny tylko dla połączeń rsync.')
            return render(request, TRANSFERS_CREATE_TEMPLATE, {**ctx_base, 'form': form})
        uploaded = uploads[0]
        dest = form.cleaned_data['source_path']
        err = _write_upload(dest, uploaded)
        if err:
            form.add_error(None, f'Nie udało się zapisać pliku: {err}')
            return render(request, TRANSFERS_CREATE_TEMPLATE, {**ctx_base, 'form': form})
        passphrase = (form.cleaned_data.get('gpg_passphrase') or '').strip() or None
        result = current_app.send_task('transfers.dry_run_preview', kwargs={
            'connection_id': connection.pk,
            'source_path': form.cleaned_data['source_path'],
            'destination_path': form.cleaned_data['destination_path'],
            'gpg_passphrase': passphrase,
        })
        return render(request, TRANSFERS_CREATE_TEMPLATE, {**ctx_base, 'form': form, 'dry_run_task_id': result.id})
    return render(request, TRANSFERS_CREATE_TEMPLATE, {**ctx_base, 'form': form})


@require_role(ROLE_OPERATOR)
def transfer_dry_run_status(request, task_id):
    result = AsyncResult(task_id)
    return render(request, 'transfers/_dry_run_result.html', {
        'task_id': task_id,
        'state': result.state,
        'result': result.result if result.state == 'SUCCESS' else None,
    })


@require_role(ROLE_READONLY)
def transfer_detail(request, pk):
    job = get_object_or_404(
        TransferJob.objects.select_related('connection', 'flow', 'flow__source_conn', 'flow__dest_conn'),
        pk=pk,
    )
    return render(request, TRANSFERS_CREATE_TEMPLATE, {'job': job})


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
            return redirect(TRANSFERS_DETAIL, pk=job.pk)
        if job.celery_task_id:
            current_app.control.revoke(job.celery_task_id, terminate=True, signal='SIGTERM')
        job.mark_cancelled(by=request.user)
    messages.success(request, 'Transfer zatrzymany.')
    return redirect(TRANSFERS_DETAIL, pk=job.pk)


@require_role(ROLE_ADMIN)
@require_POST
def transfer_delete(request, pk):
    job = get_object_or_404(TransferJob, pk=pk)
    if job.status in (STATUS_PENDING, STATUS_RUNNING):
        messages.error(request, 'Nie można usunąć aktywnego transferu — najpierw zatrzymaj.')
        return redirect(TRANSFERS_DETAIL, pk=job.pk)
    job.delete()
    return redirect('transfers:logs')
