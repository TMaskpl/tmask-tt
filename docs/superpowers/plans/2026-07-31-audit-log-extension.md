# Rozszerzenie audit logu o User i ScheduledTransfer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rozszerzyć istniejący `ConfigAuditLog` (#19, `apps.audit_log`) o rejestrowanie zmian na `User` (`apps.accounts`) i `ScheduledTransfer` (`apps.scheduler`) — dziś audytowane są tylko `Connection`, `Flow` i `MaskingRule`.

**Architecture:** Zero zmian w `apps.audit_log` (model/serwis/szablon). Wyłącznie dopisanie wywołań istniejącego serwisu (`log_created`/`log_updated`/`log_deleted`/`diff_fields` z `apps/audit_log/services.py`) w czterech widokach dwóch app: `apps/accounts/views.py` (`user_create`, `change_user_role`) i `apps/scheduler/views.py` (`schedule_create`, `schedule_edit`, `schedule_toggle`, `schedule_delete`) — dokładnie ten sam wzorzec, który już działa dla `Connection`/`Flow`/`MaskingRule`.

**Tech Stack:** Django 5, pytest-django, istniejące fixtures `admin_client`/`auth_client`/`regular_user`/`admin_user`/`make_flow` z `services/web/conftest.py`.

## Global Constraints

- Model `ConfigAuditLog`, `services.py` i `templates/audit_log/list.html` pozostają **niezmienione** — tylko nowe punkty wywołania w widokach.
- Logowanie wyłącznie przez jawne wywołania w widokach (nie sygnały `post_save`/`post_delete`) — spójne z decyzją z #19.
- Żadne pole `User`/`ScheduledTransfer` objęte tym zadaniem nie jest sekretem — `secret_fields` nie jest używane.
- Poza zakresem: usuwanie kont użytkowników (widok nie istnieje, nie dodawać), `Organization`, `ApiToken`.
- Log audytu ma powstać dopiero **po** udanym zakończeniu operacji end-to-end (np. po `_sync_celery_beat`, nie przed) — spójność: wpis istnieje wtedy i tylko wtedy, gdy operacja faktycznie się powiodła.
- Spec źródłowy: `docs/superpowers/specs/2026-07-31-audit-log-extension-design.md`.

---

### Task 1: Audit log dla User (create + zmiana roli)

**Files:**
- Modify: `services/web/apps/accounts/views.py:14-17` (importy), `services/web/apps/accounts/views.py:108-129` (`change_user_role`), `services/web/apps/accounts/views.py:132-139` (`user_create`)
- Test: `services/web/apps/accounts/tests/test_views.py`

**Interfaces:**
- Consumes: `apps.audit_log.services.log_created(user, instance)`, `apps.audit_log.services.log_updated(user, instance, changed_fields: dict)` — istniejące sygnatury, bez zmian.
- Produces: nic dla kolejnych tasków (Task 2 jest niezależny, dotyka innego pliku).

- [ ] **Step 1: Napisz failing testy dla `user_create`**

Dodaj na końcu pliku `services/web/apps/accounts/tests/test_views.py` (plik już istnieje, ma `@pytest.mark.django_db class TestUserCreate:` — dopisz metodę do tej klasy, zachowując wcięcie):

```python
    def test_create_writes_audit_log_entry(self, admin_client, admin_user, django_user_model):
        from apps.audit_log.models import ConfigAuditLog
        admin_client.post('/accounts/users/new/', {
            'username': 'auditeduser',
            'email': 'audited@example.com',
            'role': 'operator',
            'password1': 'a-decent-password-1',
            'password2': 'a-decent-password-1',
        })
        entry = ConfigAuditLog.objects.get()
        assert entry.user == admin_user
        assert entry.action == 'created'
        assert entry.model_name == 'User'
        assert entry.object_repr == 'auditeduser'
```

**Step 1b:** Dodaj nową klasę testową na końcu pliku (poniżej `TestUserCreate`) dla `change_user_role`:

