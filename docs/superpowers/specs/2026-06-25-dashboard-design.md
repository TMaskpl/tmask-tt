# Design: Dashboard z wykresami transferów

**Data:** 2026-06-25
**Status:** Zatwierdzony (brainstorming)

## Kontekst i cel

tmask-transporter gromadzi historię transferów w modelu `TransferJob` (status, timestampy, powiązanie z Connection lub Flow), ale nie ma widoku zbiorczego. Dashboard pod `/dashboard/` pokaże trzy metryki dla zalogowanego użytkownika w oknie ostatnich 30 dni: transfery dziennie, success rate, top źródła. Dane już istnieją w `TransferJob` — brakuje tylko warstwy prezentacji.

## Decyzje projektowe

1. **Okno czasowe:** stałe ostatnie 30 dni (bez selektora zakresu — YAGNI).
2. **Izolacja per-user:** wszystkie agregaty z `TransferJob.objects.filter(owner=request.user, created_at__gte=teraz-30dni)` — spójne z resztą aplikacji.
3. **Top źródła:** wspólny ranking Connection + Flow; joby relay etykietowane `"RELAY: <flow.name>"`.
4. **CSP:** projekt ma `script-src 'self'` (bez CDN, bez inline JS) — dlatego HTMX jest self-hostowany. Chart.js również self-hostowany; dane przekazane przez Django `json_script` (`type="application/json"`, CSP-safe), odczytane przez statyczny `dashboard.js`.
5. **Bez nowego endpointu danych** — metryki liczone server-side (ORM) i osadzone w stronie. Prościej i łatwiej testować niż osobne API + fetch.
6. **Nowy app `apps/dashboard/`** — izolacja, własny namespace i testy, brak puchnięcia `transfers/views.py`.

## Komponenty

| Plik | Odpowiedzialność |
|------|------------------|
| `apps/dashboard/__init__.py`, `apps.py` | Rejestracja appa Django |
| `apps/dashboard/stats.py` | Czyste funkcje agregujące `TransferJob` → dict gotowy do wykresu |
| `apps/dashboard/views.py` | `@login_required dashboard` — liczy agregaty dla `request.user`, renderuje |
| `apps/dashboard/urls.py` | `dashboard:index` → `/dashboard/` |
| `templates/dashboard/index.html` | 3× `<canvas>` + `{{ data\|json_script:"dashboard-data" }}` + `<script>` static |
| `static/js/chart.min.js` | Chart.js self-hostowany |
| `static/js/dashboard.js` | Czyta `json_script`, renderuje 3 wykresy, empty state |
| `templates/base.html` | Link `DASHBOARD` w nav |
| `config/settings/base.py` | `apps.dashboard` w `INSTALLED_APPS` |
| `config/urls.py` | include `dashboard.urls` pod `dashboard/` |

## Agregacja i przepływ danych

### `stats.py` — funkcje (stałe statusów z `transfers.models`)

```python
def transfers_per_day(jobs, days=30) -> dict:
    # grupuje po dacie created_at; luki wypełnione zerami dla pełnych 30 dni
    # -> {"labels": ["MM-DD", ...×30], "done": [int×30], "failed": [int×30]}

def success_rate(jobs) -> dict:
    # rate liczony z done/(done+failed) — pending/running poza mianownikiem
    # -> {"done": int, "failed": int, "other": int, "total": int, "rate_pct": float}

def top_sources(jobs, limit=7) -> dict:
    # łączy connection__name i flow__name (etykieta flow: "RELAY: <name>")
    # ranking malejąco po liczbie jobów, top `limit`
    # -> {"labels": [str, ...], "counts": [int, ...]}
```

`top_sources` implementacyjnie: `jobs.filter(connection__isnull=False).values('connection__name').annotate(c=Count('id'))` + analogicznie `flow__name`, scalenie, sort desc, ucięcie do `limit`.

### `views.dashboard`

```python
since = timezone.now() - timedelta(days=30)
jobs = TransferJob.objects.filter(owner=request.user, created_at__gte=since)
data = {
    "per_day": transfers_per_day(jobs),
    "success": success_rate(jobs),
    "top": top_sources(jobs),
}
return render(request, "dashboard/index.html", {"data": data})
```

### Frontend

Template osadza `{{ data|json_script:"dashboard-data" }}`, trzy `<canvas>`, na końcu `<script src="{% static 'js/chart.min.js' %}">` + `<script src="{% static 'js/dashboard.js' %}">`.

`dashboard.js` czyta `JSON.parse(getElementById('dashboard-data').textContent)` i renderuje:
- Wykres 1: `type:'bar'`, stacked DONE/FAILED per dzień
- Wykres 2: `type:'doughnut'` DONE/FAILED/OTHER + `rate_pct` w podpisie
- Wykres 3: `type:'bar', indexAxis:'y'` (poziomy) top źródła

Kolory hardkodowane pod paletę CRT (zieleń fosforowa = done, czerwień = failed, dim = other).

**Empty state:** gdy `success.total == 0` → `dashboard.js` pokazuje „BRAK DANYCH — wykonaj pierwszy transfer" zamiast pustych wykresów.

## Testy (TDD)

### `apps/dashboard/tests/test_stats.py`
- `transfers_per_day`: `test_counts_done_and_failed_per_day`, `test_fills_gaps_with_zero` (zawsze 30 etykiet), `test_excludes_jobs_older_than_window`
- `success_rate`: `test_rate_excludes_pending_running` (done=8, failed=2, pending=5 → rate 80.0, other=5, total=15), `test_zero_jobs_rate_is_zero` (brak dzielenia przez zero)
- `top_sources`: `test_combines_connections_and_flows` (etykieta flow `"RELAY: <name>"`), `test_orders_desc_and_respects_limit`

### `apps/dashboard/tests/test_views.py`
- `test_requires_login` (anonim → redirect login)
- `test_renders_200_with_data` (200, kontekst `data` z kluczami `per_day`/`success`/`top`)
- `test_per_user_isolation` (joby innego użytkownika nie wliczają się — test bezpieczeństwa)
- `test_json_script_present` (render zawiera `id="dashboard-data"` z poprawnym JSON)

### Statyczny JS
Bez testów jednostkowych (brak runnera JS w projekcie) — weryfikacja manualna w przeglądarce po wdrożeniu (3 wykresy + empty state).

### Kolejność TDD
Czerwone testy `stats.py` → implementacja funkcji → czerwone testy widoku → widok + urls + INSTALLED_APPS → template + static JS + nav → weryfikacja manualna.

## Poza zakresem (YAGNI)

- Selektor zakresu (7/30/90 dni) — stałe 30 dni
- Osobny endpoint JSON / fetch — dane osadzone server-side
- Globalny widok admina (wszyscy użytkownicy) — dashboard zawsze per-user
- Testy jednostkowe JS / E2E
- Eksport wykresów, real-time refresh
