import pytest
from apps.scheduler.models import ScheduledTransfer


@pytest.mark.django_db
class TestScheduledTransfer:
    def test_create_scheduled_transfer(self, regular_user, make_connection):
        sched = ScheduledTransfer.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/data/',
            destination_path='/backup/',
            cron_expr='0 2 * * *',
        )
        assert sched.pk is not None
        assert sched.enabled is True
        assert sched.last_run is None
        assert sched.next_run is None

    def test_default_enabled_is_true(self, regular_user, make_connection):
        sched = ScheduledTransfer(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
            cron_expr='*/5 * * * *',
        )
        assert sched.enabled is True

    def test_str_representation(self, regular_user, make_connection):
        conn = make_connection(regular_user, name='Backup Server')
        sched = ScheduledTransfer(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y',
            cron_expr='0 3 * * *',
        )
        assert 'Backup Server' in str(sched)
        assert '0 3 * * *' in str(sched)

    def test_owner_isolation(self, regular_user, admin_user, make_connection):
        ScheduledTransfer.objects.create(
            owner=admin_user,
            connection=make_connection(admin_user),
            source_path='/x', destination_path='/y',
            cron_expr='0 1 * * *',
        )
        assert ScheduledTransfer.objects.filter(owner=regular_user).count() == 0

    def test_cron_form_validation_invalid(self, regular_user, make_connection):
        from apps.scheduler.forms import ScheduledTransferForm
        conn = make_connection(regular_user)
        form = ScheduledTransferForm(
            data={
                'connection': conn.pk,
                'source_path': '/x', 'destination_path': '/y',
                'cron_expr': 'not-valid',
                'enabled': True,
            },
            user=regular_user,
        )
        assert not form.is_valid()
        assert 'cron_expr' in form.errors

    def test_cron_form_validation_valid(self, regular_user, make_connection):
        from apps.scheduler.forms import ScheduledTransferForm
        conn = make_connection(regular_user)
        form = ScheduledTransferForm(
            data={
                'connection': conn.pk,
                'source_path': '/data/', 'destination_path': '/backup/',
                'cron_expr': '0 2 * * 1',
                'enabled': True,
            },
            user=regular_user,
        )
        assert form.is_valid(), form.errors


@pytest.mark.django_db
class TestScheduledTransferFlowValidation:
    def test_flow_schedule_requires_no_connection(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        sched = ScheduledTransfer.objects.create(
            owner=regular_user,
            flow=flow,
            source_path='',
            destination_path='',
            cron_expr='0 3 * * *',
        )
        assert sched.connection is None
        assert sched.flow == flow
        assert str(sched) == 'Test Flow: 0 3 * * *'

    def test_cannot_set_both_connection_and_flow(self, regular_user, make_connection, make_flow):
        from django.core.exceptions import ValidationError
        sched = ScheduledTransfer(
            owner=regular_user,
            connection=make_connection(regular_user),
            flow=make_flow(regular_user),
            source_path='/x', destination_path='/y',
            cron_expr='0 3 * * *',
        )
        with pytest.raises(ValidationError):
            sched.full_clean()