```python
@pytest.mark.django_db
class TestChangeUserRoleAuditLog:
    def test_change_role_writes_audit_log_with_diff(self, admin_client, admin_user, regular_user):
        from apps.audit_log.models import ConfigAuditLog
        admin_client.post(f'/accounts/users/{regular_user.pk}/role/', {'role': 'readonly'})
        entry = ConfigAuditLog.objects.get()
        assert entry.user == admin_user
        assert entry.action == 'updated'
        assert entry.model_name == 'User'
        assert entry.changed_fields == {'role': ['operator', 'readonly']}

    def test_change_role_to_same_value_writes_no_audit_entry(self, admin_client, regular_user):
        from apps.audit_log.models import ConfigAuditLog
        admin_client.post(f'/accounts/users/{regular_user.pk}/role/', {'role': 'operator'})
        assert ConfigAuditLog.objects.count() == 0

    def test_rejected_role_change_writes_no_audit_entry(self, admin_client, admin_user):
        from apps.audit_log.models import ConfigAuditLog
        admin_client.post(f'/accounts/users/{admin_user.pk}/role/', {'role': 'operator'})
        assert ConfigAuditLog.objects.count() == 0
```

(Trzeci test wykorzystuje istniejącą ochronę "nie można odebrać roli ostatniemu Adminowi" — `admin_user` z fixture jest jedynym adminem, więc próba zmiany jego roli jest odrzucana wcześniej w widoku, przed jakąkolwiek zmianą — audytu też nie powinno być.)

- [ ] **Step 2: Uruchom testy i potwierdź, że failują**

Run: `docker compose run --rm web python -m pytest apps/accounts/tests/test_views.py -k "audit_log or AuditLog" -v`
Expected: FAIL — `test_create_writes_audit_log_entry` i `test_change_role_writes_audit_log_with_diff` failują z `ConfigAuditLog.DoesNotExist` (brak wpisu, bo `.get()` na pustym query); `test_change_role_to_same_value_writes_no_audit_entry` i `test_rejected_role_change_writes_no_audit_entry` **przechodzą już teraz** (bo dziś w ogóle nic nie loguje) — to oczekiwane, nie jest to regresja testu, po prostu te dwa asercje "no entry" są already-true. Kluczowe jest, że pierwsze dwa testy widocznie failują z powodu braku implementacji.

- [ ] **Step 3: Zaimplementuj logowanie w `apps/accounts/views.py`**

Zmień import w linii 16 (dodaj nową linię po `from .permissions import require_role`):

```python
from .permissions import require_role
from apps.audit_log.services import log_created, log_updated
```

Zmień `change_user_role` (linie 108-129) — dodaj przechwycenie starej wartości przed mutacją i log po zapisie, wewnątrz tego samego bloku `transaction.atomic()` żeby log nigdy nie powstał dla odrzuconej zmiany:

```python
@require_role(ROLE_ADMIN)
@require_POST
def change_user_role(request, pk):
    user_model = get_user_model()
    new_role = request.POST.get('role', '')
    valid_roles = dict(ROLE_CHOICES)
    if new_role not in valid_roles:
        messages.error(request, 'Nieprawidłowa rola.')
        return redirect(USERS_LIST)
    with transaction.atomic():
        target = get_object_or_404(user_model.objects.select_for_update(), pk=pk)
        if target.role == ROLE_ADMIN and new_role != ROLE_ADMIN:
            remaining_admins = user_model.objects.select_for_update().filter(
                role=ROLE_ADMIN
            ).exclude(pk=target.pk).count()
            if remaining_admins == 0:
                messages.error(request, 'Nie można odebrać roli Admin ostatniemu administratorowi.')
                return redirect(USERS_LIST)
        old_role = target.role
        target.role = new_role
        target.save(update_fields=['role'])
        if old_role != new_role:
            log_updated(request.user, target, {'role': [old_role, new_role]})
    messages.success(request, f'Rola {target.username} zmieniona na {valid_roles[new_role]}.')
    return redirect(USERS_LIST)
```

Zmień `user_create` (linie 132-139) — dodaj log po zapisie formularza:

