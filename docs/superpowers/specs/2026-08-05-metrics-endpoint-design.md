# Endpoint /metrics (Prometheus) — Design Spec

> Propozycja #28 z `Propozycje rozbudowy.md`. Cel: udostępnić metryki transferów (sukces/fail per moduł, czas trwania, długość kolejki Celery) w formacie Prometheus, do wpięcia w istniejący stack monitoringu użytkownika (Prometheus/Grafana).

## Zakres

**W zakresie:**
- Nowa appka `apps.monitoring` z jednym widokiem `GET /metrics/`.
- Trzy rodziny metryk: liczniki jobów per (typ, moduł, status), suma+licznik czasu trwania per (typ, moduł), długość kolejki Celery.
- Autoryzacja: statyczny sekret przez nagłówek `Authorization: Bearer <METRICS_TOKEN>`.
- Nowa zależność: `prometheus_client` (generowanie poprawnego formatu ekspozycji, `CollectorRegistry` + customowy `Collector`).

**Poza zakresem:**
- Histogramy z przedziałami czasu trwania — świadomie pominięte (arbitralny dobór bucketów), zamiast tego `_sum`/`_count` (Grafana liczy średnią przez `rate(sum)/rate(count)`).
- Okno czasowe/rolling window dla liczników — odrzucone w brainstormingu, liczniki są cumulative all-time (poprawna semantyka Prometheus Counter).
- Metryki per-user/per-connection (np. rozbicie po `owner` czy nazwie połączenia) — nie żądane w opisie propozycji, YAGNI.
- Zmiana istniejącego systemu `ApiToken`/`require_api_token` — `/metrics` ma świadomie odrębny mechanizm auth (sekret infrastrukturalny, nie per-użytkownik).

## Model danych

Brak nowych modeli/migracji — appka `apps.monitoring` zawiera wyłącznie widok i collector, żadnego stanu w bazie. Wszystkie dane pochodzą z istniejących modeli (`TransferJob`, `DbTransferJob`) i z Redis (długość kolejki), odpytywanych na żywo przy każdym scrape.

**Założenie zweryfikowane w kodzie**: `cleanup_old_transfers` (`services/worker/tasks.py:261-276`) usuwa wyłącznie pliki z dysku (`os.unlink`), nigdy nie kasuje wierszy `TransferJob`/`DbTransferJob` z bazy — więc `COUNT(*) GROUP BY status` jest naprawdę monotonicznie rosnący w czasie, poprawna semantyka Prometheus Counter.

## Metryki

### 1. `tmask_transfer_jobs_total{type, module, status}` — Counter

`COUNT(*) GROUP BY status`, dwa źródła połączone w jedną rodzinę metryk:

- **`type="file"`** (z `TransferJob`, `services/web/apps/transfers/models.py`):
  - `module` = `connection.protocol` (`'sftp'`/`'rsync'`, z `Connection.PROTOCOL_CHOICES`) gdy `connection_id` jest ustawione,
  - `module="relay"` (stała) gdy `flow_id` jest ustawione zamiast `connection_id` (transfer przez `Flow` — relay SFTP→SFTP, `services/web/apps/flows/models.py`).
- **`type="db"`** (z `DbTransferJob`, `services/web/apps/db_transfers/models.py`): `module` = pole `engine` (`'postgres'`/`'mysql'`/`'mssql'`).
- `status` = wartość z `STATUS_CHOICES` obu modeli (identyczne wartości w obu: `pending`/`running`/`done`/`failed`/`cancelled`, `services/web/apps/transfers/models.py:5-16` i `services/web/apps/db_transfers/models.py:5-16`).

### 2. `tmask_transfer_duration_seconds_sum{type, module}` + `tmask_transfer_duration_seconds_count{type, module}` — Summary (bez kwantyli)

Suma i liczba `(finished_at - started_at).total_seconds()` dla jobów z oboma polami nie-`NULL` (niezależnie od końcowego statusu — `done`/`failed`/`cancelled` mogą mieć realny czas trwania; `pending`/`running` są wykluczone przez sam warunek `finished_at IS NOT NULL`). Te same reguły `type`/`module` co metryka #1.

### 3. `tmask_celery_queue_length{queue="celery"}` — Gauge

`redis.Redis.from_url(settings.CELERY_BROKER_URL).llen('celery')` — jedna, domyślna kolejka Celery (potwierdzone: `services/web/config/celery.py` nie definiuje `task_routes`/`task_default_queue`, więc wszystkie taski trafiają do kolejki `celery`).

## Architektura

**Nowa appka `apps.monitoring`** (wzorem małych, jednoodpowiedzialnych appek jak `apps.webhook_deliveries`):

```
services/web/apps/monitoring/
├── __init__.py
├── apps.py          # AppConfig, name='apps.monitoring', label='monitoring'
├── auth.py          # require_metrics_token — dekorator porównujący Bearer token
├── collectors.py     # TmaskCollector(prometheus_client.registry.Collector)
├── views.py          # metrics_view — GET /metrics/, wywołuje generate_latest()
├── urls.py
└── tests/
    ├── __init__.py
    ├── test_auth.py
    └── test_collectors.py
```

Rejestracja: `INSTALLED_APPS` w `services/web/config/settings/base.py` (po `apps.webhook_deliveries`), `path('metrics/', include('apps.monitoring.urls'))` w `services/web/config/urls.py` (poza prefiksem `api/`, żeby nie sugerować że obowiązuje ten sam mechanizm auth co REST API).

