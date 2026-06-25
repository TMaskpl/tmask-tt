# Dashboard z wykresami — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać widok `/dashboard/` z trzema wykresami (transfery/dzień, success rate, top źródła) liczonymi z `TransferJob` dla zalogowanego użytkownika w oknie 30 dni.

**Architecture:** Nowy app `apps/dashboard/` z czystymi funkcjami agregującymi w `stats.py`, cienkim widokiem `@login_required`, i frontendem opartym o self-hostowany Chart.js zasilany przez Django `json_script` (CSP-safe). Brak nowych modeli i migracji.

**Tech Stack:** Python 3.12, Django 5.x, Chart.js 4 (self-hosted), pytest. Kod uruchamiany w kontenerze Docker `web`.

## Global Constraints

- Testy i migracje w kontenerze: `docker compose exec -T web python -m pytest apps/dashboard/ -q`. Stack musi działać (`docker compose up -d`).
- Web NIE ma bind-mountu — po zmianie kodu rebuild: `docker compose build web && docker compose up -d web` PRZED uruchomieniem testów.
- Polecenia z katalogu `/Users/dniemczok/Desktop/TMaskPL/tmask-tt`.
- Izolacja per-user: agregaty wyłącznie z `TransferJob.objects.filter(owner=request.user, ...)`.
- CSP projektu: `script-src 'self'` — żadnego CDN ani inline JS. Chart.js self-hostowany w `static/js/`; dane przez `{{ data|json_script:"dashboard-data" }}`.
- Okno czasowe: stałe 30 dni. Top źródła: limit 7, Connection + Flow razem (etykieta flow `"RELAY: <name>"`).
- TDD: czerwony test przed implementacją. Commity: prefiks `feat:`/`test:`, opis po polsku, stopka `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Praca na gałęzi `feat/dashboard` (utworzona, spec zacommitowany).
- Ścieżki: templates → `services/web/templates/`, static → `services/web/static/`, app → `services/web/apps/dashboard/`.

---

### Task 1: App scaffold + funkcje agregujące `stats.py`

**Files:**
- Create: `services/web/apps/dashboard/__init__.py` (pusty)
- Create: `services/web/apps/dashboard/stats.py`
- Create: `services/web/apps/dashboard/tests/__init__.py` (pusty)
- Create: `services/web/apps/dashboard/tests/test_stats.py`
- Modify: `services/web/config/settings/base.py` (dodanie `'apps.dashboard'` do `INSTALLED_APPS`)

**Interfaces:**
- Consumes: `TransferJob`, stałe `STATUS_DONE`, `STATUS_FAILED` z `apps.transfers.models`; fixtures `regular_user`, `make_connection`, `make_flow`.
- Produces:
  - `transfers_per_day(jobs, days=30) -> dict` → `{"labels": [str×days], "done": [int×days], "failed": [int×days]}`
  - `success_rate(jobs) -> dict` → `{"done": int, "failed": int, "other": int, "total": int, "rate_pct": float}`
  - `top_sources(jobs, limit=7) -> dict` → `{"labels": [str], "counts": [int]}`

- [ ] **Step 1: Zarejestruj app w INSTALLED_APPS**

W `services/web/config/settings/base.py` dodaj po linii `'apps.api',` (linia 25):

```python
    'apps.dashboard',
```

- [ ] **Step 2: Utwórz puste pliki pakietu**

```bash
mkdir -p services/web/apps/dashboard/tests
touch services/web/apps/dashboard/__init__.py services/web/apps/dashboard/tests/__init__.py
```

- [ ] **Step 3: Napisz czerwone testy `test_stats.py`**

Utwórz `services/web/apps/dashboard/tests/test_stats.py`:

```python
import pytest
from datetime import timedelta
from django.utils import timezone

from apps.transfers.models import (
    TransferJob, STATUS_DONE, STATUS_FAILED, STATUS_PENDING,
)
from apps.dashboard import stats


def _make_job(user, connection=None, flow=None, status=STATUS_DONE, days_ago=0):
    job = TransferJob.objects.create(
        owner=user, connection=connection, flow=flow,
        source_path='/s', destination_path='/d', status=status,
    )
    # created_at ma auto_now_add=True — nadpisanie przez update() omija je
    when = timezone.now() - timedelta(days=days_ago)
    TransferJob.objects.filter(pk=job.pk).update(created_at=when)
    return job


