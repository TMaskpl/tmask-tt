from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.transfers.models import TransferJob
from . import stats


@login_required
def dashboard(request):
    since = timezone.now() - timedelta(days=30)
    jobs = TransferJob.objects.filter(owner=request.user, created_at__gte=since)
    data = {
        "per_day": stats.transfers_per_day(jobs),
        "success": stats.success_rate(jobs),
        "top": stats.top_sources(jobs),
    }
    return render(request, "dashboard/index.html", {"data": data})
