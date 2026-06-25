import pytest
from django.core.exceptions import ValidationError
from apps.flows.models import Flow


@pytest.mark.django_db
class TestFlowModel:
    def test_create_flow(self, regular_user, make_connection):
        src = make_connection(regular_user, name='Source', host='10.0.0.1')
        dst = make_connection(regular_user, name='Dest', host='10.0.0.2')
        flow = Flow.objects.create(
            owner=regular_user,
            name='Daily Backup',
            source_conn=src,
            source_path='/data/file.tar',
            dest_conn=dst,
            dest_path='/backup/file.tar',
        )
        assert flow.pk is not None
        assert str(flow) == 'Daily Backup'

    def test_same_conn_same_path_invalid(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        flow = Flow(
            owner=regular_user,
            name='Bad',
            source_conn=conn,
            source_path='/same/path',
            dest_conn=conn,
            dest_path='/same/path',
        )
        with pytest.raises(ValidationError):
            flow.full_clean()

    def test_same_conn_different_path_valid(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        flow = Flow(
            owner=regular_user,
            name='Local Copy',
            source_conn=conn,
            source_path='/data/file.tar',
            dest_conn=conn,
            dest_path='/backup/file.tar',
        )
        flow.full_clean()  # should not raise

    def test_owner_isolation(self, regular_user, admin_user, make_connection):
        src = make_connection(admin_user, name='Src', host='10.0.0.1')
        dst = make_connection(admin_user, name='Dst', host='10.0.0.2')
        Flow.objects.create(
            owner=admin_user, name='Admin Flow',
            source_conn=src, source_path='/x',
            dest_conn=dst, dest_path='/y',
        )
        assert Flow.objects.filter(owner=regular_user).count() == 0

    def test_verify_checksum_defaults_false(self, regular_user, make_connection):
        src = make_connection(regular_user, name='S', host='10.0.0.1')
        dst = make_connection(regular_user, name='D', host='10.0.0.2')
        flow = Flow.objects.create(
            owner=regular_user, name='Flow',
            source_conn=src, source_path='/a',
            dest_conn=dst, dest_path='/b',
        )
        assert flow.verify_checksum is False
