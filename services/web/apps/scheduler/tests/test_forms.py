import pytest
from apps.scheduler.forms import ScheduledTransferForm


@pytest.mark.django_db
class TestScheduledTransferForm:
    def test_flow_schedule_valid(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        form = ScheduledTransferForm(
            data={
                'flow': flow.pk,
                'cron_expr': '0 2 * * *',
                'enabled': True,
            },
            user=regular_user,
        )
        assert form.is_valid(), form.errors

    def test_flow_required(self, regular_user):
        form = ScheduledTransferForm(
            data={
                'cron_expr': '0 2 * * *',
                'enabled': True,
            },
            user=regular_user,
        )
        assert not form.is_valid()
        assert 'flow' in form.errors

    def test_flow_filters_to_own_flows(self, regular_user, admin_user, make_flow):
        make_flow(admin_user, name='AdminFlow')
        form = ScheduledTransferForm(user=regular_user)
        assert form.fields['flow'].queryset.filter(name='AdminFlow').count() == 0

    def test_invalid_cron_rejected(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        form = ScheduledTransferForm(
            data={
                'flow': flow.pk,
                'cron_expr': 'not-valid',
                'enabled': True,
            },
            user=regular_user,
        )
        assert not form.is_valid()
        assert 'cron_expr' in form.errors

    def test_valid_cron_accepted(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        form = ScheduledTransferForm(
            data={
                'flow': flow.pk,
                'cron_expr': '0 2 * * 1',
                'enabled': True,
            },
            user=regular_user,
        )
        assert form.is_valid(), form.errors
