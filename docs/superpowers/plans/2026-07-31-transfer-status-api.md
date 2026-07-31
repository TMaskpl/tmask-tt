# Read-only REST API statusu transferów — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rozszerzyć `apps.api` o listę `TransferJob`, i o pełne pokrycie (status + lista) `DbTransferJob` — dziś tylko `TransferJob` ma pojedynczy status endpoint, `DbTransferJob` jest całkowicie niewidoczny przez API.

**Architecture:** Cztery endpointy GET w `apps/api/views.py`, wszystkie za istniejącym `@require_api_token` (bez bramki roli — org-wide odczyt, spójnie z dzisiejszym `job_status`). Dwie pary serializer+widok, jedna wspólna funkcja walidacji filtra `?status=`, jedna wspólna stała cap rozmiaru listy.

**Tech Stack:** Django 5, pytest-django, istniejące fixtures `admin_client`/`regular_user`/`admin_user`/`make_connection`/`make_flow`/`make_api_token` z `services/web/conftest.py`.

## Global Constraints

- Istniejący kontrakt `job_status` (`job_id`, `status`, `started_at`, `finished_at`, `error`) nie traci ani nie zmienia znaczenia żadnego pola — tylko dodaje nowe (`connection_id`, `flow_id`, `source_path`, `destination_path`, `created_at`).
- Żadna bramka roli na czterech endpointach odczytu (`job_status`, `job_list`, `db_job_status`, `db_job_list`) — dowolny ważny `ApiToken` czyta dowolny job, dowolnego właściciela.
- Brak pełnej paginacji (offset/next-link) — tylko opcjonalny `?status=` + stały cap `_LIST_PAGE_SIZE = 200`.
- `table_name` pusty (`''`) → `null` w JSON (idiom `x or None`, spójny z istniejącym `error_message or None`).
- Dwie równoległe rodziny endpointów (`jobs/*` dla `TransferJob`, `db-jobs/*` dla `DbTransferJob`) — bez zunifikowanego endpointu mieszającego oba typy.
- Puste listy (filtr bez wyników) → `200 {"jobs": []}`, nigdy `404`.
- Nieprawidłowa wartość `?status=` → `400 {"error": "Invalid status. Choices: pending, running, done, failed, cancelled"}`.
- Spec źródłowy: `docs/superpowers/specs/2026-07-31-transfer-status-api-design.md`.

---

### Task 1: TransferJob — rozszerzenie `job_status` + nowy `job_list`

**Files:**
- Modify: `services/web/apps/api/views.py` (import, nowa stała `_LIST_PAGE_SIZE`, nowa funkcja `_parse_status_filter`, nowa funkcja `_serialize_transfer_job`, przepisany `job_status`, nowy `job_list`)
- Modify: `services/web/apps/api/urls.py` (nowy path `jobs/`)
- Test: `services/web/apps/api/tests/test_status.py`

**Interfaces:**
- Consumes: `apps.transfers.models.TransferJob`, `apps.transfers.models.STATUS_CHOICES` (istniejące, bez zmian), `apps.api.auth.require_api_token` (istniejący dekorator).
- Produces (używane przez Task 2): `_parse_status_filter(request, status_choices) -> tuple[str | None, JsonResponse | None]` — Task 2 wywoła tę samą funkcję z `DbTransferJob`'s `STATUS_CHOICES` (zaimportowanym pod aliasem, bo obie appki definiują stałą o tej samej nazwie). `_LIST_PAGE_SIZE` — stała modułowa, Task 2 reużywa tę samą wartość dla swojej listy.

- [ ] **Step 1: Napisz failing testy**

Otwórz `services/web/apps/api/tests/test_status.py`. Rozszerz istniejącą metodę `test_returns_200_with_job_fields` w klasie `TestJobStatusEndpoint` o assercje nowych pól (dopisz na końcu metody, po istniejących assercjach):

```python
        assert data['connection_id'] == conn.pk
        assert data['flow_id'] is None
        assert data['source_path'] == '/x'
        assert data['destination_path'] == '/y'
        assert 'created_at' in data and data['created_at'] is not None
```

Dodaj nową klasę na końcu pliku (poniżej `TestOrgWideJobStatus`):

