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
        assert job.celery_task_id == ''

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

    def test_default_progress_percent_is_none(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        assert job.progress_percent is None

    def test_mark_running_resets_progress_percent(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
            progress_percent=42,
        )
        job.mark_running('celery-task-abc-123')
        job.refresh_from_db()
        assert job.progress_percent is None

    def test_mark_done_sets_progress_percent_to_100(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
            progress_percent=57,
        )
        job.mark_done()
        job.refresh_from_db()
        assert job.progress_percent == 100

    def test_update_progress_sets_percent(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        job.update_progress(33)
        job.refresh_from_db()
        assert job.progress_percent == 33

    def test_mark_failed_does_not_touch_progress_percent(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
            progress_percent=64,
        )
        job.mark_failed('boom')
        job.refresh_from_db()
        assert job.progress_percent == 64

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
class TestTransferJobFlowValidation:
    def test_flow_job_requires_no_connection(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        job = TransferJob.objects.create(
            owner=regular_user,
            flow=flow,
            source_path='/data/file.tar',
            destination_path='/backup/file.tar',
        )
        assert job.connection is None
        assert job.flow == flow

    def test_cannot_set_both_connection_and_flow(self, regular_user, make_connection, make_flow):
        from django.core.exceptions import ValidationError
        conn = make_connection(regular_user)
        flow = make_flow(regular_user)
        job = TransferJob(
            owner=regular_user,
            connection=conn,
            flow=flow,
            source_path='/x',
            destination_path='/y',
        )
        with pytest.raises(ValidationError):
            job.full_clean()

    def test_must_set_at_least_one(self, regular_user):
        from django.core.exceptions import ValidationError
        job = TransferJob(
            owner=regular_user,
            source_path='/x',
            destination_path='/y',
        )
        with pytest.raises(ValidationError):
            job.full_clean()


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


@pytest.mark.django_db
class TestMarkCancelled:
    def test_mark_cancelled_sets_status_and_who(self, django_user_model, make_connection):
        from apps.transfers.models import TransferJob, STATUS_CANCELLED
        owner = django_user_model.objects.create_user(username='owner1', password='p')
        stopper = django_user_model.objects.create_user(username='stopper1', password='p', role='admin')
        conn = make_connection(owner)
        job = TransferJob.objects.create(
            owner=owner, connection=conn, source_path='/a', destination_path='/b',
        )
        job.mark_cancelled(by=stopper)
        job.refresh_from_db()
        assert job.status == STATUS_CANCELLED
        assert job.cancelled_by_id == stopper.pk
        assert job.finished_at is not None

    def test_status_choices_include_cancelled(self):
        from apps.transfers.models import TransferJob
        values = [c[0] for c in TransferJob._meta.get_field('status').choices]
        assert 'cancelled' in values
