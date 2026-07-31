import pytest
from django.urls import reverse
from unittest.mock import patch
from apps.scheduler.models import ScheduledTransfer


@pytest.fixture
def make_schedule(db):
    def _make(user, flow, cron_expr='0 2 * * *', enabled=True):
        return ScheduledTransfer.objects.create(
            owner=user,
            flow=flow,
            cron_expr=cron_expr,
            enabled=enabled,
        )
    return _make


@pytest.mark.django_db
class TestScheduleListView:
    def test_requires_login(self, client):
        response = client.get(reverse('scheduler:list'))
        assert response.status_code == 302
        assert '/accounts/login/' in response['Location']

    def test_shows_schedules_from_all_users(self, auth_client, regular_user, admin_user, make_flow, make_schedule):
        make_schedule(regular_user, make_flow(regular_user), cron_expr='0 1 * * *')
        make_schedule(admin_user, make_flow(admin_user), cron_expr='0 2 * * *')
        response = auth_client.get(reverse('scheduler:list'))
        assert response.status_code == 200
        schedules = list(response.context['schedules'])
        assert {s.owner for s in schedules} == {regular_user, admin_user}
        assert len(schedules) == 2


@pytest.mark.django_db
class TestScheduleCreateView:
    def test_create_form_renders(self, admin_client):
        response = admin_client.get(reverse('scheduler:create'))
        assert response.status_code == 200

    def test_create_schedule(self, admin_client, admin_user, make_flow):
        flow = make_flow(admin_user)
        with patch('apps.scheduler.views._sync_celery_beat'):
            response = admin_client.post(reverse('scheduler:create'), {
                'flow': flow.pk,
                'cron_expr': '0 3 * * *',
                'enabled': True,
            })
        assert response.status_code == 302
        assert ScheduledTransfer.objects.filter(owner=admin_user, flow=flow).exists()

    def test_create_calls_sync_celery_beat(self, admin_client, admin_user, make_flow):
        flow = make_flow(admin_user)
        with patch('apps.scheduler.views._sync_celery_beat') as mock_sync:
            admin_client.post(reverse('scheduler:create'), {
                'flow': flow.pk,
                'cron_expr': '*/5 * * * *',
                'enabled': True,
            })
        mock_sync.assert_called_once()

    def test_can_use_other_users_flow(self, admin_client, admin_user, regular_user, make_flow):
        other_flow = make_flow(regular_user)
        with patch('apps.scheduler.views._sync_celery_beat'):
            response = admin_client.post(reverse('scheduler:create'), {
                'flow': other_flow.pk,
                'cron_expr': '0 3 * * *',
                'enabled': True,
            })
        assert response.status_code == 302
        assert ScheduledTransfer.objects.filter(owner=admin_user, flow=other_flow).exists()


@pytest.mark.django_db
class TestScheduleEditView:
    def test_edit_form_renders(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user))
        response = admin_client.get(reverse('scheduler:edit', args=[sched.pk]))
        assert response.status_code == 200

    def test_edit_saves_changes(self, admin_client, regular_user, make_flow, make_schedule):
        flow = make_flow(regular_user)
        sched = make_schedule(regular_user, flow, cron_expr='0 1 * * *')
        with patch('apps.scheduler.views._sync_celery_beat'):
            response = admin_client.post(reverse('scheduler:edit', args=[sched.pk]), {
                'flow': flow.pk,
                'cron_expr': '0 5 * * *',
                'enabled': True,
            })
        assert response.status_code == 302
        sched.refresh_from_db()
        assert sched.cron_expr == '0 5 * * *'

    def test_edit_returns_200_for_other_users_schedule(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user))
        response = admin_client.get(reverse('scheduler:edit', args=[sched.pk]))
        assert response.status_code == 200

    def test_operator_cannot_edit_schedule(self, auth_client, admin_user, make_flow, make_schedule):
        sched = make_schedule(admin_user, make_flow(admin_user))
        response = auth_client.get(reverse('scheduler:edit', args=[sched.pk]))
        assert response.status_code == 403

    def test_readonly_cannot_edit_schedule(self, readonly_client, admin_user, make_flow, make_schedule):
        sched = make_schedule(admin_user, make_flow(admin_user))
        response = readonly_client.post(reverse('scheduler:edit', args=[sched.pk]), {'cron_expr': '0 0 * * *'})
        assert response.status_code == 403


