# Endpoint /metrics (Prometheus) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Udostępnić `GET /metrics/` w formacie Prometheus (liczniki jobów per typ/moduł/status, czas trwania, długość kolejki Celery), chroniony statycznym tokenem Bearer.

**Architecture:** Nowa appka `apps.monitoring` — customowy `prometheus_client` Collector odpytujący `TransferJob`/`DbTransferJob`/Redis na żywo przy każdym scrape (bez stanu w pamięci procesu, bo gunicorn ma wiele workerów), opakowany widokiem chronionym dekoratorem porównującym `Authorization: Bearer <token>` ze stałą `METRICS_TOKEN`.

**Tech Stack:** Django 5.x, `prometheus_client` (nowa zależność), `redis` (już w projekcie), pytest + pytest-django.

## Global Constraints

- Liczniki jobów: cumulative all-time, `COUNT(*) GROUP BY status` z bazy przy każdym scrape — nie okno czasowe, nie stan w pamięci procesu.
- Bez histogramów czasu trwania — wyłącznie `_sum`/`_count` (Prometheus Summary bez kwantyli), przez `SummaryMetricFamily.add_metric(labels, count, sum)`.
- Autoryzacja: `Authorization: Bearer <METRICS_TOKEN>`, porównanie stałoczasowe (`secrets.compare_digest`), brak/zły token → `401` z nagłówkiem `WWW-Authenticate: Bearer`.
- `METRICS_TOKEN` bez wartości domyślnej w `config()` — wymagana jawna konfiguracja. **Krytyczne dla tego planu**: `config('METRICS_TOKEN')` bez defaultu oznacza, że jeśli zmienna nie istnieje w `.env` używanym przez testy, **całe Django settings.py rzuci `UndefinedValueError` przy starcie i KAŻDY test w całej apce web przestanie działać** (nie tylko testy tej funkcji). Task 1 Step 1 dodaje tę zmienną do `.env` PRZED jakąkolwiek zmianą `settings.py`.
- Nazwa kolejki Celery: `'celery'` (jedyna, domyślna).
- Nowa appka `apps.monitoring` wpięta pod `path('metrics/', include('apps.monitoring.urls'))` w `config/urls.py`, poza prefiksem `api/`.
- Zależność `prometheus_client` w `services/web/requirements-prod.txt` (bez górnego ograniczenia wersji — biblioteka czysto pythonowa, stabilne API).
- Etykiety `jobs_total` pojawiają się wyłącznie dla kombinacji faktycznie obecnych w danych (standardowa praktyka Prometheusa) — wyjątek: `tmask_celery_queue_length` jest emitowany zawsze, niezależnie od stanu bazy.

---

## Task 1: Scaffolding appki + autoryzacja tokenem

**Files:**
- Modify: `services/web/requirements-prod.txt`
- Modify: `services/web/config/settings/base.py`
- Modify: `.env` (worktree, gitignored — NIE commitować)
- Modify: `.env.example`
- Create: `services/web/apps/monitoring/__init__.py`
- Create: `services/web/apps/monitoring/apps.py`
- Create: `services/web/apps/monitoring/auth.py`
- Create: `services/web/apps/monitoring/tests/__init__.py`
- Test: `services/web/apps/monitoring/tests/test_auth.py`

**Interfaces:**
- Produces: `require_metrics_token(view_func)` dekorator w `apps.monitoring.auth` — Task 2 owija nim `metrics_view`. Zachowanie: brak nagłówka `Authorization` lub zły prefiks → `HttpResponse(status=401, headers={'WWW-Authenticate': 'Bearer'})`; zły token → to samo; poprawny token → wywołuje `view_func(request, *args, **kwargs)` i zwraca jego wynik.
- Produces: `settings.METRICS_TOKEN` (string, bez defaultu) — Task 2 go nie czyta bezpośrednio (czyta go tylko `auth.py`), ale musi istnieć żeby jakikolwiek test w apce web działał.

- [ ] **Step 1: Dodaj `METRICS_TOKEN` do `.env` i `.env.example` (PRZED dotknięciem `settings.py`)**

W pliku `.env` w katalogu roboczym (worktree root — gitignored, nie commitować) dopisz na końcu:

```
METRICS_TOKEN=dev-metrics-token-change-me
```

