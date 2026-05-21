import pytest
from apps.transfers.models import (
    TransferJob, TransferLog,
    STATUS_PENDING, STATUS_RUNNING, STATUS_DONE, STATUS_FAILED,
)


@pytest.mark.django_db
class TestTransferJob:
    def test_default_status_is_pending(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/data/file.tar',
            destination_path='/backup/',
        )
        assert job.status == STATUS_PENDING
        assert job.started_at is None
        assert job.finished_at is None
        assert job.celery_task_id is None

    def test_mark_running_updates_status_and_timestamp(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        job.mark_running('celery-task-abc-123')
        job.refresh_from_db()
        assert job.status == STATUS_RUNNING
        assert job.celery_task_id == 'celery-task-abc-123'
        assert job.started_at is not None

    def test_mark_done_updates_status(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        job.mark_done()
        job.refresh_from_db()
        assert job.status == STATUS_DONE
        assert job.finished_at is not None

    def test_mark_failed_saves_error_message(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        job.mark_failed('AUTH FAILED — check credentials')
        job.refresh_from_db()
        assert job.status == STATUS_FAILED
        assert job.error_message == 'AUTH FAILED — check credentials'
        assert job.finished_at is not None

    def test_owner_isolation(self, regular_user, admin_user, make_connection):
        TransferJob.objects.create(
            owner=admin_user,
            connection=make_connection(admin_user),
            source_path='/x', destination_path='/y',
        )
        assert TransferJob.objects.filter(owner=regular_user).count() == 0

    def test_str_representation(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/data/file.tar', destination_path='/backup/',
        )
        assert str(job.pk) in str(job)
        assert '/data/file.tar' in str(job)


@pytest.mark.django_db
class TestTransferLog:
    def test_log_appended_to_job(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        TransferLog.objects.create(job=job, level='info', message='Transfer started')
        assert job.logs.count() == 1

    def test_logs_ordered_by_timestamp(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        TransferLog.objects.create(job=job, level='info', message='First')
        TransferLog.objects.create(job=job, level='info', message='Second')
        messages = list(job.logs.values_list('message', flat=True))
        assert messages == ['First', 'Second']
