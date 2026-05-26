# REST API dla zewnętrznych triggerów — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodanie REST API z token auth umożliwiającego triggerowanie transferów (Connection i Flow) z zewnętrznych skryptów/CI pipeline oraz sprawdzanie statusu joba.

**Architecture:** Nowa izolowana app Django `apps/api/` z modelem `ApiToken` (SHA-256 hash w DB), dekoratorem `@require_api_token` i trzema JSON endpoints. Zarządzanie tokenami (generowanie, revoke) przez UI w istniejącym profilu użytkownika.

**Tech Stack:** Django 5.x, Celery (istniejące), pytest — zero nowych zależności.

**Spec:** `docs/superpowers/specs/2026-05-26-rest-api-external-triggers-design.md`

**Uruchamianie testów** (z katalogu projektu `tmask-tt/`):
```bash
docker compose run --rm web pytest apps/api/tests/ -v
docker compose run --rm web pytest apps/accounts/tests/ -v
```

---

## Mapa plików

### Nowe pliki
| Plik | Rola |
|------|------|
| `services/web/apps/api/__init__.py` | marker pakietu |
| `services/web/apps/api/models.py` | `ApiToken` model + `generate()` classmethod |
| `services/web/apps/api/auth.py` | `get_user_from_token()` + `@require_api_token` dekorator |
| `services/web/apps/api/views.py` | `trigger_connection`, `trigger_flow`, `job_status` |
| `services/web/apps/api/urls.py` | URL routing `/api/...` |
| `services/web/apps/api/migrations/__init__.py` | marker |
| `services/web/apps/api/tests/__init__.py` | marker |
| `services/web/apps/api/tests/test_auth.py` | testy dekoratora auth |
| `services/web/apps/api/tests/test_trigger.py` | testy trigger endpoints |
| `services/web/apps/api/tests/test_status.py` | testy job_status endpoint |
| `services/web/apps/accounts/tests/test_api_tokens.py` | testy UI generowania/revoke tokenów |

### Modyfikowane pliki
| Plik | Zmiana |
|------|--------|
| `services/web/config/settings/base.py` | dodaj `'apps.api'` do `INSTALLED_APPS` |
| `services/web/config/urls.py` | dodaj `path('api/', include('apps.api.urls'))` |
| `services/web/conftest.py` | dodaj fixture `make_api_token` |
| `services/web/apps/accounts/views.py` | dodaj `generate_api_token`, `revoke_api_token`, rozszerz `profile_view` |
| `services/web/apps/accounts/urls.py` | dodaj URL-e dla generate i revoke |
| `services/web/templates/accounts/profile.html` | dodaj sekcję `[ API TOKENS ]` i modal |

---

## Task 1: ApiToken model

**Files:**
- Create: `services/web/apps/api/__init__.py`
- Create: `services/web/apps/api/migrations/__init__.py`
- Create: `services/web/apps/api/tests/__init__.py`
- Create: `services/web/apps/api/models.py`
- Modify: `services/web/config/settings/base.py`

- [ ] **Step 1: Utwórz strukturę katalogów**

```bash
mkdir -p services/web/apps/api/migrations
mkdir -p services/web/apps/api/tests
touch services/web/apps/api/__init__.py
touch services/web/apps/api/migrations/__init__.py
touch services/web/apps/api/tests/__init__.py
```

- [ ] **Step 2: Napisz failing test dla modelu**

Utwórz `services/web/apps/api/tests/test_auth.py`:

```python
import hashlib
import pytest
from apps.api.models import ApiToken, MAX_TOKENS_PER_USER


@pytest.mark.django_db
class TestApiTokenModel:
    def test_generate_returns_token_and_raw_key(self, regular_user):
        token, raw_key = ApiToken.generate(regular_user, 'CI Jenkins')
        assert token.pk is not None
        assert token.user == regular_user
        assert token.label == 'CI Jenkins'
        assert len(raw_key) == 64
        assert token.key_hash == hashlib.sha256(raw_key.encode()).hexdigest()
        assert token.last_used_at is None

    def test_raw_key_not_stored_in_db(self, regular_user):
        token, raw_key = ApiToken.generate(regular_user, 'Test')
        assert token.key_hash != raw_key

    def test_max_tokens_constant_is_five(self):
        assert MAX_TOKENS_PER_USER == 5

    def test_ordering_newest_first(self, regular_user):
        t1, _ = ApiToken.generate(regular_user, 'First')
        t2, _ = ApiToken.generate(regular_user, 'Second')
        tokens = list(ApiToken.objects.filter(user=regular_user))
        assert tokens[0] == t2
        assert tokens[1] == t1
```

- [ ] **Step 3: Uruchom test — upewnij się że FAIL**

```bash
docker compose run --rm web pytest apps/api/tests/test_auth.py::TestApiTokenModel -v
```

Oczekiwane: `ModuleNotFoundError: No module named 'apps.api'`

- [ ] **Step 4: Utwórz `apps/api/models.py`**

```python
import hashlib
import secrets
from django.conf import settings
from django.db import models

MAX_TOKENS_PER_USER = 5


class ApiToken(models.Model):
    user         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='api_tokens'
    )
    label        = models.CharField(max_length=100)
    key_hash     = models.CharField(max_length=64, unique=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def generate(cls, user, label: str):
        raw_key = secrets.token_hex(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        token = cls.objects.create(user=user, label=label, key_hash=key_hash)
        return token, raw_key
```

