import pytest
from apps.scheduler.models import ScheduledTransfer


@pytest.mark.django_db
class TestScheduledTransfer:
    def test_flow_schedule_create(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        sched = ScheduledTransfer.objects.create(
            owner=regular_user,
            flow=flow,
            cron_expr='0 3 * * *',
        )
        assert sched.pk is not None
        assert sched.enabled is True
        assert sched.last_run is None
        assert sched.next_run is None
        assert sched.flow == flow

    def test_default_enabled_is_true(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        sched = ScheduledTransfer(
            owner=regular_user,
            flow=flow,
            cron_expr='*/5 * * * *',
        )
        assert sched.enabled is True

    def test_str_representation_with_flow(self, regular_user, make_flow):
        flow = make_flow(regular_user, name='Test Flow')
        sched = ScheduledTransfer(
            owner=regular_user,
            flow=flow,
            cron_expr='0 3 * * *',
        )
        assert 'Test Flow' in str(sched)
        assert '0 3 * * *' in str(sched)

    def test_str_no_flow(self, regular_user):
        sched = ScheduledTransfer(
            owner=regular_user,
            cron_expr='0 3 * * *',
        )
        assert '<no flow>' in str(sched)

    def test_owner_isolation(self, regular_user, admin_user, make_flow):
        ScheduledTransfer.objects.create(
            owner=admin_user,
            flow=make_flow(admin_user),
            cron_expr='0 1 * * *',
        )
        assert ScheduledTransfer.objects.filter(owner=regular_user).count() == 0

    def test_clean_requires_flow(self, regular_user):
        from django.core.exceptions import ValidationError
        sched = ScheduledTransfer(
            owner=regular_user,
            cron_expr='0 3 * * *',
        )
        with pytest.raises(ValidationError):
            sched.full_clean()
