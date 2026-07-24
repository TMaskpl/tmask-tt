# Design: Transfer baza/tabela dla MySQL i MSSQL

**Data:** 2026-07-21
**Status:** Zaakceptowany, do implementacji
**Aktualizacja 2026-07-21 (w trakcie implementacji):** sekcja MSSQL poniżej zmieniona po Task 7 implementacji (infrastruktura Dockera) — `mssql-scripter` okazał się niedziałający na arm64 (brak stabilnego wydania od 2018, natywny backend `mssqltoolsservice` tylko x86_64, potwierdzony crash pod Rosettą na hoście deweloperskim). Produkcja tego projektu to amd64, więc narzędzie by tam prawdopodobnie działało, ale użytkownik zdecydował się zabezpieczyć na obu architekturach i zastąpić `mssql-scripter` własną introspekcją schematu przez `pyodbc` + `bcp`/`sqlcmd` (oba dostępne i potwierdzone działające na arm64 w ramach `mssql-tools18`). Sekcja "3. MSSQL" poniżej zaktualizowana do nowego podejścia; oryginalny opis oparty o `mssql-scripter` zachowany tylko w historii git tego pliku.

## Kontekst i cel

Rozszerzenie istniejącego modułu transferu baz danych (dziś tylko Postgres→Postgres, punkt #17) o MySQL i MSSQL. Pomysł użytkownika (2026-07-21), udokumentowany w vault: `11-Apps/CSCS/tmask-transporter/Propozycje rozbudowy.md`.

**Wymaganie kluczowe użytkownika:** kopiowanie nie może zależeć od konkretnej wersji silnika — transfer między różnymi wersjami tego samego silnika (np. MySQL 5.7 → 8.0, MSSQL 2017 → 2022) musi działać bez ręcznej interwencji.

**Zakres (ustalony przez pytania doprecyzowujące):**
- Tylko **ten sam silnik** po obu stronach — MySQL↔MySQL, MSSQL↔MSSQL, tak jak dziś Postgres↔Postgres. **Nie** ma tłumaczenia schematu/typów między różnymi silnikami (MySQL→MSSQL poza zakresem).
- MSSQL realizowany przez własną introspekcję schematu (`pyodbc`) + `bcp`/`sqlcmd` (zmiana z pierwotnie planowanego `mssql-scripter` — patrz aktualizacja wyżej).
- Appka `db_transfers` przestaje być Postgres-specyficzna — jedna wspólna appka/model/strona dla wszystkich trzech silników, nie osobne appki per silnik.

## Model danych

### `Connection` (rozszerzenie istniejącego modelu)

- `KIND_CHOICES` rozszerzone o `mysql` i `mssql` (obok istniejących `ssh`, `postgres`)
- `port` — formularz podpowiada domyślny port zależnie od wybranego `kind` przez JS (`5432` Postgres / `3306` MySQL / `1433` MSSQL) — czysto UX, pole samo w sobie zostaje zwykłym `IntegerField`
- `db_name` — reużyty bez zmian, wymagany dla wszystkich trzech `kind` bazodanowych (walidacja w `clean()` rozszerzona z `kind == KIND_POSTGRES` na `kind in (KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL)`)
- Reszta pól (`host`, `username`, `password`) — bez zmian, generyczne

### Appka `apps/db_transfers/` — generalizacja z Postgres-only na trzy silniki

**Rename modelu z zachowaniem danych:** `PgTransferJob` → `DbTransferJob`, `PgTransferLog` → `DbTransferLog`. Migracja Django `RenameModel` (zachowuje istniejące wiersze i historię transferów Postgres — nie jest to drop+recreate).

**`DbTransferJob`** (pola istniejące bez zmian: `source_connection`, `dest_connection`, `table_name`, `verify_row_count`, `status`, `celery_task_id`, `owner`, timestamps, `cancelled_by`):
- Nowe pole `engine` (`CharField`, choices `postgres`/`mysql`/`mssql`) — wypełniane automatycznie z `source_connection.kind` przy zapisie (`form.save()`), nie wybierane bezpośrednio przez usera jako osobne pole
- `clean()` rozszerzony: `source_connection.kind == dest_connection.kind` (oba silniki muszą się zgadzać — to jest twarde ograniczenie "ten sam silnik" z decyzji o zakresie)

**`DbTransferLog`** — bez zmian strukturalnych, tylko `job` FK wskazuje teraz na `DbTransferJob`.

## Moduł workera — trzy handlery, wspólny kontrakt

```
services/worker/modules/
├── postgres/   # PgTransferHandler — bez zmian funkcjonalnych
├── mysql/      # nowy: MysqlTransferHandler
└── mssql/      # nowy: MssqlTransferHandler
```

`tasks.py::execute_db_transfer` dispatchuje po `job.engine` zamiast dzisiejszego sztywnego `PgTransferHandler(...)`:

```python
HANDLER_BY_ENGINE = {
    'postgres': PgTransferHandler,
    'mysql': MysqlTransferHandler,
    'mssql': MssqlTransferHandler,
}
handler_cls = HANDLER_BY_ENGINE[job.engine]
handler_cls(params).execute(log_callback=log_callback)
```

Każdy handler implementuje ten sam kontrakt co `PgTransferHandler.execute(log_callback)` — reużywa istniejący `_verify_row_counts`-owy wzorzec (introspekcja + `COUNT(*)` per tabela, warning na niezgodność, status mimo to `done`), retry (3 próby, fresh subprocess pair per próba), i strukturę `_check_output`/`_run_pipe`.

### `MysqlTransferHandler` (`services/worker/modules/mysql/handler.py`)

Subprocess pipe: `mysqldump | mysql`, analogicznie do `pg_dump | psql`.

**Flagi bazowe `mysqldump`:**
```
--single-transaction          # spójny snapshot InnoDB bez blokowania zapisów
--set-gtid-purged=OFF         # patrz niżej — kluczowe dla przenośności między instancjami/wersjami
--skip-lock-tables
```
Gdy `table_name` ustawione: dopisuje nazwę tabeli jako ostatni argument (`mysqldump ... db_name table_name`).

**Kompatybilność między wersjami/instancjami — dwie realne, udokumentowane pułapki, adresowane od razu (nie "gdy się pojawią"):**

1. **GTID (Global Transaction Identifiers).** Bez `--set-gtid-purged=OFF` dump z serwera z włączonym GTID zawiera `SET @@GLOBAL.GTID_PURGED=...`, co wywali restore na serwer bez GTID (albo z inną historią GTID) błędem `ERROR 1840`. To jest *pewny* problem przy migracji między różnymi instancjami, nie edge case — flaga wchodzi do bazowych flag, zawsze.
2. **Kolacja `utf8mb4` między MySQL 5.7 a 8.0.** MySQL 8.0 zmienił domyślną kolację `utf8mb4` z `utf8mb4_general_ci` na `utf8mb4_0900_ai_ci`. Dump z MySQL 8 zawiera `COLLATE utf8mb4_0900_ai_ci` w `CREATE TABLE`; restore na MySQL 5.7 (który tej kolacji nie zna) kończy się błędem `Unknown collation`. Mitigacja: przed transferem handler odpytuje wersję serwera **docelowego** (`SELECT VERSION()` przez `pymysql`); jeśli cel to MySQL < 8.0, filtr `sed` (analogiczny do istniejącego `SED_STRIP_INCOMPATIBLE_SET` dla Postgres) usuwa `COLLATE utf8mb4_0900_ai_ci` z przesyłanego strumienia SQL przed dojściem do `mysql`, zostawiając domyślną kolację serwera docelowego.

Hasła przez `MYSQL_PWD` env var per subprocess (source dla `mysqldump`, dest dla `mysql`) — nigdy jako argument CLI, ten sam wzorzec co `PGPASSWORD`.

**Wymagania obrazu:** pakiet `default-mysql-client` (apt, standardowe repo Debian) — dostarcza `mysqldump`/`mysql`.

**Introspekcja (web):** nowy `apps/connections/mysql_utils.py::list_tables()` — `pymysql`, `SELECT table_name FROM information_schema.tables WHERE table_schema = %s`.

### `MssqlTransferHandler` (`services/worker/modules/mssql/handler.py`)

**Zmiana z pierwotnego projektu (patrz aktualizacja na górze dokumentu):** zamiast `mssql-scripter` (niedziałający na arm64), handler sam introspektuje schemat źródła przez `pyodbc` i generuje `CREATE TABLE`, a do przesłania danych używa `bcp` (bulk copy, część `mssql-tools18`, obecny obok `sqlcmd`, potwierdzony działający na arm64).

Ponieważ transfer jest zawsze między tym samym silnikiem (MSSQL↔MSSQL, decyzja o zakresie), introspekcja nie musi tłumaczyć typów — nazwa typu, długość/precyzja i nullability ze źródła są odtwarzane 1:1 na celu. To **eliminuje potrzebę wykrywania wersji docelowego serwera i flagi `--target-server-version`** z pierwotnego projektu — generujemy zwykłe, stabilne składniowo T-SQL (`CREATE TABLE` z podstawowymi typami), które działa bez zmian na każdej rozsądnie nowoczesnej wersji SQL Server (2012+), zamiast polegać na tym, że output nowszego narzędzia przypadkiem zadziała na starszym serwerze. To w praktyce prostsze i solidniejsze niż pierwotny projekt.

Przebieg:
1. **Introspekcja schematu (source, przez `pyodbc`):** `SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION` per tabela (jedna tabela albo wszystkie z `INFORMATION_SCHEMA.TABLES` gdy `table_name` puste); klucz główny z `INFORMATION_SCHEMA.TABLE_CONSTRAINTS`/`KEY_COLUMN_USAGE` (`CONSTRAINT_TYPE='PRIMARY KEY'`)
2. **Generowanie DDL:** `DROP TABLE IF EXISTS [tbl]; CREATE TABLE [tbl] (...)` z odtworzonymi kolumnami + `PRIMARY KEY` (analogicznie do `--clean --if-exists` w Postgres/MySQL) — zapisane do pliku tymczasowego
3. **Wykonanie DDL na celu:** `sqlcmd -S dest_host,port -d db_name -U user -P password -i <plik_ddl>`
4. **Kopiowanie danych, per tabela:** `bcp [tbl] out <tmpfile> -S source_host,port -U user -P password -d db_name -n` (format natywny — `bcp` sam poprawnie koduje typy, bez ręcznego escape'owania literałów w `INSERT`), następnie `bcp [tbl] in <tmpfile> -S dest_host,port -U user -P password -d db_name -n` na cel
5. Pliki tymczasowe usuwane w `finally`, tak jak istniejące tymczasowe pliki kluczy SSH/known_hosts w innych modułach

**Świadomie poza zakresem tej iteracji** (redukcja względem pierwotnego projektu opartego o `mssql-scripter`, który odtworzyłby pełne DDL): klucze obce, indeksy niebędące PK, triggery, computed columns — nieodtwarzane. Dokumentowane ograniczenie, nie cichy brak.

Hasła przez argumenty `-P` są nieuniknione przy `sqlcmd`/`bcp` (nie obsługują env var na hasło jak `PGPASSWORD`/`MYSQL_PWD`) — **ryzyko do zaakceptowania i udokumentowania**: proces widoczny chwilowo w `ps aux` na hoście workera. Alternatywa (plik konfiguracyjny z hasłem, czyszczony po użyciu) rozważona jako możliwe dalsze utwardzenie, nie blokuje pierwszej iteracji.

**Wymagania obrazu:** repozytorium apt Microsoftu (nie ma w domyślnych repo Debiana) dla `mssql-tools18` (`sqlcmd` + `bcp`) + `msodbcsql18` (ODBC driver, wymagany też przez `pyodbc`) — **już zrealizowane w Task 7**, potwierdzone działające na arm64. Brak zależności od `mssql-scripter`.

**Introspekcja (web):** nowy `apps/connections/mssql_utils.py::list_tables()` — `pyodbc`, `SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'`.

## UI / formularz

**`NEW DB TRANSFER`** (`/db-transfers/new/`) — jeden formularz, wybór silnika na górze filtruje resztę:

```
ENGINE:                 ( ) POSTGRES  (•) MYSQL  ( ) MSSQL
SOURCE CONNECTION:      [ prod-mysql       ▾ ]   (dropdown, tylko connections tego samego kind co ENGINE)
SCOPE:                  ( ) CAŁA BAZA
                        (•) POJEDYNCZA TABELA
TABLE:                  [ users            ▾ ]   (dropdown HTMX, widoczny tylko gdy SCOPE=tabela)
DESTINATION CONNECTION: [ test-mysql        ▾ ]   (dropdown, tylko ten sam kind co SOURCE, != SOURCE)
VERIFY ROW COUNT:       [ ] (checkbox)

[ EXECUTE TRANSFER ]
```

- Zmiana `ENGINE` (JS) przeładowuje opcje `SOURCE CONNECTION`/`DESTINATION CONNECTION` do connections pasującego `kind` (dane już są w DOM przez `connection_protocols`-owy wzorzec, analogicznie do dzisiejszego `json_script`)
- **TABLE dropdown** — `hx-get` do jednego wspólnego endpointu `connections:db_tables` (uogólnienie dzisiejszego `pg_tables`), który wewnątrz rozgałęzia się po `connection.kind` na `pg_utils`/`mysql_utils`/`mssql_utils`
- Walidacja formularza: `source_connection.kind == dest_connection.kind` (twarde), `source_connection != dest_connection`
- Potwierdzenie przed wykonaniem — bez zmian względem istniejącego wzorca Postgres, treść komunikatu generyczna względem silnika

**Lista `/db-transfers/`** — dodać kolumnę `ENGINE` do istniejącej tabeli (POSTGRES/MYSQL/MSSQL), reszta bez zmian.

**Formularz `Connection`** — blok pól bazodanowych (`DB NAME`) widoczny dla wszystkich trzech `kind` bazodanowych zamiast tylko `kind='postgres'`; domyślny port podpowiadany JS-em przy zmianie `kind`.

**RBAC** — bez zmian, identycznie jak dziś.

## Testy

**Worker (TDD), `test_mysql_handler.py` / `test_mssql_handler.py`** — mirror struktury `test_postgres_handler.py`:
- Budowa komendy: cała baza vs pojedyncza tabela, obecność `--set-gtid-purged=OFF`/`--single-transaction` (MySQL)
- `MYSQL_PWD`/hasło nigdy w liście argumentów subprocess dla MySQL (test kontraktowy, wzorzec z `PGPASSWORD`) — dla MSSQL odwrotnie: test **potwierdzający świadomie zaakceptowane** przekazanie hasła przez `-P` (dokumentuje ryzyko, nie ukrywa go)
- Filtr kolacji MySQL: mock wersji serwera docelowego < 8.0 → `COLLATE utf8mb4_0900_ai_ci` usunięty ze strumienia; wersja >= 8.0 → strumień nietknięty
- Introspekcja schematu MSSQL: mock `pyodbc` zwracający kolumny + PK → poprawnie wygenerowany `CREATE TABLE`
- Retry przy symulowanym błędzie sieciowym (mock `Popen`), dla obu silników
- `verify_row_count`: zgodność/niezgodność, jak w Postgres

**Web (TDD):**
- `Connection` model/form: `db_name` wymagane dla `kind` in (`postgres`,`mysql`,`mssql`)
- `DbTransferForm`: filtrowanie connections po wybranym silniku, blokada różnych `kind` source/dest, blokada `source == dest`
- `mysql_utils.py`/`mssql_utils.py` — mock odpowiednio `pymysql`/`pyodbc`, sukces/błąd
- Endpoint `db_tables/` — trzy warianty (po `kind`), mock introspekcji
- Migracja `RenameModel` — test regresyjny: istniejące dane `PgTransferJob`/`PgTransferLog` sprzed migracji nadal czytelne jako `DbTransferJob`/`DbTransferLog` po jej zastosowaniu

## Poza zakresem, celowo

- Transfer między różnymi silnikami (MySQL→MSSQL, MSSQL→Postgres itd.) — wymagałby tłumaczenia typów/schematu, świadomie odrzucone w tej iteracji (decyzja użytkownika)
- Integracja ze Schedulerem i REST API trigger — jak w module Postgres, możliwe rozszerzenie później
- Dokładny progress % dla MySQL/MSSQL — tylko live log linii, jak dziś we wszystkich modułach transferu
- Utwardzenie przekazywania hasła MSSQL (env/plik configu zamiast `-P`) — udokumentowane jako możliwe dalsze ulepszenie, nie blokuje pierwszej iteracji
- Transakcyjny rollback przy częściowej awarii — nie jest możliwy technicznie w żadnym z trzech silników z tym podejściem (dump|restore między dwoma serwerami), ryzyko już zaakceptowane i udokumentowane dla Postgres, dotyczy też MySQL/MSSQL
