import pytest
from django.core.exceptions import ValidationError

from apps.db_transfers.models import PgTransferJob


@pytest.mark.django_db
class TestPgTransferJob:
    def test_clean_rejects_same_source_and_dest_connection(self, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        job = PgTransferJob(owner=regular_user, source_connection=conn, dest_connection=conn)
        with pytest.raises(ValidationError):
            job.clean()

    def test_clean_allows_different_connections(self, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob(owner=regular_user, source_connection=src, dest_connection=dst)
        job.clean()  # should not raise

    def test_mark_done_sets_status_and_finished_at(self, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst)
        job.mark_done()
        assert job.status == 'done'
        assert job.finished_at is not None

    def test_mark_failed_sets_error_message(self, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst)
        job.mark_failed('AUTH FAILED')
        assert job.status == 'failed'
        assert job.error_message == 'AUTH FAILED'