W `.env.example` (commitowany) dopisz na końcu nową sekcję:

```
# Metryki Prometheus — GET /metrics/ (Authorization: Bearer <token>)
METRICS_TOKEN=generuj: python -c "import secrets; print(secrets.token_urlsafe(32))"
```

To musi się zdarzyć zanim `config('METRICS_TOKEN')` trafi do `settings.py` w Step 5 — inaczej `docker compose build`/`run` dla `web-test` przestanie działać dla WSZYSTKICH testów w apce web, nie tylko tej funkcji.

- [ ] **Step 2: Dodaj zależność**

W `services/web/requirements-prod.txt` dopisz na końcu nową linię:

```
prometheus_client
```

(bez pinowania wersji — czysto pythonowa biblioteka, stabilne API; `requirements-dev.txt` dziedziczy przez `-r requirements-prod.txt`, nie trzeba go dotykać).

- [ ] **Step 3: Utwórz szkielet appki**

`services/web/apps/monitoring/__init__.py` (pusty plik).

`services/web/apps/monitoring/apps.py`:

```python
from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.monitoring'
    label = 'monitoring'
```

`services/web/apps/monitoring/tests/__init__.py` (pusty plik).

- [ ] **Step 4: Napisz failing testy dla dekoratora auth**

`services/web/apps/monitoring/tests/test_auth.py`:

```python
from django.http import HttpResponse
from django.test import RequestFactory


def test_missing_header_returns_401(settings):
    from apps.monitoring.auth import require_metrics_token

    settings.METRICS_TOKEN = 'correct-token'

    @require_metrics_token
    def dummy_view(request):
        return HttpResponse('ok')

    request = RequestFactory().get('/metrics/')
    response = dummy_view(request)
    assert response.status_code == 401
    assert response['WWW-Authenticate'] == 'Bearer'


def test_wrong_prefix_returns_401(settings):
    from apps.monitoring.auth import require_metrics_token

    settings.METRICS_TOKEN = 'correct-token'

    @require_metrics_token
    def dummy_view(request):
        return HttpResponse('ok')

    request = RequestFactory().get('/metrics/', HTTP_AUTHORIZATION='Token correct-token')
    response = dummy_view(request)
    assert response.status_code == 401


def test_wrong_token_returns_401(settings):
    from apps.monitoring.auth import require_metrics_token

    settings.METRICS_TOKEN = 'correct-token'

    @require_metrics_token
    def dummy_view(request):
        return HttpResponse('ok')

    request = RequestFactory().get('/metrics/', HTTP_AUTHORIZATION='Bearer wrong-token')
    response = dummy_view(request)
    assert response.status_code == 401


def test_correct_token_calls_view(settings):
    from apps.monitoring.auth import require_metrics_token

    settings.METRICS_TOKEN = 'correct-token'

    @require_metrics_token
    def dummy_view(request):
        return HttpResponse('ok')

    request = RequestFactory().get('/metrics/', HTTP_AUTHORIZATION='Bearer correct-token')
    response = dummy_view(request)
    assert response.status_code == 200
    assert response.content == b'ok'


def test_empty_metrics_token_never_matches(settings):
    from apps.monitoring.auth import require_metrics_token

    settings.METRICS_TOKEN = ''

    @require_metrics_token
    def dummy_view(request):
        return HttpResponse('ok')

    request = RequestFactory().get('/metrics/', HTTP_AUTHORIZATION='Bearer ')
    response = dummy_view(request)
    assert response.status_code == 401
```

(Ostatni test pilnuje brzegowego przypadku: jeśli `METRICS_TOKEN` byłoby kiedyś puste, pusty podany token NIE powinien się "dopasować" — `secrets.compare_digest('', '')` zwraca `True`, więc dekorator musi jawnie odrzucać puste `settings.METRICS_TOKEN`, nie polegać wyłącznie na `compare_digest`.)

- [ ] **Step 5: Uruchom testy, potwierdź failure**