- [ ] **Step 5: Zarejestruj app w INSTALLED_APPS**

W `services/web/config/settings/base.py` dodaj `'apps.api'` na końcu listy:

```python
INSTALLED_APPS = [
    # ... istniejące wpisy ...
    'apps.flows',
    'apps.api',           # ← dodaj tę linię
]
```

- [ ] **Step 6: Wygeneruj i uruchom migrację**

```bash
docker compose run --rm web python manage.py makemigrations api
docker compose run --rm web python manage.py migrate
```

Oczekiwane: `Applying api.0001_initial... OK`

- [ ] **Step 7: Uruchom testy — upewnij się że PASS**

```bash
docker compose run --rm web pytest apps/api/tests/test_auth.py::TestApiTokenModel -v
```

Oczekiwane: `4 passed`

- [ ] **Step 8: Commit**

```bash
git add services/web/apps/api/ services/web/config/settings/base.py
git commit -m "feat: add ApiToken model with SHA-256 key storage"
```

---

## Task 2: Auth dekorator

**Files:**
- Create: `services/web/apps/api/auth.py`
- Modify: `services/web/apps/api/tests/test_auth.py` (dopisz testy)
- Modify: `services/web/conftest.py` (dodaj fixture)

- [ ] **Step 1: Dodaj fixture `make_api_token` do conftest.py**

W `services/web/conftest.py` dopisz na końcu:

```python
@pytest.fixture
def make_api_token():
    from apps.api.models import ApiToken
    def _make(user, label='Test Token'):
        return ApiToken.generate(user, label)  # returns (token, raw_key)
    return _make
```

- [ ] **Step 2: Napisz failing testy dla dekoratora**

Dopisz do `services/web/apps/api/tests/test_auth.py`:

```python
import json
from django.test import RequestFactory
from django.http import JsonResponse
from apps.api.auth import require_api_token, get_user_from_token


@pytest.mark.django_db
class TestRequireApiToken:
    def test_valid_token_sets_api_user(self, rf, regular_user, make_api_token):
        _, raw_key = make_api_token(regular_user)
        request = rf.get('/', HTTP_AUTHORIZATION=f'Token {raw_key}')

        @require_api_token
        def dummy_view(request):
            return JsonResponse({'user': request.api_user.pk})

        response = dummy_view(request)
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['user'] == regular_user.pk

    def test_valid_token_updates_last_used_at(self, rf, regular_user, make_api_token):
        token, raw_key = make_api_token(regular_user)
        assert token.last_used_at is None
        request = rf.get('/', HTTP_AUTHORIZATION=f'Token {raw_key}')

        @require_api_token
        def dummy_view(request):
            return JsonResponse({})

        dummy_view(request)
        token.refresh_from_db()
        assert token.last_used_at is not None

    def test_missing_header_returns_403(self, rf, regular_user):
        request = rf.get('/')

        @require_api_token
        def dummy_view(request):
            return JsonResponse({})

        response = dummy_view(request)
        assert response.status_code == 403
        assert json.loads(response.content)['error'] == 'Invalid or missing token'

    def test_wrong_token_returns_403(self, rf, regular_user):
        request = rf.get('/', HTTP_AUTHORIZATION='Token wrongkey123')

        @require_api_token
        def dummy_view(request):
            return JsonResponse({})

        response = dummy_view(request)
        assert response.status_code == 403

    def test_malformed_header_returns_403(self, rf, regular_user):
        request = rf.get('/', HTTP_AUTHORIZATION='Bearer sometoken')

        @require_api_token
        def dummy_view(request):
            return JsonResponse({})

        response = dummy_view(request)
        assert response.status_code == 403
```

Uwaga: `rf` to pytest-django fixture `RequestFactory`. Dodaj import `rf` w conftest jeśli nie ma, lub użyj `django.test.RequestFactory` bezpośrednio.

- [ ] **Step 3: Uruchom testy — upewnij się że FAIL**

```bash
docker compose run --rm web pytest apps/api/tests/test_auth.py::TestRequireApiToken -v
```

Oczekiwane: `ImportError: cannot import name 'require_api_token' from 'apps.api.auth'`

- [ ] **Step 4: Utwórz `apps/api/auth.py`**

```python
import hashlib
from functools import wraps
from django.http import JsonResponse
from django.utils import timezone
from .models import ApiToken


def get_user_from_token(request):
    header = request.headers.get('Authorization', '')
    if not header.startswith('Token '):
        return None
    raw_key = header[6:]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    try:
        token = ApiToken.objects.select_related('user').get(key_hash=key_hash)
        token.last_used_at = timezone.now()
        token.save(update_fields=['last_used_at'])
        return token.user
    except ApiToken.DoesNotExist:
        return None


def require_api_token(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_user_from_token(request)
        if user is None:
            return JsonResponse({'error': 'Invalid or missing token'}, status=403)
        request.api_user = user
        return view_func(request, *args, **kwargs)
    return wrapper
```

- [ ] **Step 5: Uruchom testy — upewnij się że PASS**