**`collectors.py`** — klasa `TmaskCollector` implementująca protokół `prometheus_client`: metoda `collect()` zwraca generator `CounterMetricFamily`/`GaugeMetricFamily` zbudowany z zapytań `TransferJob.objects.values('status', 'connection__protocol', 'flow_id').annotate(count=Count('id'))` (i analogicznie dla `DbTransferJob` po `engine`) oraz sumy/liczby czasu trwania przez `Sum`/`Count` z adnotacją `duration=ExpressionWrapper(F('finished_at') - F('started_at'), output_field=DurationField())`, plus jedno zapytanie do Redis dla długości kolejki. **Świeże zapytanie przy każdym wywołaniu `collect()`** — nie ma żadnego stanu trzymanego w pamięci procesu między requestami (kluczowe przy wielu procesach gunicorn: każdy scrape od Prometheusa może trafić do innego procesu roboczego, więc licznik w pamięci byłby niespójny; zapytanie do bazy przy każdym scrape eliminuje ten problem).

**`views.py`** — `metrics_view(request)`: tworzy lokalny `CollectorRegistry()`, rejestruje w nim instancję `TmaskCollector()`, zwraca `HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)`. Rejestr lokalny per-request (nie globalny moduł-level singleton) — upraszcza testy (brak globalnego stanu do resetowania między testami) i unika przypadkowej rejestracji collectora więcej niż raz.

**`auth.py`** — `require_metrics_token(view_func)`: czyta `request.headers.get('Authorization', '')`, sprawdza prefiks `'Bearer '`, porównuje resztę stringa z `settings.METRICS_TOKEN` przez `secrets.compare_digest` (stała czasowo, przeciw timing attack — różnica od istniejącego `require_api_token`, który porównuje hashe SHA-256 przez `ApiToken.objects.get()`, tu nie ma ORM lookupu bo sekret jest jeden, statyczny). Brak/zły token → `HttpResponse(status=401)` z nagłówkiem `WWW-Authenticate: Bearer` (zgodnie z RFC 6750, tak Prometheus i standardowe narzędzia rozpoznają że to błąd auth, nie inny błąd).

**Konfiguracja**: nowa zmienna `METRICS_TOKEN` w `.env`/`.env.example` (bez wartości domyślnej — `config('METRICS_TOKEN')`, wymagana jawnie, tak jak `SECRET_KEY`/`FIELD_ENCRYPTION_KEY` — brak fallbacku chroni przed przypadkowym wdrożeniem z pustym/przewidywalnym sekretem), odczytana w `services/web/config/settings/base.py` obok pozostałych `config(...)`.

**Zależność**: `prometheus_client` dopisana do `services/web/requirements-prod.txt` (czysty Python, brak zależności binarnych, `requirements-dev.txt` dziedziczy przez `-r requirements-prod.txt`).

## Testowanie

- `test_auth.py`: brak nagłówka → 401; zły token → 401; poprawny token → przepuszcza do widoku (dekorator wywołuje owinięty view_func).
- `test_collectors.py`: buduje `TransferJob`/`DbTransferJob` o różnych `status`/`protocol`/`engine`/`flow`, weryfikuje że `list(TmaskCollector().collect())` zawiera oczekiwane próbki (nazwa metryki, etykiety, wartość) — w tym: job przez `Flow` → `module="relay"`; job z `finished_at=None` pominięty w `duration_seconds_sum/count`, ale wliczony w `jobs_total`. Etykiety (`type`/`module`/`status`) dla `jobs_total` pojawiają się wyłącznie dla kombinacji faktycznie obecnych w danych (standardowa praktyka Prometheusa — brak serii = brak zdarzeń, nie trzeba sztucznie emitować zer dla całego kombinatorycznego iloczynu etykiet). Wyjątek: `tmask_celery_queue_length` jest emitowany zawsze (jedno zapytanie do Redis niezależne od stanu bazy), więc test pustej bazy sprawdza że ta jedna metryka nadal jest obecna nawet gdy `jobs_total`/`duration_seconds_*` nie mają żadnych próbek.
- Test integracyjny widoku: `GET /metrics/` bez tokenu → 401; z poprawnym tokenem → 200, `Content-Type` zawiera `text/plain`, treść zawiera nazwy trzech rodzin metryk (`tmask_transfer_jobs_total`, `tmask_transfer_duration_seconds_sum`, `tmask_celery_queue_length`) — Redis w testach mockowany (`unittest.mock.patch` na `redis.Redis.from_url`), żeby nie wymagać żywego Redis w testach jednostkowych `web-test`.

## Global Constraints

- Liczniki jobów: cumulative all-time, `COUNT(*) GROUP BY status` z bazy przy każdym scrape (nie okno czasowe, nie stan w pamięci procesu).
- Bez histogramów czasu trwania — wyłącznie `_sum`/`_count` (Summary bez kwantyli).
- Autoryzacja: `Authorization: Bearer <METRICS_TOKEN>`, porównanie stałoczasowe (`secrets.compare_digest`), brak/zły token → `401` z `WWW-Authenticate: Bearer`.
- `METRICS_TOKEN` bez wartości domyślnej w `config()` — wymagana jawna konfiguracja przed startem aplikacji.
- Nazwa kolejki Celery: `'celery'` (jedyna, domyślna — brak custom routingu w projekcie).
- Nowa appka `apps.monitoring` wpięta pod `path('metrics/', ...)` w `config/urls.py`, poza prefiksem `api/`.
- Zależność `prometheus_client` w `services/web/requirements-prod.txt`.