Run: `docker compose build web-test && docker compose --profile test run --rm web-test python -m pytest apps/monitoring/ -q`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'apps.monitoring.auth'`.

- [ ] **Step 6: Zarejestruj appkę i dodaj setting**

W `services/web/config/settings/base.py` dodaj `'apps.monitoring',` do `INSTALLED_APPS`, zaraz po `'apps.webhook_deliveries',`:

```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_celery_beat',
    'django_celery_results',
    'django_htmx',
    'apps.accounts',
    'apps.connections',
    'apps.transfers',
    'apps.scheduler',
    'apps.flows',
    'apps.api',
    'apps.dashboard',
    'apps.organization',
    'apps.db_transfers',
    'apps.masking',
    'apps.audit_log',
    'apps.webhook_deliveries',
    'apps.monitoring',
]
```

Dodaj `METRICS_TOKEN = config('METRICS_TOKEN')` zaraz po istniejącej linii `TRANSFERS_RETENTION_DAYS = config('TRANSFERS_RETENTION_DAYS', default=1, cast=int)`:

```python
TRANSFERS_RETENTION_DAYS = config('TRANSFERS_RETENTION_DAYS', default=1, cast=int)
METRICS_TOKEN = config('METRICS_TOKEN')
```

- [ ] **Step 7: Zaimplementuj dekorator**

`services/web/apps/monitoring/auth.py`:

```python
import secrets
from functools import wraps
from django.conf import settings
from django.http import HttpResponse