```bash
docker compose run --rm web pytest apps/api/tests/test_auth.py -v
```

Oczekiwane: `9 passed`

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/api/auth.py services/web/apps/api/tests/test_auth.py services/web/conftest.py
git commit -m "feat: add @require_api_token decorator with SHA-256 token lookup"
```

---

## Task 3: URL routing

**Files:**
- Create: `services/web/apps/api/urls.py`
- Modify: `services/web/config/urls.py`

- [ ] **Step 1: Utwórz `apps/api/urls.py`**

```python
from django.urls import path
from . import views

app_name = 'api'

urlpatterns = [
    path('transfers/trigger/connection/<int:connection_id>/', views.trigger_connection, name='trigger_connection'),
    path('transfers/trigger/flow/<int:flow_id>/', views.trigger_flow, name='trigger_flow'),
    path('jobs/<int:job_id>/status/', views.job_status, name='job_status'),
]
```

- [ ] **Step 2: Zarejestruj w `config/urls.py`**

W `services/web/config/urls.py` dodaj przed ostatnim `path('')`:

```python
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('connections/', include('apps.connections.urls')),
    path('flows/', include('apps.flows.urls')),
    path('transfers/', include('apps.transfers.urls')),
    path('scheduler/', include('apps.scheduler.urls')),
    path('api/', include('apps.api.urls')),                   # ← dodaj tę linię
    path('', RedirectView.as_view(url='/transfers/', permanent=False)),
]
```

- [ ] **Step 3: Utwórz stub `apps/api/views.py`** (placeholder żeby URL routing działał)

```python
from django.http import JsonResponse
from .auth import require_api_token
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


@csrf_exempt
@require_POST
@require_api_token
def trigger_connection(request, connection_id):
    return JsonResponse({'status': 'not implemented'}, status=501)


@csrf_exempt
@require_POST
@require_api_token
def trigger_flow(request, flow_id):
    return JsonResponse({'status': 'not implemented'}, status=501)


@require_api_token
def job_status(request, job_id):
    return JsonResponse({'status': 'not implemented'}, status=501)
```

- [ ] **Step 4: Sprawdź że URL routing działa**

```bash
docker compose run --rm web python manage.py show_urls | grep api
```

Oczekiwane: 3 linie z `/api/transfers/trigger/connection/...`, `/api/transfers/trigger/flow/...`, `/api/jobs/...`

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/api/urls.py services/web/apps/api/views.py services/web/config/urls.py
git commit -m "feat: add api URL routing with stub views"
```

---

## Task 4: `trigger_connection` endpoint

**Files:**
- Modify: `services/web/apps/api/views.py`
- Create: `services/web/apps/api/tests/test_trigger.py`

- [ ] **Step 1: Napisz failing testy**

Utwórz `services/web/apps/api/tests/test_trigger.py`:

```python
import json
import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestTriggerConnectionEndpoint:
    def _url(self, connection_id):
        return reverse('api:trigger_connection', args=[connection_id])

    def _post(self, client, connection_id, raw_key, body):
        return client.post(
            self._url(connection_id),
            data=json.dumps(body),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )

    def test_valid_trigger_returns_202_with_job_id(
        self, client, regular_user, make_connection, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.execute_transfer.delay')
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, conn.pk, raw_key, {
            'source_path': '/data/file.tar',
            'destination_path': '/backup/',
        })
        assert response.status_code == 202
        data = response.json()
        assert 'job_id' in data
        assert isinstance(data['job_id'], int)

    def test_valid_trigger_creates_transfer_job(
        self, client, regular_user, make_connection, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.execute_transfer.delay')
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        self._post(client, conn.pk, raw_key, {
            'source_path': '/data/file.tar',
            'destination_path': '/backup/',
        })
        from apps.transfers.models import TransferJob
        job = TransferJob.objects.get(owner=regular_user, connection=conn)
        assert job.source_path == '/data/file.tar'
        assert job.destination_path == '/backup/'

    def test_valid_trigger_calls_celery_task(
        self, client, regular_user, make_connection, make_api_token, mocker
    ):
        mock_delay = mocker.patch('apps.api.views.execute_transfer.delay')
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, conn.pk, raw_key, {
            'source_path': '/data/file.tar',
            'destination_path': '/backup/',
        })
        data = response.json()
        mock_delay.assert_called_once_with(job_id=data['job_id'])

    def test_wrong_owner_connection_returns_404(
        self, client, regular_user, admin_user, make_connection, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.execute_transfer.delay')
        other_conn = make_connection(admin_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, other_conn.pk, raw_key, {
            'source_path': '/data/file.tar',
            'destination_path': '/backup/',
        })
        assert response.status_code == 404

    def test_missing_source_path_returns_400(
        self, client, regular_user, make_connection, make_api_token
    ):
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, conn.pk, raw_key, {
            'destination_path': '/backup/',
        })
        assert response.status_code == 400
        assert 'source_path' in response.json()['error']

    def test_missing_destination_path_returns_400(
        self, client, regular_user, make_connection, make_api_token
    ):
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, conn.pk, raw_key, {
            'source_path': '/data/file.tar',
        })
        assert response.status_code == 400
        assert 'destination_path' in response.json()['error']

    def test_no_token_returns_403(self, client, regular_user, make_connection):
        conn = make_connection(regular_user)
        response = client.post(
            self._url(conn.pk),
            data=json.dumps({'source_path': '/x', 'destination_path': '/y'}),
            content_type='application/json',
        )
        assert response.status_code == 403

    def test_get_method_returns_405(self, client, regular_user, make_connection, make_api_token):
        conn = make_connection(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = client.get(
            self._url(conn.pk),
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )
        assert response.status_code == 405
```