```python
@pytest.mark.django_db
class TestJobListEndpoint:
    def _url(self):
        return reverse('api:job_list')

    def _get(self, client, raw_key, **params):
        return client.get(self._url(), params, HTTP_AUTHORIZATION=f'Token {raw_key}')

    def test_returns_all_jobs(self, client, regular_user, make_connection, make_api_token):
        conn = make_connection(regular_user)
        TransferJob.objects.create(owner=regular_user, connection=conn, source_path='/a', destination_path='/b')
        TransferJob.objects.create(owner=regular_user, connection=conn, source_path='/c', destination_path='/d')
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert len(data['jobs']) == 2

    def test_filters_by_status(self, client, regular_user, make_connection, make_api_token):
        conn = make_connection(regular_user)
        TransferJob.objects.create(owner=regular_user, connection=conn, source_path='/a', destination_path='/b', status=STATUS_DONE)
        failed = TransferJob.objects.create(owner=regular_user, connection=conn, source_path='/c', destination_path='/d', status=STATUS_FAILED)
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key, status='failed')
        assert response.status_code == 200
        data = response.json()
        assert len(data['jobs']) == 1
        assert data['jobs'][0]['job_id'] == failed.pk

    def test_invalid_status_returns_400(self, client, regular_user, make_api_token):
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key, status='not-a-real-status')
        assert response.status_code == 400
        assert 'Invalid status' in response.json()['error']

    def test_empty_list_returns_200_empty_array(self, client, regular_user, make_api_token):
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        assert response.json()['jobs'] == []

    def test_respects_page_size_cap(self, client, regular_user, make_connection, make_api_token):
        conn = make_connection(regular_user)
        TransferJob.objects.bulk_create([
            TransferJob(owner=regular_user, connection=conn, source_path='/x', destination_path='/y')
            for _ in range(205)
        ])
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        assert len(response.json()['jobs']) == 200

    def test_no_token_returns_403(self, client, regular_user):
        response = client.get(self._url())
        assert response.status_code == 403

    def test_shows_other_users_jobs(self, client, regular_user, admin_user, make_connection, make_api_token):
        other_conn = make_connection(admin_user)
        TransferJob.objects.create(owner=admin_user, connection=other_conn, source_path='/a', destination_path='/b')
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        assert len(response.json()['jobs']) == 1
```

Dodaj brakujący import na górze pliku (obok istniejącego `from apps.transfers.models import TransferJob, STATUS_DONE, STATUS_FAILED, STATUS_PENDING`) — sprawdź, czy `STATUS_DONE`/`STATUS_FAILED` już są zaimportowane (są, w istniejącej linii importu na górze pliku) — nic dodatkowego do importu nie jest potrzebne.

- [ ] **Step 2: Uruchom testy i potwierdź, że failują**

Run: `docker compose run --rm web python -m pytest apps/api/tests/test_status.py -v`
Expected: FAIL — `test_returns_200_with_job_fields` failuje na `KeyError: 'connection_id'` (nowe pola jeszcze nie istnieją w odpowiedzi), wszystkie testy `TestJobListEndpoint` failują z `NoReverseMatch` (URL `api:job_list` jeszcze nie istnieje).

- [ ] **Step 3: Zaimplementuj w `apps/api/views.py`**

Zastąp całą zawartość pliku `services/web/apps/api/views.py`:

