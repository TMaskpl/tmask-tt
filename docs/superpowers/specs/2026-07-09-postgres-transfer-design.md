# Design: Moduł Postgres → Postgres (transfer baza/tabela)

**Data:** 2026-07-09
**Status:** Zaakceptowany, do implementacji po zakończeniu bieżącego modułu (podgląd dry-run rsync, spec `2026-07-08-dry-run-preview-design.md`)

## Kontekst i cel

Ręczny transfer danych między dwoma instancjami PostgreSQL — cała baza albo pojedyncza tabela — z jednego środowiska do drugiego (typowy use case: replika produkcji do środowiska testowego). Czwarty typ modułu transferu obok `sftp/`/`rsync/`/(planowanego `s3`), ale o innym charakterze niż transfer plików.

Pomysł użytkownika z 2026-07-08, udokumentowany w vault: `11-Apps/CSCS/tmask-transporter/Propozycje rozbudowy.md`, punkt #17.

**Zakres:** ręczny transfer on-demand (jak dzisiejsze `Transfers`), **nie** integracja ze Schedulerem ani REST API w tej iteracji.

## Model danych

### `Connection` (rozszerzenie istniejącego modelu)

- Nowe pole `kind` (`CharField`, choices `ssh`/`postgres`, default `ssh`) — migracja danych: wszystkie istniejące wiersze dostają `kind='ssh'`
- Nowe pole `db_name` (`CharField`, blank=True) — wymagane tylko gdy `kind='postgres'` (walidacja w `clean()`/formularzu)
- Pola SSH-specific (`ssh_key`, `protocol`, `compress`, `strict_host_key_checking`, `known_host_key`, `dry_run_before_transfer`) — pozostają na modelu bez zmian, ale w formularzu/UI widoczne i wymagane tylko gdy `kind='ssh'` (JS toggle, wzorzec identyczny jak dzisiejszy toggle pola `known_host_key`)
- `host`/`port`/`username`/`password` — reużyte bez zmian (już szyfrowane Fernet, `django-encrypted-model-fields`)
- Lista `/connections/` — nowa kolumna/filtr `KIND`; przycisk `[TEST]` rozgałęzia się w widoku: `ssh_tester.test_connection()` dla `kind='ssh'` (bez zmian), nowy `pg_tester.test_connection()` dla `kind='postgres'` (psycopg2 `connect()` + `SELECT 1`, timeout krótki)

### Nowa appka `apps/db_transfers/`

**`PgTransferJob`:**
- `source_connection` (FK `Connection`) — musi mieć `kind='postgres'`
- `dest_connection` (FK `Connection`) — musi mieć `kind='postgres'`, musi różnić się od `source_connection` (walidacja formularza — brak sensownego use case dla self-transferu, `--clean` nadpisałby tabelę samą sobą)
- `table_name` (`CharField`, blank=True) — puste = cała baza
- `verify_row_count` (`BooleanField`, default=False)
- `status` (`CharField`, choices identyczne z `TransferJob`: `pending`/`running`/`done`/`failed`/`cancelled`)
- `started_at`, `finished_at`, `error` (`TextField`, blank)
- `owner` (FK `User`, audytowe — widoczność org-wide jak inne zasoby, `require_role()`)
- `celery_task_id` — capture natychmiast przy `send_task()` (ten sam fix co w `TransferJob` dla poprawnego działania Stop na `pending` jobach)

**`PgTransferLog`:**
- `job` (FK `PgTransferJob`), `timestamp`, `line` (`TextField`) — struktura 1:1 z `TransferLog`, niezależny cykl życia

## Moduł workera (`services/worker/modules/postgres/`)

```
services/worker/modules/postgres/
├── config.py   # PG_DUMP_TIMEOUT, PG_DUMP_MAX_RETRIES, PG_DUMP_RETRY_DELAY, PG_DUMP_BASE_FLAGS
└── handler.py  # PgTransferHandler
```

**`PgTransferHandler.execute()`:**

