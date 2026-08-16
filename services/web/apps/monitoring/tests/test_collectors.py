from datetime import timedelta
from unittest.mock import patch, MagicMock

import pytest
from django.utils import timezone

from apps.transfers.models import TransferJob
from apps.db_transfers.models import DbTransferJob
from apps.monitoring.collectors import TmaskCollector


def _sample_by_name(samples, name):
    return [s for s in samples if s.name == name]


@pytest.mark.django_db
class TestJobsTotal:
    def test_counts_file_job_by_connection_protocol(self, regular_user, make_connection):
        conn = make_connection(regular_user, protocol='sftp')
        TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y', status='done',
        )
        families = {f.name: f for f in TmaskCollector().collect()}
        samples = _sample_by_name(families['tmask_transfer_jobs'].samples, 'tmask_transfer_jobs_total')
        matching = [s for s in samples if s.labels == {'type': 'file', 'module': 'sftp', 'status': 'done'}]
        assert len(matching) == 1
        assert matching[0].value == 1

    def test_counts_flow_job_as_relay_module(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        TransferJob.objects.create(
            owner=regular_user, flow=flow,
            source_path='/x', destination_path='/y', status='failed',
        )
        families = {f.name: f for f in TmaskCollector().collect()}
        samples = families['tmask_transfer_jobs'].samples
        matching = [s for s in samples if s.labels == {'type': 'file', 'module': 'relay', 'status': 'failed'}]
        assert len(matching) == 1
        assert matching[0].value == 1

    def test_counts_db_job_by_engine(self, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='a', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='b', name='dst')
        DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst,
            engine='postgres', status='running',
        )
        families = {f.name: f for f in TmaskCollector().collect()}
        samples = families['tmask_transfer_jobs'].samples
        matching = [s for s in samples if s.labels == {'type': 'db', 'module': 'postgres', 'status': 'running'}]
        assert len(matching) == 1
        assert matching[0].value == 1

    def test_no_samples_for_empty_database(self, regular_user):
        families = {f.name: f for f in TmaskCollector().collect()}
        assert families['tmask_transfer_jobs'].samples == []


@pytest.mark.django_db
class TestDurationSeconds:
    def test_sums_duration_for_finished_file_job(self, regular_user, make_connection):
        conn = make_connection(regular_user, protocol='rsync')
        started = timezone.now() - timedelta(seconds=30)
        finished = timezone.now()
        TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y', status='done',
            started_at=started, finished_at=finished,
        )
        families = {f.name: f for f in TmaskCollector().collect()}
        samples = families['tmask_transfer_duration_seconds'].samples
        sum_sample = [s for s in samples if s.name == 'tmask_transfer_duration_seconds_sum'
                      and s.labels == {'type': 'file', 'module': 'rsync'}]
        count_sample = [s for s in samples if s.name == 'tmask_transfer_duration_seconds_count'
                        and s.labels == {'type': 'file', 'module': 'rsync'}]
        assert len(sum_sample) == 1
        assert len(count_sample) == 1
        assert 29.0 <= sum_sample[0].value <= 31.0
        assert count_sample[0].value == 1

    def test_excludes_job_without_finished_at(self, regular_user, make_connection):
        conn = make_connection(regular_user, protocol='sftp')
        TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y', status='running',
            started_at=timezone.now(), finished_at=None,
        )
        families = {f.name: f for f in TmaskCollector().collect()}
        assert families['tmask_transfer_duration_seconds'].samples == []
        jobs_samples = families['tmask_transfer_jobs'].samples
        assert len(jobs_samples) == 1  # still counted in jobs_total


@pytest.mark.django_db
class TestQueueLength:
    def test_reads_llen_from_redis(self, regular_user):
        with patch('apps.monitoring.collectors.redis.Redis') as MockRedis:
            MockRedis.from_url.return_value.llen.return_value = 7
            families = {f.name: f for f in TmaskCollector().collect()}
        samples = families['tmask_celery_queue_length'].samples
        matching = [s for s in samples if s.labels == {'queue': 'celery'}]
        assert len(matching) == 1
        assert matching[0].value == 7

    def test_present_even_with_empty_database(self, regular_user):
        with patch('apps.monitoring.collectors.redis.Redis') as MockRedis:
            MockRedis.from_url.return_value.llen.return_value = 0
            families = {f.name: f for f in TmaskCollector().collect()}
        assert families['tmask_transfer_jobs'].samples == []
        assert len(families['tmask_celery_queue_length'].samples) == 1