```python
import json
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.models import ROLE_LEVEL, ROLE_OPERATOR
from apps.connections.models import Connection
from apps.flows.models import Flow
from apps.transfers.forms import _validate_transfer_path
from apps.transfers.models import TransferJob, STATUS_CHOICES
from celery import current_app
from .auth import require_api_token

_NOT_FOUND = 'Not found'
_FORBIDDEN = 'Operator or admin role required'
_LIST_PAGE_SIZE = 200


def _parse_status_filter(request, status_choices):
    """Reads ?status= from the query string and validates it against the
    given model's STATUS_CHOICES. Returns (status_or_None, error_response_or_None) —
    exactly one of the two is non-None."""
    status = request.GET.get('status')
    if not status:
        return None, None
    valid_values = [choice for choice, _ in status_choices]
    if status not in valid_values:
        error = JsonResponse(
            {'error': f"Invalid status. Choices: {', '.join(valid_values)}"},
            status=400,
        )
        return None, error
    return status, None


def _serialize_transfer_job(job):
    return {
        'job_id': job.pk,
        'status': job.status,
        'connection_id': job.connection_id,
        'flow_id': job.flow_id,
        'source_path': job.source_path,
        'destination_path': job.destination_path,
        'created_at': job.created_at.isoformat(),
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        'error': job.error_message or None,
    }


@csrf_exempt
@require_POST
@require_api_token
def trigger_connection(request, connection_id):
    if request.api_user.role_level < ROLE_LEVEL[ROLE_OPERATOR]:
        return JsonResponse({'error': _FORBIDDEN}, status=403)
    try:
        connection = Connection.objects.get(pk=connection_id)
    except Connection.DoesNotExist:
        return JsonResponse({'error': _NOT_FOUND}, status=404)

    try:
        data = json.loads(request.body)
    except ValueError:
        data = {}

    source_path = data.get('source_path', '').strip()
    destination_path = data.get('destination_path', '').strip()

    if not source_path:
        return JsonResponse({'error': 'source_path required'}, status=400)
    if not destination_path:
        return JsonResponse({'error': 'destination_path required'}, status=400)

    try:
        _validate_transfer_path(source_path)
        _validate_transfer_path(destination_path)
    except ValidationError as exc:
        return JsonResponse({'error': exc.message}, status=400)

    job = TransferJob.objects.create(
        owner=request.api_user,
        connection=connection,
        source_path=source_path,
        destination_path=destination_path,
    )
    result = current_app.send_task('transfers.execute', kwargs={'job_id': job.pk})
    TransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)
    return JsonResponse({'job_id': job.pk}, status=202)


@csrf_exempt
@require_POST
@require_api_token
def trigger_flow(request, flow_id):
    if request.api_user.role_level < ROLE_LEVEL[ROLE_OPERATOR]:
        return JsonResponse({'error': _FORBIDDEN}, status=403)
    try:
        flow = Flow.objects.get(pk=flow_id)
    except Flow.DoesNotExist:
        return JsonResponse({'error': _NOT_FOUND}, status=404)

    job = TransferJob.objects.create(
        owner=request.api_user,
        flow=flow,
        source_path=flow.source_path,
        destination_path=flow.dest_path,
    )
    result = current_app.send_task('transfers.execute', kwargs={'job_id': job.pk})
    TransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)
    return JsonResponse({'job_id': job.pk}, status=202)


@require_api_token
def job_status(request, job_id):
    try:
        job = TransferJob.objects.get(pk=job_id)
    except TransferJob.DoesNotExist:
        return JsonResponse({'error': _NOT_FOUND}, status=404)

    return JsonResponse(_serialize_transfer_job(job))


@require_api_token
def job_list(request):
    status, error = _parse_status_filter(request, STATUS_CHOICES)
    if error:
        return error
    jobs = TransferJob.objects.all()
    if status:
        jobs = jobs.filter(status=status)
    jobs = jobs[:_LIST_PAGE_SIZE]
    return JsonResponse({'jobs': [_serialize_transfer_job(j) for j in jobs]})
```

(To jest przejściowa wersja pliku — Task 2 doda do niej `_serialize_db_transfer_job`, `db_job_status`, `db_job_list` i odpowiedni import `DbTransferJob`.)

- [ ] **Step 4: Zaktualizuj `apps/api/urls.py`**

Zastąp całą zawartość pliku `services/web/apps/api/urls.py`:

```python
from django.urls import path
from . import views

app_name = 'api'

urlpatterns = [
    path('transfers/trigger/connection/<int:connection_id>/', views.trigger_connection, name='trigger_connection'),
    path('transfers/trigger/flow/<int:flow_id>/', views.trigger_flow, name='trigger_flow'),
    path('jobs/<int:job_id>/status/', views.job_status, name='job_status'),
    path('jobs/', views.job_list, name='job_list'),
]
```

(Task 2 doda dwa kolejne wpisy `db-jobs/...` do tej samej listy.)

- [ ] **Step 5: Uruchom testy i potwierdź, że przechodzą**

Run: `docker compose run --rm web python -m pytest apps/api/tests/test_status.py -v`
Expected: PASS — cały plik, wliczając wszystkie istniejące testy (`TestJobStatusEndpoint`, `TestOrgWideJobStatus`) i wszystkie nowe testy `TestJobListEndpoint`. Sprawdź też, że `test_trigger.py` nie regresował (import w `views.py` się nie zmienił dla trigger endpointów):

