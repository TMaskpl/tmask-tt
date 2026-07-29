# Maskowanie danych w transferach DB→DB — Design

## Kontekst i problem

Moduły `db_transfers` (Postgres #17, MySQL/MSSQL #23) replikują bazę/tabelę 1:1 z produkcji "do środowisk testowych" bez żadnej transformacji danych. To realne ryzyko RODO/compliance — produkcyjne PII (e-maile, telefony, adresy, nazwiska) trafia bez zmian do dev/test, gdzie dostęp bywa szerszy i mniej kontrolowany.

Cel: opcjonalny, konfigurowalny krok maskowania wybranych kolumn w pipeline transferu, zastępujący realne wartości danymi wygenerowanymi przez Faker (format-preserving, realistycznie wyglądające fake dane — nie NULL/hash/redact).

## Zakres

Wszystkie trzy silniki naraz: Postgres, MySQL, MSSQL. Świadomie większy zakres niż typowa "szybka wygrana" — porównywalny do #23 (MySQL/MSSQL dla db_transfers), które też objęło od razu wszystkie silniki w jednym cyklu.

**Poza zakresem (v1), świadomie odłożone:**
- Maskowanie kolumn numerycznych/dat — tylko string-like (`varchar`/`text`/`char`/`nvarchar` itp.).
- Deterministyczne/seedowane fake wartości (ta sama wartość źródłowa → ten sam fake za każdym razem) — każdy przebieg generuje świeże losowe dane.
- Spójność referencyjna fake wartości między tabelami (np. ten sam fake e-mail dla tego samego użytkownika w dwóch tabelach) — wynika wprost z braku determinizmu powyżej.
- Blokowanie transferu CAŁA BAZA przy niepełnym pokryciu profilami — brak profilu dla tabeli = przepuszczenie bez maskowania + `WARN` w logu, nie blokada.
- Podgląd/dry-run zamaskowanych danych przed uruchomieniem transferu — naturalne rozszerzenie na przyszłość, nie budujemy teraz.

## Architektura mechanizmu

Trzy silniki mają dziś fundamentalnie różny transport danych, więc nie ma jednego uniwersalnego triku SQL-owego (SQL VIEW z maskowaniem odpada — Faker działa w Pythonie, nie w SQL). Rozwiązanie: **wspólny moduł Python + cienkie adaptery per silnik**, żeby logika "zastosuj Faker z poszanowaniem długości kolumny i bezpiecznym escapowaniem" żyła w jednym miejscu, nie w trzech niezależnie dryfujących kopiach.

`services/worker/modules/masking/` — nowy pakiet współdzielony przez wszystkie trzy handlery:
- Curated whitelist generatorów Faker (nie dowolna metoda) — pokrywa typowe PII: `name`, `first_name`, `last_name`, `email`, `phone_number`, `street_address`, `city`, `postcode`, `country`, `company`, `job_title`.
- Funkcja `mask_value(provider, max_length) -> str` — generuje fake wartość, obcina do `max_length` jeśli podany.
- Per-format transformery wiersza (COPY TSV dla PG, `INSERT ... VALUES` dla MySQL, tab-delimited dla bcp `-c`) — każdy zna tylko swój format, deleguje generowanie do wspólnej funkcji.

### Postgres

`PgTransferHandler._run_pipe` przestaje puszczać `sed` jako proces OS-owy między `pg_dump` a `psql`. W jego miejsce Python-owy relay (wątek czytający `dump_proc.stdout`, piszący do `psql_proc.stdin`) który:
1. Rozpoznaje linie `COPY <table> (<col1>, <col2>, ...) FROM stdin;` — zapamiętuje bieżącą tabelę i kolejność kolumn.
2. Dla tabel z aktywnym `MaskingRule` podmienia wartości w wierszach TSV (do napotkania `\.`) na wygenerowane fake, z zachowaniem PostgreSQL-owego escapowania COPY (backslash, tab, newline, carriage return).
3. Zachowuje istniejące zachowanie `SED_STRIP_INCOMPATIBLE_SET` (`SET transaction_timeout`) — przenosi je z `sed` do tego samego relaya jako prosty string-check per linia.
4. Tabele bez reguł przechodzą bez zmian, bit-for-bit jak dziś.

### MySQL

`mysqldump` dostaje dodatkowe flagi `--skip-extended-insert --complete-insert` **tylko gdy dla danego połączenia źródłowego istnieje choć jedna aktywna `MaskingRule`** — wymusza jeden `INSERT INTO \`table\` (\`col1\`,\`col2\`) VALUES (...)` per wiersz zamiast dzisiejszych batchowanych multi-row INSERT-ów, bo tylko taki format da się bezpiecznie sparsować pozycyjnie. **Efekt uboczny do zaakceptowania**: to spowalnia dump dla wszystkich tabel w tej bazie (nie tylko maskowanych), jeśli connection ma jakikolwiek profil — akceptowalne, bo dotyczy tylko połączeń świadomie skonfigurowanych do maskowania.

Relay parsuje rozpoznane `INSERT` (biblioteka do bezpiecznego tokenizowania wartości SQL, nie naiwny `split(',')` — musi respektować cudzysłowy i ich escapowanie), podmienia wartości masowanych kolumn, re-serializuje z properowym MySQL-owym escapowaniem stringów (analogicznie do `pymysql`'s escape). Istniejące `SED_STRIP_MYSQL80_COLLATION` przenosi się tym samym mechanizmem co w Postgresie.

### MSSQL

`bcp out`/`bcp in` przełącza się z trybu binarnego (`-n`) na tekstowy tab-delimited (`-c`) **per tabela, tylko dla tabel z aktywnym profilem** (już dziś pętla po tabelach jest per-table, więc to tani warunek). Relay czyta wygenerowany `.dat` (format tekstowy, kolejność kolumn już znana z istniejącej `_introspect_table`), podmienia maskowane kolumny, nadpisuje plik przed `bcp in`. Tabele bez profilu zostają przy `-n` jak dziś.

## Model danych

Nowa appka `apps/masking` (web) — spójne z istniejącym wzorcem wydzielonych, skupionych appek (`apps/webhook_deliveries`, `apps/audit_log`).

```python
class MaskingRule(models.Model):
    connection      = models.ForeignKey('connections.Connection', on_delete=models.CASCADE)
    table_name      = models.CharField(max_length=255)
    column_name     = models.CharField(max_length=255)
    faker_provider  = models.CharField(max_length=30, choices=FAKER_PROVIDER_CHOICES)
    created_by      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('connection', 'table_name', 'column_name')
```

`connection` to zawsze połączenie **źródłowe** — reguła opisuje "ta tabela na tym źródle zawsze ma te kolumny zamaskowane", niezależnie od tego dokąd trafia. Przy tworzeniu/wykonywaniu `DbTransferJob` worker pobiera `MaskingRule.objects.filter(connection=job.source_connection, table_name=<tabela w zakresie>)` i buduje mapę kolumna→provider przekazywaną do handlera — **stosuje się automatycznie**, bez zaznaczania czegokolwiek w formularzu transferu.

## Wykrywanie generatora i UI

Auto-sugestia po nazwie kolumny (case-insensitive substring match, pierwsze dopasowanie z góry listy wygrywa) — pełna tabela słów kluczowych:

| Słowo kluczowe w nazwie kolumny | Sugerowany provider |
|---|---|
| `first_name`, `given_name`, `firstname` | `first_name` |
| `last_name`, `surname`, `lastname` | `last_name` |
| `name`, `fullname` (i nie złapane przez dwa powyższe) | `name` |
| `email`, `mail` | `email` |
| `phone`, `tel`, `mobile` | `phone_number` |
| `street`, `address1`, `address_line` | `street_address` |
| `city`, `town` | `city` |
| `zip`, `postcode`, `postal` | `postcode` |
| `country` | `country` |
| `company`, `employer`, `organization` | `company` |
| `job`, `title`, `position` | `job_title` |

Brak dopasowania → pole wymaga ręcznego wyboru przed zapisem, nic nie zapisuje się bez jawnie wybranego generatora.

**Nowy endpoint AJAX** `list_columns(connection, table_name)` w `apps/masking`, wykorzystujący nowe funkcje `list_columns()` dopisane do istniejących `apps/connections/{pg,mysql,mssql}_utils.py` (analogicznie do obecnego `list_tables()`) — zwraca nazwę, typ i flagę `maskable` per kolumna. **Maskowalne (string-like) typy per silnik:**

| Silnik | Typy uznawane za maskowalne |
|---|---|
| Postgres | `character varying`, `varchar`, `text`, `char`, `character` |
| MySQL | `varchar`, `char`, `text`, `tinytext`, `mediumtext`, `longtext` |
| MSSQL | `varchar`, `nvarchar`, `char`, `nchar`, `text`, `ntext` |

Wszystkie inne typy (numeryczne, daty, boolean, uuid/binary) są widoczne w UI, ale wyszarzone/nieklikalne.

**RBAC**: CRUD reguł maskowania — Admin-only (spójne z `ConfigAuditLog` #19 dla Connection/Flow — decyduje co wycieka do test/dev, wysokie ryzyko przy złej konfiguracji). Operator widzi informacyjnie, że dana tabela ma aktywny profil, nie edytuje. Zmiany reguł logowane w `ConfigAuditLog` tym samym wzorcem co edycja Connection/Flow.

## Obsługa błędów i przypadków brzegowych

| Sytuacja | Zachowanie |
|---|---|
| Scope CAŁA BAZA, tabela bez profilu | Przepuszczona bez maskowania, `WARN` w logu transferu |
| Fake wartość dłuższa niż `character_maximum_length` | Obcięcie do limitu przed wysłaniem |
| Reguła wskazuje kolumnę, która już nie istnieje w tabeli (dryf schematu) | Reguła dla tej kolumny pomijana + `WARN` w logu, transfer nie failuje |
| Fake wartość zawiera znak wymagający escapowania (cudzysłów, tab) | Serializacja przez to samo bezpieczne escapowanie co reszta pipeline'u per silnik — nigdy naiwny string format |
| Connection bez żadnej `MaskingRule` | Zero zmiany zachowania względem dzisiejszego kodu — bit-for-bit ten sam dump |

## Testowanie

- Testy jednostkowe per parser wiersza — fixture z przykładowym fragmentem `COPY ... FROM stdin` / `INSERT ... VALUES` / linii bcp `-c`, weryfikacja podmiany maskowanej kolumny, poszanowania długości, przepuszczenia niemaskowanych kolumn bez zmian.
- Test regresyjny: transfer bez żadnego `MaskingRule` musi dać identyczny wynik jak dziś (bit-for-bit dla PG/MySQL dump, `-n` dla MSSQL) — gwarancja że feature jest czysto addytywny.
- Test integracyjny na realnej bazie w Dockerze (istniejący `docker compose --profile test`): pełny przebieg `DbTransferJob` z aktywnym `MaskingRule` — dane w destination różne od źródłowych dla maskowanej kolumny, `verify_row_count` nadal się zgadza.
- Testy CRUD `MaskingRule` (RBAC — Admin może, Operator/Read-only nie mogą tworzyć/edytować) i wpisu do `ConfigAuditLog`.

## Ryzyka

- **MySQL global flag effect**: `--skip-extended-insert` spowalnia dump całej bazy, gdy istnieje choć jedna reguła dla tego connection — akceptowalny trade-off, udokumentowany wyżej, nie ukrywany.
- **Silny nacisk na poprawność escapowania** — błąd w serializacji fake wartości może uszkodzić restore (SQL injection do własnego dumpa, złamany COPY stream). Wymaga dedykowanych testów jednostkowych per silnik, nie tylko integracyjnych.
- **Fałszywe poczucie bezpieczeństwa przy braku profilu** w scope CAŁA BAZA — złagodzone przez jawny `WARN` w logu (nie ciche pominięcie), ale nadal wymaga świadomej lektury logu przez użytkownika.