```python
@require_role(ROLE_ADMIN)
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        log_created(request.user, user)
        messages.success(request, f'Użytkownik {user.username} utworzony z rolą {user.get_role_display()}.')
        return redirect(USERS_LIST)
    return render(request, 'users/create.html', {'form': form})
```

- [ ] **Step 4: Uruchom testy i potwierdź, że przechodzą**

Run: `docker compose run --rm web python -m pytest apps/accounts/tests/test_views.py -v`
Expected: PASS — cały plik, wliczając wszystkie 4 nowe testy oraz wszystkie istniejące testy `TestUserCreate`/`TestChangeUserRole` (upewnij się, że stare testy tych klas dalej przechodzą — `change_user_role` i `user_create` mają teraz dodatkową linię kodu, ale niezmienioną logikę biznesową).

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/accounts/views.py services/web/apps/accounts/tests/test_views.py
git commit -m "feat(audit-log): log User create and role changes (#29)"
```

---

### Task 2: Audit log dla ScheduledTransfer (create/edit/toggle/delete)

**Files:**
- Modify: `services/web/apps/scheduler/views.py` (cały plik, 82 linie — importy + 4 widoki)
- Test: `services/web/apps/scheduler/tests/test_views.py`

**Interfaces:**
- Consumes: `apps.audit_log.services.log_created(user, instance)`, `log_updated(user, instance, changed_fields: dict)`, `log_deleted(user, instance)`, `diff_fields(old_instance, new_instance, fields: list, secret_fields=None) -> dict` — istniejące sygnatury, bez zmian.
- Produces: nic dla kolejnych tasków — to ostatni task planu.

- [ ] **Step 1: Napisz failing testy**

Dodaj do `services/web/apps/scheduler/tests/test_views.py`, na końcu pliku (plik ma już fixture `make_schedule` i fixtures `admin_client`/`make_flow`/`regular_user`/`admin_user` z `services/web/conftest.py`, dostępne globalnie — nic nowego do zaimportowania poza `ConfigAuditLog`):

```python
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
```

- [ ] **Step 2: Uruchom testy i potwierdź, że failują**

Run: `docker compose run --rm web python -m pytest apps/scheduler/tests/test_views.py -k AuditLog -v`
Expected: FAIL — `test_create_writes_audit_log_entry`, `test_edit_writes_audit_log_with_field_diff`, `test_toggle_writes_audit_log_entry`, `test_delete_writes_audit_log_entry` failują z `ConfigAuditLog.DoesNotExist`. `test_edit_without_real_changes_writes_no_audit_entry` przechodzi już teraz (nic dziś nie loguje) — to oczekiwane, sygnał regresji dają pozostałe cztery.

- [ ] **Step 3: Zaimplementuj logowanie w `apps/scheduler/views.py`**

Zastąp całą zawartość pliku `services/web/apps/scheduler/views.py`:

```python
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN, ROLE_READONLY
from apps.audit_log.services import log_created, log_updated, log_deleted, diff_fields
from .models import ScheduledTransfer
from .forms import ScheduledTransferForm

_SCHEDULER_LIST = 'scheduler:list'
SCHEDULE_TRACKED_FIELDS = ['flow', 'cron_expr', 'enabled']


@require_role(ROLE_READONLY)
def schedule_list(request):
    schedules = ScheduledTransfer.objects.all().select_related('flow', 'flow__source_conn', 'flow__dest_conn')
    return render(request, 'scheduler/list.html', {'schedules': schedules})


@require_role(ROLE_ADMIN)
def schedule_create(request):
    form = ScheduledTransferForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        sched = form.save(commit=False)
        sched.owner = request.user
        sched.save()
        _sync_celery_beat(sched)
        log_created(request.user, sched)
        return redirect(_SCHEDULER_LIST)
    return render(request, 'scheduler/form.html', {'form': form, 'action': 'CREATE'})