- [ ] **Step 2: Uruchom testy — upewnij się że FAIL**

```bash
docker compose run --rm web pytest apps/api/tests/test_trigger.py::TestTriggerConnectionEndpoint -v
```

Oczekiwane: testy failują (501 zamiast 202, import errors itp.)

- [ ] **Step 3: Zaimplementuj `trigger_connection` w `apps/api/views.py`**

Zastąp cały plik:

```python
import json
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.connections.models import Connection
from apps.flows.models import Flow
from apps.transfers.forms import _validate_transfer_path
from apps.transfers.models import TransferJob
from apps.transfers.tasks import execute_transfer
from .auth import require_api_token


@csrf_exempt
@require_POST
@require_api_token
def trigger_connection(request, connection_id):
    try:
        connection = Connection.objects.get(pk=connection_id, owner=request.api_user)
    except Connection.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
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
    execute_transfer.delay(job_id=job.pk)
    return JsonResponse({'job_id': job.pk}, status=202)


@csrf_exempt
@require_POST
@require_api_token
def trigger_flow(request, flow_id):
    return JsonResponse({'status': 'not implemented'}, status=501)


@require_api_token
def job_status(request, job_id):
    return JsonResponse({'status': 'not implemented'}, status=501)
```

- [ ] **Step 4: Uruchom testy — upewnij się że PASS**

```bash
docker compose run --rm web pytest apps/api/tests/test_trigger.py::TestTriggerConnectionEndpoint -v
```

