from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .models import ScheduledTransfer
from .forms import ScheduledTransferForm

_SCHEDULER_LIST = 'scheduler:list'


@login_required
def schedule_list(request):
    schedules = ScheduledTransfer.objects.filter(owner=request.user).select_related('flow', 'flow__source_conn', 'flow__dest_conn')
    return render(request, 'scheduler/list.html', {'schedules': schedules})


@login_required
def schedule_create(request):
    form = ScheduledTransferForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        sched = form.save(commit=False)
        sched.owner = request.user
        sched.save()
        _sync_celery_beat(sched)
        return redirect(_SCHEDULER_LIST)
    return render(request, 'scheduler/form.html', {'form': form, 'action': 'CREATE'})


@login_required
def schedule_edit(request, pk):
    sched = get_object_or_404(ScheduledTransfer, pk=pk, owner=request.user)
    form = ScheduledTransferForm(request.POST or None, instance=sched, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        _sync_celery_beat(sched)
        return redirect(_SCHEDULER_LIST)
    return render(request, 'scheduler/form.html', {'form': form, 'action': 'EDIT', 'sched': sched})


@login_required
@require_POST
def schedule_toggle(request, pk):
    sched = get_object_or_404(ScheduledTransfer, pk=pk, owner=request.user)
    sched.enabled = not sched.enabled
    sched.save(update_fields=['enabled'])
    _sync_celery_beat(sched)
    return redirect(_SCHEDULER_LIST)


@login_required
@require_POST
def schedule_delete(request, pk):
    sched = get_object_or_404(ScheduledTransfer, pk=pk, owner=request.user)
    _delete_celery_beat(sched)
    sched.delete()
    return redirect(_SCHEDULER_LIST)


def _sync_celery_beat(sched: ScheduledTransfer):
    from django_celery_beat.models import PeriodicTask, CrontabSchedule
    import json
    minute, hour, day_of_month, month_of_year, day_of_week = sched.cron_expr.split()
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=minute, hour=hour, day_of_month=day_of_month,
        month_of_year=month_of_year, day_of_week=day_of_week,
    )
    task_name = f'scheduled_transfer_{sched.pk}'
    PeriodicTask.objects.update_or_create(
        name=task_name,
        defaults={
            'crontab': crontab,
            'task': 'transfers.execute',
            'kwargs': json.dumps({'job_id': None, 'scheduled_id': sched.pk}),
            'enabled': sched.enabled,
        }
    )


def _delete_celery_beat(sched: ScheduledTransfer):
    from django_celery_beat.models import PeriodicTask
    PeriodicTask.objects.filter(name=f'scheduled_transfer_{sched.pk}').delete()
