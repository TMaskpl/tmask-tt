import redis
from django.conf import settings
from django.db.models import Count, Sum, Case, When, Value, F, CharField, ExpressionWrapper, DurationField
from django.db.models.functions import Coalesce

from apps.transfers.models import TransferJob
from apps.db_transfers.models import DbTransferJob
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, SummaryMetricFamily

_FILE_MODULE_EXPR = Case(
    When(flow_id__isnull=False, then=Value('relay')),
    default=Coalesce(F('connection__protocol'), Value('unknown')),
    output_field=CharField(),
)

_DURATION_EXPR = ExpressionWrapper(
    F('finished_at') - F('started_at'), output_field=DurationField()
)


class TmaskCollector:
    def collect(self):
        yield self._jobs_total()
        yield self._duration_seconds()
        yield self._queue_length()

    def _jobs_total(self):
        counter = CounterMetricFamily(
            'tmask_transfer_jobs_total',
            'Total number of transfer jobs by type, module and status.',
            labels=['type', 'module', 'status'],
        )

        file_rows = (
            TransferJob.objects
            .annotate(module=_FILE_MODULE_EXPR)
            .values('module', 'status')
            .annotate(count=Count('id'))
        )
        for row in file_rows:
            counter.add_metric(['file', row['module'], row['status']], row['count'])

        db_rows = (
            DbTransferJob.objects
            .values('engine', 'status')
            .annotate(count=Count('id'))
        )
        for row in db_rows:
            counter.add_metric(['db', row['engine'], row['status']], row['count'])

        return counter

    def _duration_seconds(self):
        summary = SummaryMetricFamily(
            'tmask_transfer_duration_seconds',
            'Duration of finished transfer jobs in seconds, by type and module.',
            labels=['type', 'module'],
        )

        file_rows = (
            TransferJob.objects
            .filter(started_at__isnull=False, finished_at__isnull=False)
            .annotate(module=_FILE_MODULE_EXPR, duration=_DURATION_EXPR)
            .values('module')
            .annotate(total=Sum('duration'), cnt=Count('id'))
        )
        for row in file_rows:
            total_seconds = row['total'].total_seconds() if row['total'] else 0.0
            summary.add_metric(['file', row['module']], row['cnt'], total_seconds)

        db_rows = (
            DbTransferJob.objects
            .filter(started_at__isnull=False, finished_at__isnull=False)
            .annotate(duration=_DURATION_EXPR)
            .values('engine')
            .annotate(total=Sum('duration'), cnt=Count('id'))
        )
        for row in db_rows:
            total_seconds = row['total'].total_seconds() if row['total'] else 0.0
            summary.add_metric(['db', row['engine']], row['cnt'], total_seconds)

        return summary

    def _queue_length(self):
        gauge = GaugeMetricFamily(
            'tmask_celery_queue_length',
            'Number of tasks waiting in the Celery queue.',
            labels=['queue'],
        )
        client = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        gauge.add_metric(['celery'], client.llen('celery'))
        return gauge