@pytest.mark.django_db
class TestTransfersPerDay:
    def test_counts_done_and_failed_per_day(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        _make_job(regular_user, conn, status=STATUS_DONE, days_ago=0)
        _make_job(regular_user, conn, status=STATUS_DONE, days_ago=0)
        _make_job(regular_user, conn, status=STATUS_FAILED, days_ago=0)
        _make_job(regular_user, conn, status=STATUS_DONE, days_ago=1)
        result = stats.transfers_per_day(TransferJob.objects.filter(owner=regular_user))
        assert len(result['labels']) == 30
        assert result['done'][-1] == 2   # dziś
        assert result['failed'][-1] == 1
        assert result['done'][-2] == 1   # wczoraj

    def test_fills_gaps_with_zero(self, regular_user):
        result = stats.transfers_per_day(TransferJob.objects.filter(owner=regular_user))
        assert len(result['labels']) == 30
        assert result['done'] == [0] * 30
        assert result['failed'] == [0] * 30

    def test_excludes_jobs_older_than_window(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        _make_job(regular_user, conn, status=STATUS_DONE, days_ago=40)
        result = stats.transfers_per_day(TransferJob.objects.filter(owner=regular_user))
        assert sum(result['done']) == 0


@pytest.mark.django_db
class TestSuccessRate:
    def test_rate_excludes_pending_running(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        for _ in range(8):
            _make_job(regular_user, conn, status=STATUS_DONE)
        for _ in range(2):
            _make_job(regular_user, conn, status=STATUS_FAILED)
        for _ in range(5):
            _make_job(regular_user, conn, status=STATUS_PENDING)
        result = stats.success_rate(TransferJob.objects.filter(owner=regular_user))
        assert result['done'] == 8
        assert result['failed'] == 2
        assert result['other'] == 5
        assert result['total'] == 15
        assert result['rate_pct'] == 80.0

    def test_zero_jobs_rate_is_zero(self, regular_user):
        result = stats.success_rate(TransferJob.objects.filter(owner=regular_user))
        assert result['total'] == 0
        assert result['rate_pct'] == 0.0


@pytest.mark.django_db
class TestTopSources:
    def test_combines_connections_and_flows(self, regular_user, make_connection, make_flow):
        conn = make_connection(regular_user, name='Backup-SFTP')
        flow = make_flow(regular_user, name='Nightly')
        _make_job(regular_user, connection=conn)
        _make_job(regular_user, connection=conn)
        _make_job(regular_user, flow=flow)
        result = stats.top_sources(TransferJob.objects.filter(owner=regular_user))
        assert result['labels'][0] == 'Backup-SFTP'
        assert result['counts'][0] == 2
        assert 'RELAY: Nightly' in result['labels']

    def test_orders_desc_and_respects_limit(self, regular_user, make_connection):
        for i in range(9):
            conn = make_connection(regular_user, name=f'C{i}', host=f'10.0.0.{i}')
            for _ in range(i + 1):
                _make_job(regular_user, connection=conn)
        result = stats.top_sources(TransferJob.objects.filter(owner=regular_user), limit=7)
        assert len(result['labels']) == 7
        assert result['labels'][0] == 'C8'      # najwięcej jobów
        assert result['counts'] == sorted(result['counts'], reverse=True)
```

- [ ] **Step 4: Uruchom testy — sprawdź że padają**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/dashboard/tests/test_stats.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.dashboard.stats'`

- [ ] **Step 5: Zaimplementuj `stats.py`**

Utwórz `services/web/apps/dashboard/stats.py`:

```python
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.transfers.models import STATUS_DONE, STATUS_FAILED


def transfers_per_day(jobs, days=30):
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    rows = (
        jobs.filter(created_at__date__gte=start)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(
            done=Count('id', filter=Q(status=STATUS_DONE)),
            failed=Count('id', filter=Q(status=STATUS_FAILED)),
        )
    )
    by_day = {r['day']: r for r in rows}
    labels, done, failed = [], [], []
    for i in range(days):
        d = start + timedelta(days=i)
        labels.append(d.strftime('%m-%d'))
        row = by_day.get(d)
        done.append(row['done'] if row else 0)
        failed.append(row['failed'] if row else 0)
    return {"labels": labels, "done": done, "failed": failed}


def success_rate(jobs):
    total = jobs.count()
    done = jobs.filter(status=STATUS_DONE).count()
    failed = jobs.filter(status=STATUS_FAILED).count()
    other = total - done - failed
    denom = done + failed
    rate = round(done / denom * 100, 1) if denom else 0.0
    return {"done": done, "failed": failed, "other": other, "total": total, "rate_pct": rate}


def top_sources(jobs, limit=7):
    counts = {}
    for r in jobs.filter(connection__isnull=False).values('connection__name').annotate(c=Count('id')):
        name = r['connection__name']
        counts[name] = counts.get(name, 0) + r['c']
    for r in jobs.filter(flow__isnull=False).values('flow__name').annotate(c=Count('id')):
        label = f"RELAY: {r['flow__name']}"
        counts[label] = counts.get(label, 0) + r['c']
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return {"labels": [k for k, _ in ranked], "counts": [v for _, v in ranked]}
```

- [ ] **Step 6: Uruchom testy — zielone**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/dashboard/tests/test_stats.py -q`
Expected: PASS — 7 testów

- [ ] **Step 7: Commit**

```bash
git add services/web/apps/dashboard/__init__.py services/web/apps/dashboard/stats.py services/web/apps/dashboard/tests/__init__.py services/web/apps/dashboard/tests/test_stats.py services/web/config/settings/base.py
git commit -m "$(cat <<'EOF'
feat: app dashboard + funkcje agregujące stats.py

transfers_per_day / success_rate / top_sources liczone z TransferJob,
okno 30 dni, top łączy Connection + Flow.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Widok `/dashboard/` + URL + template (struktura)

**Files:**
- Create: `services/web/apps/dashboard/views.py`
- Create: `services/web/apps/dashboard/urls.py`
- Modify: `services/web/config/urls.py`
- Create: `services/web/templates/dashboard/index.html`
- Create: `services/web/apps/dashboard/tests/test_views.py`

**Interfaces:**
- Consumes: `transfers_per_day`, `success_rate`, `top_sources` z Task 1; `TransferJob`; fixtures `auth_client`, `regular_user`, `admin_user`, `make_connection`.
- Produces: URL `dashboard:index` → `/dashboard/`; widok renderuje `dashboard/index.html` z kontekstem `{"data": {...}}` zawierającym klucze `per_day`/`success`/`top`; HTML zawiera `<script id="dashboard-data" type="application/json">`.

- [ ] **Step 1: Napisz czerwone testy `test_views.py`**

Utwórz `services/web/apps/dashboard/tests/test_views.py`:

```python
import json
import pytest
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone

from apps.transfers.models import TransferJob, STATUS_DONE


def _make_job(user, connection, status=STATUS_DONE, days_ago=0):
    job = TransferJob.objects.create(
        owner=user, connection=connection,
        source_path='/s', destination_path='/d', status=status,
    )
    TransferJob.objects.filter(pk=job.pk).update(
        created_at=timezone.now() - timedelta(days=days_ago)
    )
    return job


@pytest.mark.django_db
class TestDashboardView:
    def test_requires_login(self, client):
        response = client.get(reverse('dashboard:index'))
        assert response.status_code == 302
        assert '/accounts/login' in response.url

    def test_renders_200_with_data(self, auth_client, regular_user, make_connection):
        _make_job(regular_user, make_connection(regular_user))
        response = auth_client.get(reverse('dashboard:index'))
        assert response.status_code == 200
        data = response.context['data']
        assert set(data.keys()) == {'per_day', 'success', 'top'}

    def test_per_user_isolation(self, auth_client, regular_user, admin_user, make_connection):
        # job innego użytkownika nie może wpływać na agregaty regular_user
        _make_job(admin_user, make_connection(admin_user, name='AdminConn'))
        response = auth_client.get(reverse('dashboard:index'))
        assert response.context['data']['success']['total'] == 0

    def test_json_script_present(self, auth_client, regular_user, make_connection):
        _make_job(regular_user, make_connection(regular_user))
        response = auth_client.get(reverse('dashboard:index'))
        html = response.content.decode()
        assert 'id="dashboard-data"' in html
        assert 'type="application/json"' in html
        # zawartość json_script musi być poprawnym JSON
        start = html.index('id="dashboard-data"')
        snippet = html[start:start + 2000]
        assert '"per_day"' in snippet and '"success"' in snippet
```

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/dashboard/tests/test_views.py -q`
Expected: FAIL — `django.urls.exceptions.NoReverseMatch: 'dashboard' is not a registered namespace`

- [ ] **Step 3: Utwórz widok**

Utwórz `services/web/apps/dashboard/views.py`:

```python
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from apps.transfers.models import TransferJob
from . import stats


@login_required
def dashboard(request):
    since = timezone.now() - timedelta(days=30)
    jobs = TransferJob.objects.filter(owner=request.user, created_at__gte=since)
    data = {
        "per_day": stats.transfers_per_day(jobs),
        "success": stats.success_rate(jobs),
        "top": stats.top_sources(jobs),
    }
    return render(request, "dashboard/index.html", {"data": data})
```

- [ ] **Step 4: Utwórz urls.py appa**

Utwórz `services/web/apps/dashboard/urls.py`:

```python
from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard, name='index'),
]
```

- [ ] **Step 5: Podłącz w config/urls.py**

W `services/web/config/urls.py` dodaj w `urlpatterns` przed wpisem `RedirectView` (ostatnia linia):

```python
    path('dashboard/', include('apps.dashboard.urls')),
```

- [ ] **Step 6: Utwórz template (struktura, bez skryptów)**

Utwórz `services/web/templates/dashboard/index.html`:

```html
{% extends 'base.html' %}
{% load static %}
{% block title %}DASHBOARD — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="box">
  <div class="box-title">[ DASHBOARD ] — ostatnie 30 dni</div>
  {{ data|json_script:"dashboard-data" }}
  <div id="dashboard-empty" style="display:none;color:var(--green);opacity:0.6;padding:1rem;">BRAK DANYCH — wykonaj pierwszy transfer</div>
  <div style="display:grid;grid-template-columns:2fr 1fr;gap:1rem;margin-top:1rem;">
    <div><canvas id="chart-per-day"></canvas></div>
    <div><canvas id="chart-success"></canvas></div>
  </div>
  <div style="margin-top:1rem;"><canvas id="chart-top"></canvas></div>
</div>
{% endblock %}
```

- [ ] **Step 7: Uruchom testy — zielone**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/dashboard/tests/test_views.py -q`
Expected: PASS — 4 testy

- [ ] **Step 8: Commit**

```bash
git add services/web/apps/dashboard/views.py services/web/apps/dashboard/urls.py services/web/config/urls.py services/web/templates/dashboard/index.html services/web/apps/dashboard/tests/test_views.py
git commit -m "$(cat <<'EOF'
feat: widok /dashboard/ + template z json_script

Cienki widok per-user liczący 3 agregaty, dane osadzone CSP-safe.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Frontend — Chart.js self-host, dashboard.js, nav (weryfikacja manualna)

**Files:**
- Create: `services/web/static/js/chart.min.js` (pobrany Chart.js 4 UMD)
- Create: `services/web/static/js/dashboard.js`
- Modify: `services/web/templates/base.html` (blok `{% block scripts %}` przed `</body>` + link `DASHBOARD` w nav)
- Modify: `services/web/templates/dashboard/index.html` (wypełnienie `{% block scripts %}`)

**Interfaces:**
- Consumes: `<script id="dashboard-data">` (Task 2) z kluczami `per_day`/`success`/`top`; canvasy `chart-per-day`/`chart-success`/`chart-top`; `#dashboard-empty`.
- Produces: renderowane 3 wykresy lub empty state; link nawigacyjny do dashboardu.

> Ten task nie ma testów jednostkowych (brak runnera JS) — kończy się weryfikacją manualną w przeglądarce. Pełny zestaw `pytest` musi pozostać zielony (brak regresji w renderze).

- [ ] **Step 1: Pobierz self-hostowany Chart.js**

```bash
curl -L -o services/web/static/js/chart.min.js https://cdn.jsdelivr.net/npm/chart.js@4.4.6/dist/chart.umd.min.js
```

Weryfikacja: plik istnieje i jest niepusty (>100 KB), zawiera string `Chart`:
```bash
ls -la services/web/static/js/chart.min.js && grep -c "Chart" services/web/static/js/chart.min.js | head -1
```
Expected: rozmiar ~200 KB, grep zwraca liczbę > 0.

- [ ] **Step 2: Utwórz `dashboard.js`**

Utwórz `services/web/static/js/dashboard.js`:

```javascript
(function () {
  const el = document.getElementById('dashboard-data');
  if (!el) return;
  const data = JSON.parse(el.textContent);

  const GREEN = '#33ff33', RED = '#ff3333', OTHER = '#557755';
  const GRID = 'rgba(51,255,51,0.12)', TICK = '#8fdf8f';

  if (!data.success || data.success.total === 0) {
    const empty = document.getElementById('dashboard-empty');
    if (empty) empty.style.display = 'block';
    return;
  }

  Chart.defaults.color = TICK;
  Chart.defaults.font.family = 'monospace';

  new Chart(document.getElementById('chart-per-day'), {
    type: 'bar',
    data: {
      labels: data.per_day.labels,
      datasets: [
        { label: 'DONE', data: data.per_day.done, backgroundColor: GREEN },
        { label: 'FAILED', data: data.per_day.failed, backgroundColor: RED },
      ],
    },
    options: {
      responsive: true,
      scales: {
        x: { stacked: true, grid: { color: GRID } },
        y: { stacked: true, beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } },
      },
    },
  });

  new Chart(document.getElementById('chart-success'), {
    type: 'doughnut',
    data: {
      labels: ['DONE', 'FAILED', 'OTHER'],
      datasets: [{
        data: [data.success.done, data.success.failed, data.success.other],
        backgroundColor: [GREEN, RED, OTHER],
      }],
    },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: 'SUCCESS RATE: ' + data.success.rate_pct + '%' } },
    },
  });

  new Chart(document.getElementById('chart-top'), {
    type: 'bar',
    data: {
      labels: data.top.labels,
      datasets: [{ label: 'JOBS', data: data.top.counts, backgroundColor: GREEN }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      scales: {
        x: { beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } },
        y: { grid: { color: GRID } },
      },
    },
  });
})();
```

- [ ] **Step 3: Dodaj blok `scripts` i link nav w base.html**

W `services/web/templates/base.html` dodaj link w nav po linii LOGS (`<a href="{% url 'transfers:logs' %}">LOGS</a>`):

```html
    <a href="{% url 'dashboard:index' %}" class="{% if request.resolver_match.app_name == 'dashboard' %}active{% endif %}">DASHBOARD</a>
```

Oraz dodaj blok skryptów bezpośrednio przed `</body>`:

```html
  {% block scripts %}{% endblock %}
</body>
```

- [ ] **Step 4: Wypełnij blok scripts w dashboard/index.html**

W `services/web/templates/dashboard/index.html` dodaj na końcu (po `{% endblock %}` zamykającym `content`):

```html
{% block scripts %}
<script src="{% static 'js/chart.min.js' %}"></script>
<script src="{% static 'js/dashboard.js' %}"></script>
{% endblock %}
```

- [ ] **Step 5: Rebuild + pełny zestaw web (brak regresji renderu)**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/ -q`
Expected: PASS — wszystkie testy web (w tym dashboard) zielone

- [ ] **Step 6: Weryfikacja manualna w przeglądarce**

1. Otwórz `http://localhost/dashboard/` (zaloguj się jeśli trzeba).
2. Sprawdź: link `DASHBOARD` widoczny w nav i podświetlony jako `active`.
3. Przy istniejących transferach: renderują się 3 wykresy (słupkowy stacked done/failed, doughnut z success rate w tytule, poziomy top źródła).
4. Sprawdź konsolę przeglądarki — brak błędów CSP (`Refused to load/execute script`) i brak błędów JS.
5. Empty state: dla konta bez transferów w oknie 30 dni widoczny napis „BRAK DANYCH — wykonaj pierwszy transfer", brak pustych wykresów.

- [ ] **Step 7: Commit**

```bash
git add services/web/static/js/chart.min.js services/web/static/js/dashboard.js services/web/templates/base.html services/web/templates/dashboard/index.html
git commit -m "$(cat <<'EOF'
feat: frontend dashboardu — Chart.js self-host + 3 wykresy + nav

Chart.js 4 self-hostowany (CSP), dashboard.js renderuje wykresy z json_script,
empty state, link DASHBOARD w nawigacji.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Po wdrożeniu (poza planem TDD)

- Aktualizacja dokumentacji w vault: `Projekt-tmask-transporter.md` (nowa funkcja Dashboard), `Propozycje rozbudowy.md` (pozycja #9 dashboard → zrealizowane), wpis do `LOG.md`.
- `git push` obu repozytoriów (kod → GitHub, vault → Gitea) po akceptacji.
