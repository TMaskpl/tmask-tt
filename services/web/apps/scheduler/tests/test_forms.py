import pytest
from apps.scheduler.forms import ScheduledTransferForm


@pytest.mark.django_db
class TestScheduledTransferFormFlowSupport:
    def test_flow_schedule_valid(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        form = ScheduledTransferForm(
            data={
                'mode': 'flow',
                'flow': flow.pk,
                'source_path': '',
                'destination_path': '',
                'cron_expr': '0 2 * * *',
                'enabled': True,
            },
            user=regular_user,
        )
        assert form.is_valid(), form.errors

    def test_connection_schedule_valid(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        form = ScheduledTransferForm(
            data={
                'mode': 'connection',
                'connection': conn.pk,
                'source_path': '/data/',
                'destination_path': '/backup/',
                'cron_expr': '0 2 * * *',
                'enabled': True,
            },
            user=regular_user,
        )
        assert form.is_valid(), form.errors

    def test_cannot_set_both_connection_and_flow(self, regular_user, make_connection, make_flow):
        conn = make_connection(regular_user)
        flow = make_flow(regular_user)
        form = ScheduledTransferForm(
            data={
                'mode': 'connection',
                'connection': conn.pk,
                'flow': flow.pk,
                'source_path': '/data/',
                'destination_path': '/backup/',
                'cron_expr': '0 2 * * *',
                'enabled': True,
            },
            user=regular_user,
        )
        assert not form.is_valid()

    def test_must_set_at_least_one(self, regular_user):
        form = ScheduledTransferForm(
            data={
                'mode': 'connection',
                'source_path': '/data/',
                'destination_path': '/backup/',
                'cron_expr': '0 2 * * *',
                'enabled': True,
            },
            user=regular_user,
        )
        assert not form.is_valid()

    def test_flow_filters_to_own_flows(self, regular_user, admin_user, make_flow):
        make_flow(admin_user, name='AdminFlow')
        form = ScheduledTransferForm(user=regular_user)
        assert form.fields['flow'].queryset.filter(name='AdminFlow').count() == 0

    def test_connection_filters_to_own_connections(self, regular_user, admin_user, make_connection):
        make_connection(admin_user, name='AdminConn')
        form = ScheduledTransferForm(user=regular_user)
        assert form.fields['connection'].queryset.filter(name='AdminConn').count() == 0