@require_role(ROLE_ADMIN)
def schedule_edit(request, pk):
    sched = get_object_or_404(ScheduledTransfer, pk=pk)
    form = ScheduledTransferForm(request.POST or None, instance=sched, user=request.user)
    if request.method == 'POST' and form.is_valid():
        before = ScheduledTransfer.objects.get(pk=sched.pk)
        form.save()
        _sync_celery_beat(sched)
        changes = diff_fields(before, sched, SCHEDULE_TRACKED_FIELDS)
        log_updated(request.user, sched, changes)
        return redirect(_SCHEDULER_LIST)
    return render(request, 'scheduler/form.html', {'form': form, 'action': 'EDIT', 'sched': sched})


@require_role(ROLE_ADMIN)
@require_POST
def schedule_toggle(request, pk):
    sched = get_object_or_404(ScheduledTransfer, pk=pk)
    old_enabled = sched.enabled
    sched.enabled = not sched.enabled
    sched.save(update_fields=['enabled'])
    _sync_celery_beat(sched)
    log_updated(request.user, sched, {'enabled': [str(old_enabled), str(sched.enabled)]})
    return redirect(_SCHEDULER_LIST)


@require_role(ROLE_ADMIN)
@require_POST
def schedule_delete(request, pk):
    sched = get_object_or_404(ScheduledTransfer, pk=pk)
    log_deleted(request.user, sched)
    _delete_celery_beat(sched)
    sched.delete()
    return redirect(_SCHEDULER_LIST)


def _sync_celery_beat(sched: ScheduledTransfer):
    from django_celery_beat.models import PeriodicTask, CrontabSchedule
    import json
    minute, hour, day_of_month, month_of_year, day_of_week = sched.cron_expr.split()
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=minute, hour=hour, day_of_month=day_of_month,
        month_of_year=month_of_year, day_of_week=day_of_week,
    )
    task_name = f'scheduled_transfer_{sched.pk}'
    PeriodicTask.objects.update_or_create(
        name=task_name,
        defaults={
            'crontab': crontab,
            'task': 'transfers.execute',
            'kwargs': json.dumps({'job_id': None, 'scheduled_id': sched.pk}),
            'enabled': sched.enabled,
        }
    )


def _delete_celery_beat(sched: ScheduledTransfer):
    from django_celery_beat.models import PeriodicTask
    PeriodicTask.objects.filter(name=f'scheduled_transfer_{sched.pk}').delete()
```

(Jedyne zmiany względem oryginału: nowy import `from apps.audit_log.services import ...`, nowa stała `SCHEDULE_TRACKED_FIELDS`, i po jednej nowej linii `log_*(...)` w każdym z czterech widoków — `_sync_celery_beat`/`_delete_celery_beat` na dole pliku bez zmian.)

- [ ] **Step 4: Uruchom testy i potwierdź, że przechodzą**

Run: `docker compose run --rm web python -m pytest apps/scheduler/tests/test_views.py -v`
Expected: PASS — cały plik, wliczając wszystkie 5 nowych testów oraz wszystkie istniejące testy (`TestScheduleCreateView`, `TestScheduleEditView`, `TestScheduleToggleView`, `TestScheduleDeleteView`, `TestOrgWideVisibilityAndAdminOnly`, `TestScheduledTransferFormOrgWideFlows`) — w szczególności `test_create_calls_sync_celery_beat`, `test_toggle_calls_sync_celery_beat`, `test_delete_calls_delete_celery_beat`, które asercją `mock_sync.assert_called_once()`/`assert_called_once_with(sched)` weryfikują, że kolejność wywołań (`_sync_celery_beat` / `_delete_celery_beat` wciąż wywoływane dokładnie raz) się nie zmieniła.

- [ ] **Step 5: Uruchom pełny suite web, żeby wykluczyć regresję poza tymi dwoma plikami**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/ -q`
Expected: PASS — wszystkie testy (baseline przed tym zadaniem: 561/561), teraz 561 + 4 (Task 1) + 5 (Task 2) = 570/570.

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/scheduler/views.py services/web/apps/scheduler/tests/test_views.py
git commit -m "feat(audit-log): log ScheduledTransfer create/edit/toggle/delete (#29)"
```