1. Buduje komendę `pg_dump` (source) i `psql` (dest) jako dwa subprocessy połączone pipe'm: `Popen(pg_dump_cmd, stdout=PIPE, stderr=PIPE)` → `Popen(psql_cmd, stdin=pg_dump_proc.stdout, stderr=PIPE)`
2. Flagi bazowe (`PG_DUMP_BASE_FLAGS`): `--clean --if-exists --no-owner --no-privileges --verbose`
3. Gdy `table_name` ustawione: dopisuje `--table=<table_name>` do komendy `pg_dump` — ten sam mechanizm obsługuje cały zakres (cała baza / pojedyncza tabela), bez rozgałęzień w kodzie
4. Hasła przez `PGPASSWORD` env var, osobno per subprocess (source password dla `pg_dump`, dest password dla `psql`) — odszyfrowane z Fernet tuż przed użyciem, **nigdy** jako argument CLI (nie trafia do `ps aux` ani logów) — env, nie stdin, bo tak działa libpq
5. Live log: stderr obu procesów strumieniowany do `PgTransferLog` linia-po-linii (`--verbose` daje realne wpisy postępu: `pg_dump: dumping contents of table "x"`)
6. Po sukcesie (`returncode == 0` dla obu procesów): jeśli `verify_row_count=True` — `SELECT COUNT(*)` per tabela (single-table: jedna tabela; whole-db: wszystkie z `information_schema.tables` po stronie source) po obu stronach połączenia; rozbieżność → log **WARNING** (status pozostaje `done` — dane już fizycznie przeniesione, nie ma czego cofać, w przeciwieństwie do checksumy w SFTP/relay gdzie niezgodność blokuje sukces przed jego potwierdzeniem)
7. Retry: świeża para subprocessów per próba (jak fresh `SSHClient` per retry w SFTP) — tylko dla błędów sieciowych/timeout; błędy danych (np. brak tabeli źródłowej) nie są retry'owane, bo nie są transient
8. Błąd w trakcie transferu (np. `psql` pada w połowie po tym jak `--clean` już wykasował część tabel po stronie celu) → `FAILED`, log jasno opisuje: "transfer przerwany w trakcie — cel może być w stanie częściowym". **Świadomie zaakceptowane ryzyko** — pg_dump|psql nie działa w jednej transakcji między dwoma serwerami, więc nie ma tu transakcyjnego rollbacku. Ta sama klasa ryzyka co już udokumentowane ryzyko częściowego pliku przy SIGTERM w innych modułach.

**Wymagania obrazu:** `services/worker/Dockerfile` — doinstalować pakiet systemowy `postgresql-client` (dostarcza `pg_dump`/`psql`), analogicznie do już obecnego `rsync`.

**Introspekcja tabel (dla dropdownu w UI):** dzieje się w `web`, nie w workerze. Nowy endpoint `GET /connections/<pk>/pg-tables/` — łączy się przez `psycopg2` do source connection, `SELECT tablename FROM pg_tables WHERE schemaname='public'`, zwraca listę nazw (fragment HTML dla HTMX). Wymaga `psycopg2-binary` w `services/web/requirements.txt`. Worker **nie** potrzebuje Python DB drivera — tam wyłącznie binarki `pg_dump`/`psql` przez subprocess.

## UI / formularz

**`NEW DB TRANSFER`** (`/db-transfers/new/`):

```
SOURCE CONNECTION:      [ prod-db          ▾ ]   (dropdown, tylko kind=postgres)
SCOPE:                  ( ) CAŁA BAZA
                         (•) POJEDYNCZA TABELA
TABLE:                   [ users            ▾ ]  (dropdown HTMX, widoczny tylko gdy SCOPE=tabela)
DESTINATION CONNECTION: [ test-db           ▾ ]   (dropdown, tylko kind=postgres, != SOURCE)
VERIFY ROW COUNT:       [ ] (checkbox)

[ EXECUTE TRANSFER ]
```