@pytest.mark.django_db
class TestScheduleToggleView:
    def test_toggle_disables_active_schedule(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user), enabled=True)
        with patch('apps.scheduler.views._sync_celery_beat'):
            response = admin_client.post(reverse('scheduler:toggle', args=[sched.pk]))
        assert response.status_code == 302
        sched.refresh_from_db()
        assert sched.enabled is False

    def test_toggle_enables_inactive_schedule(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user), enabled=False)
        with patch('apps.scheduler.views._sync_celery_beat'):
            response = admin_client.post(reverse('scheduler:toggle', args=[sched.pk]))
        assert response.status_code == 302
        sched.refresh_from_db()
        assert sched.enabled is True

    def test_toggle_get_returns_405(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user))
        response = admin_client.get(reverse('scheduler:toggle', args=[sched.pk]))
        assert response.status_code == 405

    def test_toggle_returns_302_for_other_users_schedule(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user))
        with patch('apps.scheduler.views._sync_celery_beat'):
            response = admin_client.post(reverse('scheduler:toggle', args=[sched.pk]))
        assert response.status_code == 302

    def test_toggle_calls_sync_celery_beat(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user))
        with patch('apps.scheduler.views._sync_celery_beat') as mock_sync:
            admin_client.post(reverse('scheduler:toggle', args=[sched.pk]))
        mock_sync.assert_called_once_with(sched)


@pytest.mark.django_db
class TestScheduleDeleteView:
    def test_delete_removes_schedule(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user))
        with patch('apps.scheduler.views._delete_celery_beat'):
            response = admin_client.post(reverse('scheduler:delete', args=[sched.pk]))
        assert response.status_code == 302
        assert not ScheduledTransfer.objects.filter(pk=sched.pk).exists()

    def test_delete_calls_delete_celery_beat(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user))
        with patch('apps.scheduler.views._delete_celery_beat') as mock_del:
            admin_client.post(reverse('scheduler:delete', args=[sched.pk]))
        # Django sets pk=None on the instance after delete(), so we check call count only
        assert mock_del.call_count == 1

    def test_delete_returns_302_for_other_users_schedule(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user))
        with patch('apps.scheduler.views._delete_celery_beat'):
            response = admin_client.post(reverse('scheduler:delete', args=[sched.pk]))
        assert response.status_code == 302

    def test_delete_get_returns_405(self, admin_client, regular_user, make_flow, make_schedule):
        sched = make_schedule(regular_user, make_flow(regular_user))
        response = admin_client.get(reverse('scheduler:delete', args=[sched.pk]))
        assert response.status_code == 405


@pytest.mark.django_db
class TestOrgWideVisibilityAndAdminOnly:
    def test_operator_sees_schedule_created_by_another_user(self, auth_client, django_user_model, make_flow):
        from apps.scheduler.models import ScheduledTransfer
        other = django_user_model.objects.create_user(username='sother1', password='p', role='admin')
        flow = make_flow(other)
        ScheduledTransfer.objects.create(owner=other, flow=flow, cron_expr='0 3 * * *', enabled=True)
        resp = auth_client.get('/scheduler/')
        assert resp.status_code == 200
        assert flow.name.encode() in resp.content

    def test_operator_cannot_create_schedule(self, auth_client):
        resp = auth_client.get('/scheduler/new/')
        assert resp.status_code == 403

    def test_operator_cannot_toggle_schedule(self, auth_client, django_user_model, make_flow):
        from apps.scheduler.models import ScheduledTransfer
        other = django_user_model.objects.create_user(username='sother2', password='p', role='admin')
        flow = make_flow(other)
        sched = ScheduledTransfer.objects.create(owner=other, flow=flow, cron_expr='0 3 * * *', enabled=True)
        resp = auth_client.post(f'/scheduler/{sched.pk}/toggle/')
        assert resp.status_code == 403

    def test_readonly_cannot_delete_schedule(self, readonly_client, django_user_model, make_flow):
        from apps.scheduler.models import ScheduledTransfer
        other = django_user_model.objects.create_user(username='sother3', password='p', role='admin')
        flow = make_flow(other)
        sched = ScheduledTransfer.objects.create(owner=other, flow=flow, cron_expr='0 3 * * *', enabled=True)
        resp = readonly_client.post(f'/scheduler/{sched.pk}/delete/')
        assert resp.status_code == 403


