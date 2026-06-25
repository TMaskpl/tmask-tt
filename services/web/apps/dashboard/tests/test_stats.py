import pytest
from datetime import timedelta
from django.utils import timezone

from apps.transfers.models import (
    TransferJob, STATUS_DONE, STATUS_FAILED, STATUS_PENDING,
)
from apps.dashboard import stats


def _make_job(user, connection=None, flow=None, status=STATUS_DONE, days_ago=0):
    job = TransferJob.objects.create(
        owner=user, connection=connection, flow=flow,
        source_path='/s', destination_path='/d', status=status,
    )
    # created_at ma auto_now_add=True — nadpisanie przez update() omija je
    when = timezone.now() - timedelta(days=days_ago)
    TransferJob.objects.filter(pk=job.pk).update(created_at=when)
    return job


@pytest.mark.django_db
class TestTransfersPerDay:
    def test_counts_done_and_failed_per_day(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        _make_job(regular_user, conn, status=STATUS_DONE, days_ago=0)
        _make_job(regular_user, conn, status=STATUS_DONE, days_ago=0)
        _make_job(regular_user, conn, status=STATUS_FAILED, days_ago=0)
        _make_job(regular_user, conn, status=STATUS_DONE, days_ago=1)
        result = stats.transfers_per_day(TransferJob.objects.filter(owner=regular_user))
        assert len(result['labels']) == 30
        assert result['done'][-1] == 2   # dziś
        assert result['failed'][-1] == 1
        assert result['done'][-2] == 1   # wczoraj

    def test_fills_gaps_with_zero(self, regular_user):
        result = stats.transfers_per_day(TransferJob.objects.filter(owner=regular_user))
        assert len(result['labels']) == 30
        assert result['done'] == [0] * 30
        assert result['failed'] == [0] * 30

    def test_excludes_jobs_older_than_window(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        _make_job(regular_user, conn, status=STATUS_DONE, days_ago=40)
        result = stats.transfers_per_day(TransferJob.objects.filter(owner=regular_user))
        assert sum(result['done']) == 0


@pytest.mark.django_db
class TestSuccessRate:
    def test_rate_excludes_pending_running(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        for _ in range(8):
            _make_job(regular_user, conn, status=STATUS_DONE)
        for _ in range(2):
            _make_job(regular_user, conn, status=STATUS_FAILED)
        for _ in range(5):
            _make_job(regular_user, conn, status=STATUS_PENDING)
        result = stats.success_rate(TransferJob.objects.filter(owner=regular_user))
        assert result['done'] == 8
        assert result['failed'] == 2
        assert result['other'] == 5
        assert result['total'] == 15
        assert result['rate_pct'] == 80.0

    def test_zero_jobs_rate_is_zero(self, regular_user):
        result = stats.success_rate(TransferJob.objects.filter(owner=regular_user))
        assert result['total'] == 0
        assert result['rate_pct'] == 0.0


@pytest.mark.django_db
class TestTopSources:
    def test_combines_connections_and_flows(self, regular_user, make_connection, make_flow):
        conn = make_connection(regular_user, name='Backup-SFTP')
        flow = make_flow(regular_user, name='Nightly')
        _make_job(regular_user, connection=conn)
        _make_job(regular_user, connection=conn)
        _make_job(regular_user, flow=flow)
        result = stats.top_sources(TransferJob.objects.filter(owner=regular_user))
        assert result['labels'][0] == 'Backup-SFTP'
        assert result['counts'][0] == 2
        assert 'RELAY: Nightly' in result['labels']

    def test_orders_desc_and_respects_limit(self, regular_user, make_connection):
        for i in range(9):
            conn = make_connection(regular_user, name=f'C{i}', host=f'10.0.0.{i}')
            for _ in range(i + 1):
                _make_job(regular_user, connection=conn)
        result = stats.top_sources(TransferJob.objects.filter(owner=regular_user), limit=7)
        assert len(result['labels']) == 7
        assert result['labels'][0] == 'C8'      # najwięcej jobów
        assert result['counts'] == sorted(result['counts'], reverse=True)