- **TABLE dropdown** — `hx-get="/connections/<pk>/pg-tables/" hx-trigger="change from:#id_source_connection" hx-target="#id_table_name"`, wypełnia `<option>` po zmianie SOURCE
- **SCOPE toggle** — JS show/hide bloku TABLE, wzorzec identyczny jak dzisiejszy toggle `known_host_key`
- **Walidacja formularza**: oba connections `kind='postgres'`; `source_connection != dest_connection` (zawsze, niezależnie od SCOPE)
- **Potwierdzenie przed wykonaniem** (wymagane przez użytkownika w tej iteracji) — `[EXECUTE TRANSFER]` z `onclick="return confirm(...)"`, treść zależna od SCOPE:
  - Cała baza: *"Czy na pewno? Nadpisze WSZYSTKIE tabele w bazie '<dest.db_name>' (<dest.name>) danymi z '<source.name>'."*
  - Tabela: *"Czy na pewno? Nadpisze tabelę '<table>' w '<dest.name>' danymi z '<source.name>'."*

**Lista `/db-transfers/`** — tabela CRT, kolumny: SOURCE, DEST, SCOPE (cała baza / nazwa tabeli), STATUS, STARTED, FINISHED, akcja `[LOG]`. Wzorzec 1:1 z dzisiejszą listą `/transfers/`.

**Widok logu** (`/db-transfers/<pk>/`) — live log HTMX polling co 2s, identyczny mechanizm co `TransferLog`.

**Stop transferu** — `POST /db-transfers/<pk>/stop/`, `celery.control.revoke(task_id, terminate=True)`, `celery_task_id` capture natychmiast przy dispatch (ten sam wzorzec co punkt #13 w projekcie — tanio dodać, bo mechanizm już istnieje na poziomie Celery).

**Nawigacja** — nowy link `[ DB TRANSFERS ]` w navbarze, obok istniejących.

**Formularz `Connection`** — pole `kind` jako select na górze, JS `onchange` przełącza widoczność dwóch bloków pól (SSH-block vs Postgres-block: `DB NAME`).

**RBAC** — `require_role()` identycznie jak `TransferJob` dziś: Admin pełna konfiguracja (w tym Connections typu postgres), Operator uruchamia/zatrzymuje, Read-only wyłącznie podgląd.

## Testy

**Worker (TDD), `test_postgres_handler.py`:**
- Budowa komendy: cała baza vs `--table=X`, flagi `--clean --if-exists --no-owner --no-privileges`
- `PGPASSWORD` przekazywane przez `env=`, **nigdy** w liście argumentów subprocess — test kontraktowy pinujący to explicite (projekt ma udokumentowaną historię subtelnych błędów kontraktu w dokładnie tym miejscu, patrz `TestRemoteSha256Contract` dla precedensu)
- Retry przy symulowanym błędzie sieciowym (mock `Popen`)
- `verify_row_count`: zgodność → brak warninga; niezgodność → log WARNING, status mimo to `done`

**Web (TDD):**
- `Connection` model/form: `db_name` wymagane gdy `kind='postgres'`, pola SSH nieużywane/ukryte dla `kind='postgres'`
- `PgTransferForm`: oba connections `kind='postgres'`, blokada `source_connection == dest_connection`
- `pg_tester.py` — mock psycopg2, sukces/błąd
- Endpoint `pg-tables/` — mock introspekcji, zwraca listę nazw
- Widoki listy/logu/stop `PgTransferJob` — RBAC dla wszystkich trzech ról

## Poza zakresem, celowo

- Integracja ze Schedulerem (cron) i REST API trigger — możliwe rozszerzenie później, nie w tej iteracji
- Dokładny progress % (pg_dump nie daje tego tanio) — tylko live log linii, jak dziś w innych modułach (ten sam nierozwiązany TODO co dla transferu plików)
- Filtrowanie wierszy / selektywny eksport kolumn — cała tabela albo cała baza, tak jak `pg_dump` ją widzi
- Transakcyjny rollback przy częściowej awarii między dwoma serwerami — nie jest technicznie możliwy z `pg_dump | psql`, ryzyko udokumentowane i zaakceptowane