@pytest.mark.django_db
class TestScheduledTransferFormOrgWideFlows:
    def test_form_offers_flows_from_other_users(self, django_user_model, make_flow):
        from apps.scheduler.forms import ScheduledTransferForm
        owner = django_user_model.objects.create_user(username='flowowner', password='p')
        flow = make_flow(owner)
        requester = django_user_model.objects.create_user(username='requester2', password='p', role='admin')
        form = ScheduledTransferForm(user=requester)
        assert flow in form.fields['flow'].queryset


@pytest.mark.django_db
class TestScheduleAuditLog:
    def test_create_writes_audit_log_entry(self, admin_client, admin_user, make_flow):
        from apps.audit_log.models import ConfigAuditLog
        flow = make_flow(admin_user)
        with patch('apps.scheduler.views._sync_celery_beat'):
            admin_client.post(reverse('scheduler:create'), {
                'flow': flow.pk,
                'cron_expr': '0 3 * * *',
                'enabled': True,
            })
        entry = ConfigAuditLog.objects.get()
        assert entry.user == admin_user
        assert entry.action == 'created'
        assert entry.model_name == 'ScheduledTransfer'

    def test_edit_writes_audit_log_with_field_diff(self, admin_client, admin_user, regular_user, make_flow, make_schedule):
        from apps.audit_log.models import ConfigAuditLog
        flow = make_flow(regular_user)
        sched = make_schedule(regular_user, flow, cron_expr='0 1 * * *')
        with patch('apps.scheduler.views._sync_celery_beat'):
            admin_client.post(reverse('scheduler:edit', args=[sched.pk]), {
                'flow': flow.pk,
                'cron_expr': '0 5 * * *',
                'enabled': True,
            })
        entry = ConfigAuditLog.objects.get()
        assert entry.user == admin_user
        assert entry.action == 'updated'
        assert entry.model_name == 'ScheduledTransfer'
        assert entry.changed_fields['cron_expr'] == ['0 1 * * *', '0 5 * * *']

    def test_edit_without_real_changes_writes_no_audit_entry(self, admin_client, regular_user, make_flow, make_schedule):
        from apps.audit_log.models import ConfigAuditLog
        flow = make_flow(regular_user)
        sched = make_schedule(regular_user, flow, cron_expr='0 1 * * *', enabled=True)
        with patch('apps.scheduler.views._sync_celery_beat'):
            admin_client.post(reverse('scheduler:edit', args=[sched.pk]), {
                'flow': flow.pk,
                'cron_expr': '0 1 * * *',
                'enabled': True,
            })
        assert ConfigAuditLog.objects.count() == 0

    def test_toggle_writes_audit_log_entry(self, admin_client, admin_user, regular_user, make_flow, make_schedule):
        from apps.audit_log.models import ConfigAuditLog
        sched = make_schedule(regular_user, make_flow(regular_user), enabled=True)
        with patch('apps.scheduler.views._sync_celery_beat'):
            admin_client.post(reverse('scheduler:toggle', args=[sched.pk]))
        entry = ConfigAuditLog.objects.get()
        assert entry.user == admin_user
        assert entry.action == 'updated'
        assert entry.model_name == 'ScheduledTransfer'
        assert entry.changed_fields == {'enabled': ['True', 'False']}

    def test_delete_writes_audit_log_entry(self, admin_client, admin_user, regular_user, make_flow, make_schedule):
        from apps.audit_log.models import ConfigAuditLog
        sched = make_schedule(regular_user, make_flow(regular_user))
        with patch('apps.scheduler.views._delete_celery_beat'):
            admin_client.post(reverse('scheduler:delete', args=[sched.pk]))
        entry = ConfigAuditLog.objects.get()
        assert entry.user == admin_user
        assert entry.action == 'deleted'
        assert entry.model_name == 'ScheduledTransfer'