def require_metrics_token(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        expected = settings.METRICS_TOKEN
        header = request.headers.get('Authorization', '')
        if not expected or not header.startswith('Bearer '):
            return HttpResponse(status=401, headers={'WWW-Authenticate': 'Bearer'})
        provided = header[len('Bearer '):]
        if not secrets.compare_digest(provided, expected):
            return HttpResponse(status=401, headers={'WWW-Authenticate': 'Bearer'})
        return view_func(request, *args, **kwargs)
    return wrapper
```

- [ ] **Step 8: Uruchom testy, potwierdź pass**

Run: `docker compose build web-test && docker compose --profile test run --rm web-test python -m pytest apps/monitoring/ -q`
Expected: `PASS`, 5 passed.

- [ ] **Step 9: Uruchom pełen zestaw testów web, potwierdź brak regresji od dodania `METRICS_TOKEN`**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/ -q`
Expected: `PASS`, 0 failed (potwierdza że `config('METRICS_TOKEN')` bez defaultu nie wysadziło reszty apki — bo `.env` zostało zaktualizowane w Step 1).

- [ ] **Step 10: Commit**

```bash
git add services/web/requirements-prod.txt services/web/config/settings/base.py .env.example \
        services/web/apps/monitoring/__init__.py services/web/apps/monitoring/apps.py \
        services/web/apps/monitoring/auth.py services/web/apps/monitoring/tests/__init__.py \
        services/web/apps/monitoring/tests/test_auth.py
git commit -m "feat(monitoring): scaffold apps.monitoring + Bearer token auth for /metrics"
```

(Nie dodawaj `.env` do commita — jest gitignored i zawiera tylko lokalną wartość deweloperską.)

---

## Task 2: Collector metryk + widok + urls

**Files:**
- Create: `services/web/apps/monitoring/collectors.py`
- Create: `services/web/apps/monitoring/views.py`
- Create: `services/web/apps/monitoring/urls.py`
- Modify: `services/web/config/urls.py`
- Test: `services/web/apps/monitoring/tests/test_collectors.py`
- Test: `services/web/apps/monitoring/tests/test_views.py`

**Interfaces:**
- Consumes: `require_metrics_token` z `apps.monitoring.auth` (Task 1), `settings.METRICS_TOKEN` (Task 1).
- Consumes: `apps.transfers.models.TransferJob` (pola: `status`, `connection` FK nullable, `flow_id` nullable, `started_at`, `finished_at`), `apps.db_transfers.models.DbTransferJob` (pola: `status`, `engine`, `started_at`, `finished_at`), `apps.connections.models.Connection.protocol`.
- Produces: `TmaskCollector` (klasa w `apps.monitoring.collectors`, metoda `collect(self)` zwracająca generator obiektów `prometheus_client` metric family) i `metrics_view` (w `apps.monitoring.views`) — oba używane wyłącznie wewnątrz tej appki, nic w innych taskach ich nie konsumuje (to ostatni task planu).

- [ ] **Step 1: Napisz failing testy dla collectora**

`services/web/apps/monitoring/tests/test_collectors.py`:

```python
from datetime import timedelta
from unittest.mock import patch, MagicMock

import pytest
from django.utils import timezone

from apps.transfers.models import TransferJob
from apps.db_transfers.models import DbTransferJob
from apps.monitoring.collectors import TmaskCollector


def _sample_by_name(samples, name):
    return [s for s in samples if s.name == name]


@pytest.mark.django_db
class TestJobsTotal:
    def test_counts_file_job_by_connection_protocol(self, regular_user, make_connection):
        conn = make_connection(regular_user, protocol='sftp')
        TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y', status='done',
        )
        families = {f.name: f for f in TmaskCollector().collect()}
        samples = _sample_by_name(families['tmask_transfer_jobs'].samples, 'tmask_transfer_jobs_total')
        matching = [s for s in samples if s.labels == {'type': 'file', 'module': 'sftp', 'status': 'done'}]
        assert len(matching) == 1
        assert matching[0].value == 1

    def test_counts_flow_job_as_relay_module(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        TransferJob.objects.create(
            owner=regular_user, flow=flow,
            source_path='/x', destination_path='/y', status='failed',
        )
        families = {f.name: f for f in TmaskCollector().collect()}
        samples = families['tmask_transfer_jobs'].samples
        matching = [s for s in samples if s.labels == {'type': 'file', 'module': 'relay', 'status': 'failed'}]
        assert len(matching) == 1
        assert matching[0].value == 1

    def test_counts_db_job_by_engine(self, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='a', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='b', name='dst')
        DbTransferJob.objects.create(
            owner=regular_user, source_connection=src, dest_connection=dst,
            engine='postgres', status='running',
        )
        families = {f.name: f for f in TmaskCollector().collect()}
        samples = families['tmask_transfer_jobs'].samples
        matching = [s for s in samples if s.labels == {'type': 'db', 'module': 'postgres', 'status': 'running'}]
        assert len(matching) == 1
        assert matching[0].value == 1

    def test_no_samples_for_empty_database(self, regular_user):
        families = {f.name: f for f in TmaskCollector().collect()}
        assert families['tmask_transfer_jobs'].samples == []


@pytest.mark.django_db
class TestDurationSeconds:
    def test_sums_duration_for_finished_file_job(self, regular_user, make_connection):
        conn = make_connection(regular_user, protocol='rsync')
        started = timezone.now() - timedelta(seconds=30)
        finished = timezone.now()
        TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y', status='done',
            started_at=started, finished_at=finished,
        )
        families = {f.name: f for f in TmaskCollector().collect()}
        samples = families['tmask_transfer_duration_seconds'].samples
        sum_sample = [s for s in samples if s.name == 'tmask_transfer_duration_seconds_sum'
                      and s.labels == {'type': 'file', 'module': 'rsync'}]
        count_sample = [s for s in samples if s.name == 'tmask_transfer_duration_seconds_count'
                        and s.labels == {'type': 'file', 'module': 'rsync'}]
        assert len(sum_sample) == 1
        assert len(count_sample) == 1
        assert 29.0 <= sum_sample[0].value <= 31.0
        assert count_sample[0].value == 1

    def test_excludes_job_without_finished_at(self, regular_user, make_connection):
        conn = make_connection(regular_user, protocol='sftp')
        TransferJob.objects.create(
            owner=regular_user, connection=conn,
            source_path='/x', destination_path='/y', status='running',
            started_at=timezone.now(), finished_at=None,
        )
        families = {f.name: f for f in TmaskCollector().collect()}
        assert families['tmask_transfer_duration_seconds'].samples == []
        jobs_samples = families['tmask_transfer_jobs'].samples
        assert len(jobs_samples) == 1  # still counted in jobs_total


@pytest.mark.django_db
class TestQueueLength:
    def test_reads_llen_from_redis(self, regular_user):
        with patch('apps.monitoring.collectors.redis.Redis') as MockRedis:
            MockRedis.from_url.return_value.llen.return_value = 7
            families = {f.name: f for f in TmaskCollector().collect()}
        samples = families['tmask_celery_queue_length'].samples
        matching = [s for s in samples if s.labels == {'queue': 'celery'}]
        assert len(matching) == 1
        assert matching[0].value == 7

    def test_present_even_with_empty_database(self, regular_user):
        with patch('apps.monitoring.collectors.redis.Redis') as MockRedis:
            MockRedis.from_url.return_value.llen.return_value = 0
            families = {f.name: f for f in TmaskCollector().collect()}
        assert families['tmask_transfer_jobs'].samples == []
        assert len(families['tmask_celery_queue_length'].samples) == 1
```

- [ ] **Step 2: Uruchom testy, potwierdź failure**

Run: `docker compose build web-test && docker compose --profile test run --rm web-test python -m pytest apps/monitoring/tests/test_collectors.py -q`
Expected: `FAIL` — `ModuleNotFoundError: No module named 'apps.monitoring.collectors'`.

- [ ] **Step 3: Zaimplementuj collector**

`services/web/apps/monitoring/collectors.py`:

```python
import redis
from django.conf import settings
from django.db.models import Count, Sum, Case, When, Value, F, CharField, ExpressionWrapper, DurationField

from apps.transfers.models import TransferJob
from apps.db_transfers.models import DbTransferJob
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, SummaryMetricFamily

_FILE_MODULE_EXPR = Case(
    When(flow_id__isnull=False, then=Value('relay')),
    default=F('connection__protocol'),
    output_field=CharField(),
)

_DURATION_EXPR = ExpressionWrapper(
    F('finished_at') - F('started_at'), output_field=DurationField()
)


class TmaskCollector:
    def collect(self):
        yield self._jobs_total()
        yield self._duration_seconds()
        yield self._queue_length()

    def _jobs_total(self):
        counter = CounterMetricFamily(
            'tmask_transfer_jobs_total',
            'Total number of transfer jobs by type, module and status.',
            labels=['type', 'module', 'status'],
        )

        file_rows = (
            TransferJob.objects
            .annotate(module=_FILE_MODULE_EXPR)
            .values('module', 'status')
            .annotate(count=Count('id'))
        )
        for row in file_rows:
            counter.add_metric(['file', row['module'], row['status']], row['count'])

        db_rows = (
            DbTransferJob.objects
            .values('engine', 'status')
            .annotate(count=Count('id'))
        )
        for row in db_rows:
            counter.add_metric(['db', row['engine'], row['status']], row['count'])

        return counter

    def _duration_seconds(self):
        summary = SummaryMetricFamily(
            'tmask_transfer_duration_seconds',
            'Duration of finished transfer jobs in seconds, by type and module.',
            labels=['type', 'module'],
        )

        file_rows = (
            TransferJob.objects
            .filter(started_at__isnull=False, finished_at__isnull=False)
            .annotate(module=_FILE_MODULE_EXPR, duration=_DURATION_EXPR)
            .values('module')
            .annotate(total=Sum('duration'), cnt=Count('id'))
        )
        for row in file_rows:
            total_seconds = row['total'].total_seconds() if row['total'] else 0.0
            summary.add_metric(['file', row['module']], row['cnt'], total_seconds)

        db_rows = (
            DbTransferJob.objects
            .filter(started_at__isnull=False, finished_at__isnull=False)
            .annotate(duration=_DURATION_EXPR)
            .values('engine')
            .annotate(total=Sum('duration'), cnt=Count('id'))
        )
        for row in db_rows:
            total_seconds = row['total'].total_seconds() if row['total'] else 0.0
            summary.add_metric(['db', row['engine']], row['cnt'], total_seconds)

        return summary

    def _queue_length(self):
        gauge = GaugeMetricFamily(
            'tmask_celery_queue_length',
            'Number of tasks waiting in the Celery queue.',
            labels=['queue'],
        )
        client = redis.Redis.from_url(settings.CELERY_BROKER_URL)
        gauge.add_metric(['celery'], client.llen('celery'))
        return gauge
```

- [ ] **Step 4: Uruchom testy collectora, potwierdź pass**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/monitoring/tests/test_collectors.py -q`
Expected: `PASS`, 9 passed.

- [ ] **Step 5: Napisz failing test widoku**

`services/web/apps/monitoring/tests/test_views.py`:

```python
from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestMetricsView:
    def test_requires_bearer_token(self, client):
        response = client.get(reverse('monitoring:metrics'))
        assert response.status_code == 401

    def test_rejects_wrong_token(self, client, settings):
        settings.METRICS_TOKEN = 'correct-token'
        response = client.get(reverse('monitoring:metrics'), HTTP_AUTHORIZATION='Bearer wrong-token')
        assert response.status_code == 401

    def test_returns_prometheus_text_with_correct_token(self, client, settings):
        settings.METRICS_TOKEN = 'correct-token'
        with patch('apps.monitoring.collectors.redis.Redis') as MockRedis:
            MockRedis.from_url.return_value.llen.return_value = 0
            response = client.get(reverse('monitoring:metrics'), HTTP_AUTHORIZATION='Bearer correct-token')
        assert response.status_code == 200
        assert response['Content-Type'].startswith('text/plain')
        body = response.content.decode()
        assert 'tmask_transfer_jobs_total' in body
        assert 'tmask_transfer_duration_seconds' in body
        assert 'tmask_celery_queue_length' in body
```

- [ ] **Step 6: Uruchom test widoku, potwierdź failure**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/monitoring/tests/test_views.py -q`
Expected: `FAIL` — `django.urls.exceptions.NoReverseMatch` (URL `monitoring:metrics` jeszcze nie istnieje).

- [ ] **Step 7: Zaimplementuj widok i urls**

`services/web/apps/monitoring/views.py`:

```python
from django.http import HttpResponse
from prometheus_client import CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST

from .auth import require_metrics_token
from .collectors import TmaskCollector


@require_metrics_token
def metrics_view(request):
    registry = CollectorRegistry()
    registry.register(TmaskCollector())
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
```

`services/web/apps/monitoring/urls.py`:

```python
from django.urls import path
from . import views

app_name = 'monitoring'

urlpatterns = [
    path('', views.metrics_view, name='metrics'),
]
```

W `services/web/config/urls.py` dodaj `path('metrics/', include('apps.monitoring.urls')),` zaraz po `path('webhook-deliveries/', include('apps.webhook_deliveries.urls')),`, przed końcowym `path('', RedirectView.as_view(...))`:

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
    path('db-transfers/', include('apps.db_transfers.urls')),
    path('masking/', include('apps.masking.urls')),
    path('scheduler/', include('apps.scheduler.urls')),
    path('api/', include('apps.api.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('organization/', include('apps.organization.urls')),
    path('audit-log/', include('apps.audit_log.urls')),
    path('webhook-deliveries/', include('apps.webhook_deliveries.urls')),
    path('metrics/', include('apps.monitoring.urls')),
    path('', RedirectView.as_view(url='/transfers/', permanent=False)),
]
```

- [ ] **Step 8: Uruchom testy widoku, potwierdź pass**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/monitoring/ -q`
Expected: `PASS`, 15 passed (5 z Task 1 + 9 collector + 3 widok — łącznie 17; jeśli liczba się nie zgadza, przelicz z sum testów napisanych w obu taskach, nie traktuj konkretnej liczby jako twardego wymogu).

- [ ] **Step 9: Uruchom pełen zestaw testów web**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/ -q`
Expected: `PASS`, 0 failed.

- [ ] **Step 10: Commit**

```bash
git add services/web/apps/monitoring/collectors.py services/web/apps/monitoring/views.py \
        services/web/apps/monitoring/urls.py services/web/config/urls.py \
        services/web/apps/monitoring/tests/test_collectors.py services/web/apps/monitoring/tests/test_views.py
git commit -m "feat(monitoring): add Prometheus collector + /metrics view"
```

---

## Po zakończeniu wszystkich tasków

Uruchom pełen zestaw testów obu serwisów (worker nie jest dotknięty tym planem, ale weryfikacja braku regresji jest tania):

Run: `docker compose --profile test run --rm web-test python -m pytest apps/ -q`
Run: `docker compose run --rm worker python -m pytest tests/ -q`

Expected: oba `PASS`, 0 failed. Worker: bez zmian liczby testów względem stanu przed tym planem (ta funkcja dotyczy wyłącznie `services/web`).

Ręczna weryfikacja end-to-end (opcjonalna, poza automatycznymi testami): `curl -H "Authorization: Bearer $METRICS_TOKEN" http://localhost/metrics/` na uruchomionym stacku powinno zwrócić tekst w formacie Prometheus.
