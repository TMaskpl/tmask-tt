from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.transfers.models import STATUS_DONE, STATUS_FAILED


def transfers_per_day(jobs, days=30):
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    rows = (
        jobs.filter(created_at__date__gte=start)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(
            done=Count('id', filter=Q(status=STATUS_DONE)),
            failed=Count('id', filter=Q(status=STATUS_FAILED)),
        )
    )
    by_day = {r['day']: r for r in rows}
    labels, done, failed = [], [], []
    for i in range(days):
        d = start + timedelta(days=i)
        labels.append(d.strftime('%m-%d'))
        row = by_day.get(d)
        done.append(row['done'] if row else 0)
        failed.append(row['failed'] if row else 0)
    return {"labels": labels, "done": done, "failed": failed}


def success_rate(jobs):
    total = jobs.count()
    done = jobs.filter(status=STATUS_DONE).count()
    failed = jobs.filter(status=STATUS_FAILED).count()
    other = total - done - failed
    denom = done + failed
    rate = round(done / denom * 100, 1) if denom else 0.0
    return {"done": done, "failed": failed, "other": other, "total": total, "rate_pct": rate}


def top_sources(jobs, limit=7):
    counts = {}
    for r in jobs.filter(connection__isnull=False).values('connection__name').annotate(c=Count('id')):
        name = r['connection__name']
        counts[name] = counts.get(name, 0) + r['c']
    for r in jobs.filter(flow__isnull=False).values('flow__name').annotate(c=Count('id')):
        label = f"RELAY: {r['flow__name']}"
        counts[label] = counts.get(label, 0) + r['c']
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return {"labels": [k for k, _ in ranked], "counts": [v for _, v in ranked]}