Run: `docker compose run --rm web python -m pytest apps/api/ -v`
Expected: PASS — cały pakiet `apps/api/`.

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/api/views.py services/web/apps/api/urls.py services/web/apps/api/tests/test_status.py
git commit -m "feat(api): extend job_status contract + add job_list endpoint (#30)"
```

---

### Task 2: DbTransferJob — nowy `db_job_status` + nowy `db_job_list`

**Files:**
- Modify: `services/web/apps/api/views.py` (import `DbTransferJob` + `STATUS_CHOICES` pod aliasem, nowa funkcja `_serialize_db_transfer_job`, nowe widoki `db_job_status`/`db_job_list`)
- Modify: `services/web/apps/api/urls.py` (nowe paths `db-jobs/<int:job_id>/status/` i `db-jobs/`)
- Test: `services/web/apps/api/tests/test_db_status.py` (nowy plik)

**Interfaces:**
- Consumes: `apps.db_transfers.models.DbTransferJob`, `apps.db_transfers.models.STATUS_CHOICES` (istniejące, bez zmian), `_parse_status_filter(request, status_choices)` i `_LIST_PAGE_SIZE` z Task 1 (już w `apps/api/views.py`).
- Produces: nic dla kolejnych tasków — to ostatni task planu.

- [ ] **Step 1: Napisz failing testy**

Utwórz nowy plik `services/web/apps/api/tests/test_db_status.py`:

```python
import pytest
from django.urls import reverse
from apps.db_transfers.models import DbTransferJob


@pytest.mark.django_db
class TestDbJobStatusEndpoint:
    def _url(self, job_id):
        return reverse('api:db_job_status', args=[job_id])

    def _get(self, client, job_id, raw_key):
        return client.get(
            self._url(job_id),
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )

    def test_returns_200_with_job_fields(
        self, client, regular_user, make_connection, make_api_token
    ):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst,
            engine='postgres', table_name='users',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert data['job_id'] == job.pk
        assert data['status'] == 'pending'
        assert data['engine'] == 'postgres'
        assert data['source_connection_id'] == src.pk
        assert data['dest_connection_id'] == dst.pk
        assert data['table_name'] == 'users'
        assert data['created_at'] is not None
        assert data['started_at'] is None
        assert data['finished_at'] is None
        assert data['error'] is None

    def test_whole_db_transfer_has_null_table_name(
        self, client, regular_user, make_connection, make_api_token
    ):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst,
            engine='postgres', table_name='',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        assert response.json()['table_name'] is None

    def test_returns_done_status_with_timestamps(
        self, client, regular_user, make_connection, make_api_token
    ):
        from django.utils import timezone
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        now = timezone.now()
        job = DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst,
            engine='postgres', status='done', started_at=now, finished_at=now,
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'done'
        assert data['started_at'] is not None
        assert data['finished_at'] is not None

    def test_returns_failed_status_with_error(
        self, client, regular_user, make_connection, make_api_token
    ):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst,
            engine='postgres', status='failed', error_message='Connection refused',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        assert response.json()['error'] == 'Connection refused'

    def test_other_users_job_returns_200(
        self, client, regular_user, admin_user, make_connection, make_api_token
    ):
        src = make_connection(admin_user, kind='postgres', db_name='proddb', name='src2')
        dst = make_connection(admin_user, kind='postgres', db_name='testdb', name='dst2')
        job = DbTransferJob.objects.create(
            owner=admin_user, source_connection=src, dest_connection=dst, engine='postgres',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200

    def test_nonexistent_job_returns_404(self, client, regular_user, make_api_token):
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, 99999, raw_key)
        assert response.status_code == 404

    def test_no_token_returns_403(self, client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres',
        )
        response = client.get(self._url(job.pk))
        assert response.status_code == 403


@pytest.mark.django_db
class TestDbJobListEndpoint:
    def _url(self):
        return reverse('api:db_job_list')

    def _get(self, client, raw_key, **params):
        return client.get(self._url(), params, HTTP_AUTHORIZATION=f'Token {raw_key}')

    def test_returns_all_jobs(self, client, regular_user, make_connection, make_api_token):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        DbTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres')
        DbTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres', table_name='orders')
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        assert len(response.json()['jobs']) == 2

    def test_filters_by_status(self, client, regular_user, make_connection, make_api_token):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        DbTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres', status='done')
        failed = DbTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, engine='postgres', status='failed')
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key, status='failed')
        assert response.status_code == 200
        data = response.json()
        assert len(data['jobs']) == 1
        assert data['jobs'][0]['job_id'] == failed.pk

    def test_invalid_status_returns_400(self, client, regular_user, make_api_token):
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key, status='not-a-real-status')
        assert response.status_code == 400
        assert 'Invalid status' in response.json()['error']

    def test_empty_list_returns_200_empty_array(self, client, regular_user, make_api_token):
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, raw_key)
        assert response.status_code == 200
        assert response.json()['jobs'] == []

    def test_no_token_returns_403(self, client, regular_user):
        response = client.get(self._url())
        assert response.status_code == 403