Oczekiwane: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/api/views.py services/web/apps/api/tests/test_trigger.py
git commit -m "feat: implement POST /api/transfers/trigger/connection/<id>/ endpoint"
```

---

## Task 5: `trigger_flow` endpoint

**Files:**
- Modify: `services/web/apps/api/views.py`
- Modify: `services/web/apps/api/tests/test_trigger.py`

- [ ] **Step 1: Napisz failing testy**

Dopisz do `services/web/apps/api/tests/test_trigger.py`:

```python
@pytest.mark.django_db
class TestTriggerFlowEndpoint:
    def _url(self, flow_id):
        return reverse('api:trigger_flow', args=[flow_id])

    def _post(self, client, flow_id, raw_key, body=None):
        return client.post(
            self._url(flow_id),
            data=json.dumps(body or {}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )

    def test_valid_trigger_returns_202_with_job_id(
        self, client, regular_user, make_flow, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.execute_transfer.delay')
        flow = make_flow(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, flow.pk, raw_key)
        assert response.status_code == 202
        assert 'job_id' in response.json()

    def test_valid_trigger_creates_job_with_flow_paths(
        self, client, regular_user, make_flow, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.execute_transfer.delay')
        flow = make_flow(regular_user)
        _, raw_key = make_api_token(regular_user)
        self._post(client, flow.pk, raw_key)
        from apps.transfers.models import TransferJob
        job = TransferJob.objects.get(owner=regular_user, flow=flow)
        assert job.source_path == flow.source_path
        assert job.destination_path == flow.dest_path

    def test_wrong_owner_flow_returns_404(
        self, client, regular_user, admin_user, make_flow, make_api_token, mocker
    ):
        mocker.patch('apps.api.views.execute_transfer.delay')
        other_flow = make_flow(admin_user)
        _, raw_key = make_api_token(regular_user)
        response = self._post(client, other_flow.pk, raw_key)
        assert response.status_code == 404

    def test_no_token_returns_403(self, client, regular_user, make_flow):
        flow = make_flow(regular_user)
        response = client.post(
            self._url(flow.pk),
            data=json.dumps({}),
            content_type='application/json',
        )
        assert response.status_code == 403

    def test_get_method_returns_405(self, client, regular_user, make_flow, make_api_token):
        flow = make_flow(regular_user)
        _, raw_key = make_api_token(regular_user)
        response = client.get(self._url(flow.pk), HTTP_AUTHORIZATION=f'Token {raw_key}')
        assert response.status_code == 405
```

- [ ] **Step 2: Uruchom testy — upewnij się że FAIL**

```bash
docker compose run --rm web pytest apps/api/tests/test_trigger.py::TestTriggerFlowEndpoint -v
```

Oczekiwane: `501 Not Implemented` powoduje failure

- [ ] **Step 3: Zaimplementuj `trigger_flow` w `apps/api/views.py`**

Zamień stub `trigger_flow` na:

```python
@csrf_exempt
@require_POST
@require_api_token
def trigger_flow(request, flow_id):
    try:
        flow = Flow.objects.get(pk=flow_id, owner=request.api_user)
    except Flow.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    job = TransferJob.objects.create(
        owner=request.api_user,
        flow=flow,
        source_path=flow.source_path,
        destination_path=flow.dest_path,
    )
    execute_transfer.delay(job_id=job.pk)
    return JsonResponse({'job_id': job.pk}, status=202)
```

- [ ] **Step 4: Uruchom testy — upewnij się że PASS**

```bash
docker compose run --rm web pytest apps/api/tests/test_trigger.py -v
```

Oczekiwane: `13 passed`

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/api/views.py services/web/apps/api/tests/test_trigger.py
git commit -m "feat: implement POST /api/transfers/trigger/flow/<id>/ endpoint"
```

---

## Task 6: `job_status` endpoint

**Files:**
- Modify: `services/web/apps/api/views.py`
- Create: `services/web/apps/api/tests/test_status.py`

- [ ] **Step 1: Napisz failing testy**

Utwórz `services/web/apps/api/tests/test_status.py`:

```python
import pytest
from django.urls import reverse
from apps.transfers.models import TransferJob, STATUS_DONE, STATUS_FAILED, STATUS_PENDING


@pytest.mark.django_db
class TestJobStatusEndpoint:
    def _url(self, job_id):
        return reverse('api:job_status', args=[job_id])

    def _get(self, client, job_id, raw_key):
        return client.get(
            self._url(job_id),
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )

    def test_returns_200_with_job_fields(
        self, client, regular_user, make_connection, make_api_token
    ):
        conn = make_connection(regular_user)
        job = TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert data['job_id'] == job.pk
        assert data['status'] == STATUS_PENDING
        assert data['started_at'] is None
        assert data['finished_at'] is None
        assert data['error'] is None

    def test_returns_done_status_with_timestamps(
        self, client, regular_user, make_connection, make_api_token
    ):
        from django.utils import timezone
        conn = make_connection(regular_user)
        now = timezone.now()
        job = TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y',
            status=STATUS_DONE,
            started_at=now,
            finished_at=now,
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == STATUS_DONE
        assert data['started_at'] is not None
        assert data['finished_at'] is not None

    def test_returns_failed_status_with_error(
        self, client, regular_user, make_connection, make_api_token
    ):
        conn = make_connection(regular_user)
        job = TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y',
            status=STATUS_FAILED,
            error_message='Connection refused',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, job.pk, raw_key)
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == STATUS_FAILED
        assert data['error'] == 'Connection refused'

    def test_other_users_job_returns_404(
        self, client, regular_user, admin_user, make_connection, make_api_token
    ):
        other_conn = make_connection(admin_user)
        other_job = TransferJob.objects.create(
            owner=admin_user, connection=other_conn,
            source_path='/x', destination_path='/y',
        )
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, other_job.pk, raw_key)
        assert response.status_code == 404

    def test_nonexistent_job_returns_404(
        self, client, regular_user, make_api_token
    ):
        _, raw_key = make_api_token(regular_user)
        response = self._get(client, 99999, raw_key)
        assert response.status_code == 404

    def test_no_token_returns_403(self, client, regular_user, make_connection):
        conn = make_connection(regular_user)
        job = TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y',
        )
        response = client.get(self._url(job.pk))
        assert response.status_code == 403
```

- [ ] **Step 2: Uruchom testy — upewnij się że FAIL**

```bash
docker compose run --rm web pytest apps/api/tests/test_status.py -v
```

Oczekiwane: `501 Not Implemented` powoduje failure

- [ ] **Step 3: Zaimplementuj `job_status` w `apps/api/views.py`**

Zamień stub `job_status` na:

```python
@require_api_token
def job_status(request, job_id):
    try:
        job = TransferJob.objects.get(pk=job_id, owner=request.api_user)
    except TransferJob.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    return JsonResponse({
        'job_id': job.pk,
        'status': job.status,
        'started_at': job.started_at.isoformat() if job.started_at else None,
        'finished_at': job.finished_at.isoformat() if job.finished_at else None,
        'error': job.error_message,
    })
```

- [ ] **Step 4: Uruchom wszystkie testy API — upewnij się że PASS**

```bash
docker compose run --rm web pytest apps/api/tests/ -v
```

Oczekiwane: `~19 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/api/views.py services/web/apps/api/tests/test_status.py
git commit -m "feat: implement GET /api/jobs/<id>/status/ endpoint"
```

---

## Task 7: UI generowania tokenów

**Files:**
- Modify: `services/web/apps/accounts/views.py`
- Modify: `services/web/apps/accounts/urls.py`
- Modify: `services/web/templates/accounts/profile.html`
- Create: `services/web/apps/accounts/tests/test_api_tokens.py`

- [ ] **Step 1: Napisz failing testy generowania**

Utwórz `services/web/apps/accounts/tests/test_api_tokens.py`:

```python
import pytest
from django.urls import reverse
from apps.api.models import ApiToken, MAX_TOKENS_PER_USER


@pytest.mark.django_db
class TestGenerateApiToken:
    def test_generate_creates_token_and_stores_key_in_session(self, auth_client, regular_user):
        url = reverse('accounts:generate_api_token')
        response = auth_client.post(url, {'label': 'CI Jenkins'})
        assert response.status_code == 302
        assert ApiToken.objects.filter(user=regular_user, label='CI Jenkins').exists()
        assert 'new_api_token' in auth_client.session

    def test_raw_key_shown_in_session_is_64_chars(self, auth_client, regular_user):
        url = reverse('accounts:generate_api_token')
        auth_client.post(url, {'label': 'CI Jenkins'})
        raw_key = auth_client.session['new_api_token']
        assert len(raw_key) == 64

    def test_session_key_matches_stored_hash(self, auth_client, regular_user):
        import hashlib
        url = reverse('accounts:generate_api_token')
        auth_client.post(url, {'label': 'CI Jenkins'})
        raw_key = auth_client.session['new_api_token']
        token = ApiToken.objects.get(user=regular_user)
        assert token.key_hash == hashlib.sha256(raw_key.encode()).hexdigest()

    def test_empty_label_redirects_with_error_no_token_created(self, auth_client, regular_user):
        url = reverse('accounts:generate_api_token')
        response = auth_client.post(url, {'label': ''})
        assert response.status_code == 302
        assert not ApiToken.objects.filter(user=regular_user).exists()

    def test_limit_5_tokens_blocks_generation(self, auth_client, regular_user):
        for i in range(MAX_TOKENS_PER_USER):
            ApiToken.generate(regular_user, f'Token {i}')
        url = reverse('accounts:generate_api_token')
        response = auth_client.post(url, {'label': 'Extra'})
        assert response.status_code == 302
        assert ApiToken.objects.filter(user=regular_user).count() == MAX_TOKENS_PER_USER

    def test_unauthenticated_redirects_to_login(self, client):
        url = reverse('accounts:generate_api_token')
        response = client.post(url, {'label': 'Test'})
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_profile_shows_token_modal_with_key(self, auth_client, regular_user):
        gen_url = reverse('accounts:generate_api_token')
        auth_client.post(gen_url, {'label': 'CI Jenkins'})
        profile_url = reverse('accounts:profile')
        response = auth_client.get(profile_url)
        assert response.status_code == 200
        assert b'NOWY TOKEN API' in response.content

    def test_profile_modal_consumed_on_second_visit(self, auth_client, regular_user):
        gen_url = reverse('accounts:generate_api_token')
        auth_client.post(gen_url, {'label': 'CI Jenkins'})
        profile_url = reverse('accounts:profile')
        auth_client.get(profile_url)  # konsumuje sesję
        response = auth_client.get(profile_url)  # drugi visit — modal nie powinien być
        assert b'NOWY TOKEN API' not in response.content
```

- [ ] **Step 2: Uruchom testy — upewnij się że FAIL**

```bash
docker compose run --rm web pytest apps/accounts/tests/test_api_tokens.py::TestGenerateApiToken -v
```

Oczekiwane: `NoReverseMatch: 'generate_api_token' is not a registered namespace`

- [ ] **Step 3: Dodaj widok `generate_api_token` do `apps/accounts/views.py`**

Na początku pliku dodaj import:
```python
from apps.api.models import ApiToken, MAX_TOKENS_PER_USER
```

Na końcu pliku dopisz:

```python
@login_required
@require_POST
def generate_api_token(request):
    if request.user.api_tokens.count() >= MAX_TOKENS_PER_USER:
        messages.error(request, f'Limit {MAX_TOKENS_PER_USER} tokenów osiągnięty. Usuń token aby dodać nowy.')
        return redirect('accounts:profile')
    label = request.POST.get('label', '').strip()[:100]
    if not label:
        messages.error(request, 'Etykieta tokenu jest wymagana.')
        return redirect('accounts:profile')
    _, raw_key = ApiToken.generate(request.user, label)
    request.session['new_api_token'] = raw_key
    messages.success(request, 'Token wygenerowany. Zapisz go — nie zostanie pokazany ponownie.')
    return redirect('accounts:profile')
```

- [ ] **Step 4: Zarejestruj URL w `apps/accounts/urls.py`**

```python
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.users_list, name='users'),
    path('profile/', views.profile_view, name='profile'),
    path('test-webhook/', views.test_webhook, name='test_webhook'),
    path('api-tokens/generate/', views.generate_api_token, name='generate_api_token'),    # ← dodaj
]
```

- [ ] **Step 5: Zaktualizuj `profile_view` żeby przekazywał tokeny i new_token do kontekstu**

Zastąp funkcję `profile_view` (zachowaj istniejące importsz na górze):

```python
@login_required
def profile_view(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Ustawienia zapisane.')
            return redirect('accounts:profile')
    else:
        form = ProfileForm(instance=request.user)
    new_token = request.session.pop('new_api_token', None)
    api_tokens = request.user.api_tokens.all()
    return render(request, 'accounts/profile.html', {
        'form': form,
        'api_tokens': api_tokens,
        'new_token': new_token,
    })
```

- [ ] **Step 6: Dodaj sekcję API TOKENS do `templates/accounts/profile.html`**

> **Uwaga:** Revoke buttons zostaną dodane w Task 8 (po zarejestrowaniu URL `revoke_api_token`). Ten krok dodaje sekcję bez kolumny revoke.

Przed zamykającym `</div>` panelu (przed `{% endblock %}`) dopisz:

```html
  <div class="panel-section" id="api-tokens-section">
    <div class="panel-subheader">[ API TOKENS ]</div>

    {% if api_tokens %}
    <table style="width:100%; border-collapse:collapse; margin-bottom:1rem;">
      <thead>
        <tr>
          <th style="text-align:left; padding:4px 8px; border-bottom:1px solid var(--fg);">ETYKIETA</th>
          <th style="text-align:left; padding:4px 8px; border-bottom:1px solid var(--fg);">UTWORZONY</th>
          <th style="text-align:left; padding:4px 8px; border-bottom:1px solid var(--fg);">OSTATNIO UŻYWANY</th>
        </tr>
      </thead>
      <tbody>
        {% for token in api_tokens %}
        <tr>
          <td style="padding:4px 8px;">{{ token.label }}</td>
          <td style="padding:4px 8px;">{{ token.created_at|date:"Y-m-d H:i" }}</td>
          <td style="padding:4px 8px;">{{ token.last_used_at|date:"Y-m-d H:i"|default:"—" }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="warn">&gt; BRAK TOKENÓW API</div>
    {% endif %}

    {% if api_tokens.count < 5 %}
    <form method="post" action="{% url 'accounts:generate_api_token' %}">
      {% csrf_token %}
      <div class="field-row">
        <label class="label" for="api-token-label">ETYKIETA:</label>
        <input type="text" id="api-token-label" name="label" class="crt-input"
               maxlength="100" placeholder="np. CI Jenkins" required>
        <button type="submit" class="btn">[ GENERATE NEW TOKEN ]</button>
      </div>
    </form>
    {% else %}
    <div class="warn">&gt; LIMIT 5 TOKENÓW OSIĄGNIĘTY — USUŃ TOKEN ABY DODAĆ NOWY</div>
    {% endif %}
  </div>

  {% if new_token %}
  <div id="token-modal" style="
      position:fixed; top:0; left:0; width:100%; height:100%;
      background:rgba(0,0,0,0.85); z-index:1000;
      display:flex; align-items:center; justify-content:center;">
    <div class="panel" style="max-width:600px; width:90%;">
      <div class="panel-header">[ NOWY TOKEN API ]</div>
      <div class="panel-section">
        <div class="warn" style="margin-bottom:1rem;">
          &gt; ZAPISZ TEN KLUCZ — NIE ZOSTANIE POKAZANY PONOWNIE
        </div>
        <div class="field-row" style="word-break:break-all;">
          <code id="new-token-value" style="font-family:inherit; letter-spacing:0.05em;">{{ new_token }}</code>
        </div>
        <div class="field-row" style="margin-top:0.5rem;">
          <button type="button" class="btn btn-sm" onclick="copyNewToken()">[ COPY ]</button>
        </div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn" onclick="document.getElementById('token-modal').style.display='none'">[ ZAMKNIJ ]</button>
      </div>
    </div>
  </div>
  <script>
  function copyNewToken() {
    navigator.clipboard.writeText('{{ new_token|escapejs }}');
  }
  </script>
  {% endif %}
```

- [ ] **Step 7: Uruchom testy — upewnij się że PASS**

```bash
docker compose run --rm web pytest apps/accounts/tests/test_api_tokens.py::TestGenerateApiToken -v
```

Oczekiwane: `8 passed`

- [ ] **Step 8: Commit**

```bash
git add services/web/apps/accounts/views.py services/web/apps/accounts/urls.py \
        services/web/templates/accounts/profile.html \
        services/web/apps/accounts/tests/test_api_tokens.py
git commit -m "feat: add API token generation UI in profile page"
```

---

## Task 8: UI revoke tokenu

**Files:**
- Modify: `services/web/apps/accounts/views.py`
- Modify: `services/web/apps/accounts/urls.py`
- Modify: `services/web/apps/accounts/tests/test_api_tokens.py`

- [ ] **Step 1: Napisz failing testy revoke**

Dopisz do `services/web/apps/accounts/tests/test_api_tokens.py`:

```python
@pytest.mark.django_db
class TestRevokeApiToken:
    def test_revoke_deletes_own_token(self, auth_client, regular_user, make_api_token):
        token, _ = make_api_token(regular_user)
        url = reverse('accounts:revoke_api_token', args=[token.pk])
        response = auth_client.post(url)
        assert response.status_code == 302
        assert not ApiToken.objects.filter(pk=token.pk).exists()

    def test_revoke_redirects_to_profile(self, auth_client, regular_user, make_api_token):
        token, _ = make_api_token(regular_user)
        url = reverse('accounts:revoke_api_token', args=[token.pk])
        response = auth_client.post(url)
        assert response.status_code == 302
        assert '/profile/' in response['Location']

    def test_cannot_revoke_other_users_token(self, auth_client, regular_user, admin_user, make_api_token):
        other_token, _ = make_api_token(admin_user)
        url = reverse('accounts:revoke_api_token', args=[other_token.pk])
        response = auth_client.post(url)
        assert response.status_code == 404
        assert ApiToken.objects.filter(pk=other_token.pk).exists()

    def test_unauthenticated_redirects_to_login(self, client, regular_user, make_api_token):
        token, _ = make_api_token(regular_user)
        url = reverse('accounts:revoke_api_token', args=[token.pk])
        response = client.post(url)
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_after_revoke_token_no_longer_authenticates_api(
        self, client, regular_user, make_api_token, make_connection, mocker
    ):
        mocker.patch('apps.api.views.execute_transfer.delay')
        token, raw_key = make_api_token(regular_user)
        revoke_url = reverse('accounts:revoke_api_token', args=[token.pk])

        auth_client_local = client
        auth_client_local.force_login(regular_user)
        auth_client_local.post(revoke_url)

        conn = make_connection(regular_user)
        import json
        response = client.post(
            reverse('api:trigger_connection', args=[conn.pk]),
            data=json.dumps({'source_path': '/x', 'destination_path': '/y'}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {raw_key}',
        )
        assert response.status_code == 403
```

- [ ] **Step 2: Uruchom testy — upewnij się że FAIL**

```bash
docker compose run --rm web pytest apps/accounts/tests/test_api_tokens.py::TestRevokeApiToken -v
```

Oczekiwane: `NoReverseMatch: 'revoke_api_token' is not a registered namespace`

- [ ] **Step 3: Dodaj widok `revoke_api_token` do `apps/accounts/views.py`**

Dopisz na końcu pliku:

```python
@login_required
@require_POST
def revoke_api_token(request, token_id):
    get_object_or_404(ApiToken, pk=token_id, user=request.user).delete()
    messages.success(request, 'Token usunięty.')
    return redirect('accounts:profile')
```

Dodaj `get_object_or_404` do importu na górze (jest już w pliku z poprzednich widoków? sprawdź — jeśli nie, dodaj):
```python
from django.shortcuts import render, redirect, get_object_or_404
```

- [ ] **Step 4: Zarejestruj URL w `apps/accounts/urls.py`**

```python
urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.users_list, name='users'),
    path('profile/', views.profile_view, name='profile'),
    path('test-webhook/', views.test_webhook, name='test_webhook'),
    path('api-tokens/generate/', views.generate_api_token, name='generate_api_token'),
    path('api-tokens/<int:token_id>/revoke/', views.revoke_api_token, name='revoke_api_token'),  # ← dodaj
]
```

- [ ] **Step 5: Dodaj kolumnę REVOKE do tabeli w `templates/accounts/profile.html`**

Zamień nagłówek tabeli — dodaj kolumnę akcji:

```html
      <thead>
        <tr>
          <th style="text-align:left; padding:4px 8px; border-bottom:1px solid var(--fg);">ETYKIETA</th>
          <th style="text-align:left; padding:4px 8px; border-bottom:1px solid var(--fg);">UTWORZONY</th>
          <th style="text-align:left; padding:4px 8px; border-bottom:1px solid var(--fg);">OSTATNIO UŻYWANY</th>
          <th style="padding:4px 8px; border-bottom:1px solid var(--fg);"></th>
        </tr>
      </thead>
```

Zamień wiersze tabeli — dodaj kolumnę z formularzem revoke:

```html
        {% for token in api_tokens %}
        <tr>
          <td style="padding:4px 8px;">{{ token.label }}</td>
          <td style="padding:4px 8px;">{{ token.created_at|date:"Y-m-d H:i" }}</td>
          <td style="padding:4px 8px;">{{ token.last_used_at|date:"Y-m-d H:i"|default:"—" }}</td>
          <td style="padding:4px 8px;">
            <form method="post" action="{% url 'accounts:revoke_api_token' token.pk %}" style="display:inline;">
              {% csrf_token %}
              <button type="submit" class="btn btn-sm"
                      onclick="return confirm('Usuń token {{ token.label|escapejs }}?')">[ REVOKE ]</button>
            </form>
          </td>
        </tr>
        {% endfor %}
```

- [ ] **Step 6: Uruchom wszystkie testy accounts**

```bash
docker compose run --rm web pytest apps/accounts/tests/ -v
```

Oczekiwane: wszystkie passing

- [ ] **Step 7: Uruchom całą suite testów**

```bash
docker compose run --rm web pytest -v
```

Oczekiwane: wszystkie passing — brak regresji w istniejących testach

- [ ] **Step 8: Commit**

```bash
git add services/web/apps/accounts/views.py services/web/apps/accounts/urls.py \
        services/web/templates/accounts/profile.html \
        services/web/apps/accounts/tests/test_api_tokens.py
git commit -m "feat: add API token revoke UI — token management complete"
```

---

## Weryfikacja końcowa

- [ ] **Smoke test ręczny**: uruchom aplikację i w panelu `Profile → [ API TOKENS ]` wygeneruj token, skopiuj raw key

- [ ] **Test z curl**:
```bash
# Trigger connection
curl -s -X POST http://localhost/api/transfers/trigger/connection/<id>/ \
  -H "Authorization: Token <raw_key>" \
  -H "Content-Type: application/json" \
  -d '{"source_path":"/tmp/test.txt","destination_path":"/backup/"}' | jq

# Status
curl -s http://localhost/api/jobs/<job_id>/status/ \
  -H "Authorization: Token <raw_key>" | jq
```

- [ ] **Revoke i sprawdź**: usuń token, ten sam curl → `{"error": "Invalid or missing token"}`

- [ ] **Commit dokumentacji** (aktualizacja Obsidian — opcjonalnie):
```bash
git add .
git commit -m "docs: update project notes for REST API feature"
```
