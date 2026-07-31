# Read-only REST API statusu transferów — Design

**Propozycja:** #30 z `Propozycje rozbudowy.md` (vault Obsidian).

## Kontekst i korekta zakresu

Wpis #30 zakładał brak `GET /api/transfers/<id>/status`, ale kod (`apps/api/views.py:78`, `job_status`) pokazuje, że pojedynczy status **już istnieje** dla `TransferJob` (plikowe transfery: SFTP/rsync/relay), z pełnym pokryciem testowym (`apps/api/tests/test_status.py`). Realna luka, potwierdzona podczas brainstormingu:

1. Brak endpointu **listy** transferów (wprost wspomniane w opisie #30: „i listy").
2. `DbTransferJob` (#17/#23 — replikacja Postgres/MySQL/MSSQL) to całkowicie osobny model, niewidoczny przez API w ogóle — ani pojedynczy status, ani lista.

## Cel

Dodać do istniejącego `apps.api` (token-based, `ApiToken`, `require_api_token`) dwa brakujące elementy: listę `TransferJob` i pełne pokrycie (status + lista) `DbTransferJob` — z zachowaniem istniejącego kontraktu `job_status` (czysto addytywne rozszerzenie, żaden dotychczasowy klucz JSON nie znika ani nie zmienia znaczenia).

## Endpointy

| Metoda | Ścieżka | Status |
|--------|---------|--------|
| GET | `/api/jobs/<job_id>/status/` | już istnieje, bez zmian kontraktu (rozszerzony o nowe pola, patrz niżej) |
| GET | `/api/jobs/` | **nowy** — lista `TransferJob` |
| GET | `/api/db-jobs/<job_id>/status/` | **nowy** — pojedynczy status `DbTransferJob` |
| GET | `/api/db-jobs/` | **nowy** — lista `DbTransferJob` |

Dwie równoległe rodziny endpointów (nie jeden zunifikowany endpoint) — `TransferJob` i `DbTransferJob` mają różne, nienachodzące na siebie pola (`connection`/`flow` vs `source_connection`/`dest_connection`/`engine`/`table_name`); spłaszczenie do wspólnego kształtu straciłoby informację albo wymusiło zagnieżdżony `details` bez realnej korzyści przy tylko dwóch typach.

Autoryzacja: istniejący `@require_api_token` na wszystkich czterech endpointach, **bez** dodatkowej bramki roli — identycznie jak dzisiejszy `job_status` (dowolny ważny token, niezależnie od roli właściciela, może odczytać dowolny job; potwierdzone testem `test_any_authenticated_token_can_read_job_status_of_another_users_job`). Spójne z resztą aplikacji, gdzie odczyt jest już org-wide (harmonogramy, lista transferów w UI).

## Kształty JSON

### `TransferJob` (rozszerzony `job_status` + nowy `job_list`)

```json
{
  "job_id": 42,
  "status": "done",
  "connection_id": 3,
  "flow_id": null,
  "source_path": "/data/file.tar",
  "destination_path": "/backup/file.tar",
  "created_at": "2026-07-31T10:00:00+00:00",
  "started_at": "2026-07-31T10:00:01+00:00",
  "finished_at": "2026-07-31T10:00:05+00:00",
  "error": null
}
```

Nowe pola względem dzisiejszego `job_status` (`connection_id`, `flow_id`, `source_path`, `destination_path`, `created_at`) — dodane, bo w kontekście listy klient musi móc rozróżnić joby bez N dodatkowych zapytań. Dotychczasowe pola (`job_id`, `status`, `started_at`, `finished_at`, `error`) zachowują nazwę i znaczenie.

`GET /api/jobs/` zwraca:
```json
{"jobs": [ /* obiekty jak wyżej, malejąco po created_at */ ]}
```

### `DbTransferJob` (nowy `db_job_status` + nowy `db_job_list`)

```json
{
  "job_id": 7,
  "status": "running",
  "engine": "postgres",
  "source_connection_id": 1,
  "dest_connection_id": 2,
  "table_name": "users",
  "created_at": "2026-07-31T10:00:00+00:00",
  "started_at": "2026-07-31T10:00:01+00:00",
  "finished_at": null,
  "error": null
}
```

`table_name` pusty (transfer całej bazy) serializowany jako `null`, wzorem już istniejącego `error_message or None` w `job_status` — spójny idiom "puste pole tekstowe → `null` w JSON", nie pusty string.

`GET /api/db-jobs/` zwraca:
```json
{"jobs": [ /* obiekty jak wyżej, malejąco po created_at */ ]}
```

## Filtrowanie i limit

Obie listy przyjmują opcjonalny query param `?status=`, walidowany po `STATUS_CHOICES` (identyczny zestaw wartości w obu modelach: `pending`, `running`, `done`, `failed`, `cancelled`):
- Wartość spoza zbioru → `400 {"error": "Invalid status. Choices: pending, running, done, failed, cancelled"}`.
- Brak parametru → brak filtrowania (wszystkie statusy).

Sortowanie: `created_at` malejąco — już domyślne (`Meta.ordering = ['-created_at']` w obu modelach), żadnego jawnego `.order_by()` potrzebnego.

Limit rozmiaru strony: stała `_LIST_PAGE_SIZE = 200` w `apps/api/views.py`, wzorem istniejącego `_PAGE_SIZE = 200` w `apps/audit_log/views.py` — proste `[:​_LIST_PAGE_SIZE]` po filtrze, bez pełnej paginacji (offset/next-link). Zgodne z małą skalą projektu (jeden serwer, LAN-only — udokumentowany kompromis w `README.md`/CI-CD docs).

## Architektura implementacji

- Wydzielenie dwóch prywatnych funkcji serializujących w `apps/api/views.py`: `_serialize_transfer_job(job) -> dict` i `_serialize_db_transfer_job(job) -> dict`. Istniejący `job_status` przechodzi na `_serialize_transfer_job` (bez zmiany zachowania na zewnątrz, tylko refaktor — usuwa duplikację kształtu JSON między pojedynczym statusem a listą).
- `job_list(request)`: `TransferJob.objects.all()`, opcjonalny `.filter(status=...)` po walidacji, `[:_LIST_PAGE_SIZE]`, zwraca `{"jobs": [_serialize_transfer_job(j) for j in jobs]}`.
- `db_job_status(request, job_id)`: analogiczne do `job_status`, ale na `DbTransferJob`, przez `_serialize_db_transfer_job`.
- `db_job_list(request)`: analogiczne do `job_list`, ale na `DbTransferJob.objects.all()`.
- URL-e w `apps/api/urls.py`: `jobs/`, `db-jobs/<int:job_id>/status/`, `db-jobs/` (nazwy: `job_list`, `db_job_status`, `db_job_list`).

## Obsługa błędów

- Nieprawidłowa wartość `?status=` → `400` z komunikatem wymieniającym dozwolone wartości (ułatwia debugowanie integracji CI bez czytania kodu źródłowego).
- Brak/nieprawidłowy token → `403` (istniejące zachowanie `require_api_token`, bez zmian).
- Puste listy (brak jobów pasujących do filtra) → `200 {"jobs": []}`, nie `404` — pusta lista to poprawny, nie błędny wynik.
- `db_job_status` dla nieistniejącego `job_id` → `404 {"error": "Not found"}`, identycznie jak dzisiejszy `job_status`.

## Testowanie

- `apps/api/tests/test_status.py`: rozszerzenie o nowe pola w istniejących testach `job_status` (assercja obecności `connection_id`/`flow_id`/`source_path`/`destination_path`/`created_at` — regresja kontraktu), plus nowa klasa `TestJobListEndpoint` (bez filtra, z `?status=`, filtr nieprawidłowej wartości → 400, pusta lista → 200, cap `_LIST_PAGE_SIZE` respektowany, brak tokenu → 403).
- Nowy plik `apps/api/tests/test_db_status.py` (wzorem `test_status.py`): `TestDbJobStatusEndpoint` (analogiczne przypadki jak `TestJobStatusEndpoint`: 200 z polami, done ze znacznikami czasu, failed z błędem, inny właściciel → 200 (org-wide), nieistniejący job → 404, brak tokenu → 403) i `TestDbJobListEndpoint` (analogiczne do `TestJobListEndpoint`, plus test że `table_name=''` serializuje się jako `null`).

## Global Constraints

- Istniejący kontrakt `job_status` nie traci ani nie zmienia znaczenia żadnego pola — tylko dodaje nowe.
- Żadna bramka roli na czterech endpointach odczytu — dowolny ważny `ApiToken` czyta dowolny job, dowolnego właściciela (org-wide, spójne z dzisiejszym `job_status`).
- Brak pełnej paginacji (offset/next-link) — tylko `?status=` + stały cap `_LIST_PAGE_SIZE=200`, zgodnie z małą skalą projektu.
- `table_name` pusty → `null` w JSON (nie pusty string), spójnie z istniejącym idiomem `error_message or None`.
- Dwie równoległe rodziny endpointów (`jobs/*`, `db-jobs/*`) — bez zunifikowanego endpointu mieszającego oba typy transferu.