```

- [ ] **Step 2: Uruchom testy i potwierdź, że failują**

Run: `docker compose run --rm web python -m pytest apps/api/tests/test_db_status.py -v`
Expected: FAIL — wszystkie testy failują z `NoReverseMatch` (`api:db_job_status`/`api:db_job_list` jeszcze nie istnieją).

- [ ] **Step 3: Zaimplementuj w `apps/api/views.py`**

Dodaj import na górze pliku (obok istniejącego `from apps.transfers.models import TransferJob, STATUS_CHOICES`):

```python
from apps.db_transfers.models import DbTransferJob, STATUS_CHOICES as DB_STATUS_CHOICES
```

(Alias konieczny — `apps.transfers.models.STATUS_CHOICES` i `apps.db_transfers.models.STATUS_CHOICES` to dwie różne stałe o tej samej nazwie w różnych modułach; bez aliasu drugi import nadpisałby pierwszy.)

Dodaj nową funkcję serializującą, zaraz po `_serialize_transfer_job`:

```python
def _serialize_db_transfer_job(job):
    return {
        'job_id': job.pk,
        'status': job.status,
        'engine': job.engine,
        'source_connection_id': job.source_connection_id,
        'dest_connection_id': job.dest_connection_id,
        'table_name': job.table_name or None,
        'created_at': job.created_at.isoformat(),
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        'error': job.error_message or None,
    }
```

Dodaj dwa nowe widoki na końcu pliku (po `job_list`):

```python
@require_api_token
def db_job_status(request, job_id):
    try:
        job = DbTransferJob.objects.get(pk=job_id)
    except DbTransferJob.DoesNotExist:
        return JsonResponse({'error': _NOT_FOUND}, status=404)

    return JsonResponse(_serialize_db_transfer_job(job))


@require_api_token
def db_job_list(request):
    status, error = _parse_status_filter(request, DB_STATUS_CHOICES)
    if error:
        return error
    jobs = DbTransferJob.objects.all()
    if status:
        jobs = jobs.filter(status=status)
    jobs = jobs[:_LIST_PAGE_SIZE]
    return JsonResponse({'jobs': [_serialize_db_transfer_job(j) for j in jobs]})
```

- [ ] **Step 4: Zaktualizuj `apps/api/urls.py`**

Dodaj dwie nowe linie do `urlpatterns` (po istniejącym `path('jobs/', views.job_list, name='job_list')`):

```python
    path('db-jobs/<int:job_id>/status/', views.db_job_status, name='db_job_status'),
    path('db-jobs/', views.db_job_list, name='db_job_list'),
```

Pełna zawartość `urlpatterns` po tej zmianie:

```python
urlpatterns = [
    path('transfers/trigger/connection/<int:connection_id>/', views.trigger_connection, name='trigger_connection'),
    path('transfers/trigger/flow/<int:flow_id>/', views.trigger_flow, name='trigger_flow'),
    path('jobs/<int:job_id>/status/', views.job_status, name='job_status'),
    path('jobs/', views.job_list, name='job_list'),
    path('db-jobs/<int:job_id>/status/', views.db_job_status, name='db_job_status'),
    path('db-jobs/', views.db_job_list, name='db_job_list'),
]
```

- [ ] **Step 5: Uruchom testy i potwierdź, że przechodzą**

Run: `docker compose run --rm web python -m pytest apps/api/tests/test_db_status.py -v`
Expected: PASS — wszystkie testy `TestDbJobStatusEndpoint` i `TestDbJobListEndpoint`.

- [ ] **Step 6: Uruchom pełny suite web, żeby wykluczyć regresję poza `apps/api/`**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/ -q`
Expected: PASS — wszystkie testy (baseline przed tym zadaniem: 570/570 — patrz `testy/Projekt-tmask-transporter-Testy.md`). Task 1 dodaje 6 nowych testów (`TestJobListEndpoint`), Task 2 dodaje 12 (`TestDbJobStatusEndpoint`: 7, `TestDbJobListEndpoint`: 5). Oczekiwany wynik: 570 + 6 + 12 = 588/588.

- [ ] **Step 7: Commit**

```bash
git add services/web/apps/api/views.py services/web/apps/api/urls.py services/web/apps/api/tests/test_db_status.py
git commit -m "feat(api): add DbTransferJob status and list endpoints (#30)"
```
