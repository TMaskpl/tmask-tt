# Design: Retencja i auto-cleanup wolumenu `/transfers`

**Data:** 2026-07-06
**Status:** Zatwierdzony (brainstorming)

## Kontekst i problem

Pole „LOCAL ./TRANSFERS" w formularzu transferu (od 2026-07-01, punkt #12 roadmapy)
przestało być nazwą pliku już leżącego na serwerze — stało się uploadem pliku z
przeglądarki, zapisywanym przez `web` do współdzielonego wolumenu `/transfers`
(`settings.TRANSFERS_DIR`), skąd `worker` go czyta i wysyła dalej (SFTP/rsync).
Ten sam wolumen może też otrzymać `source_path` od zewnętrznego wywołania REST API
(`apps/api/views.py::trigger_connection`) — walidacja (`_validate_transfer_path`)
blokuje tylko traversal/znaki kontrolne, nie wymusza ścieżki pod `/transfers/`.

Żaden mechanizm nie usuwa tych plików po zakończeniu transferu — dokumentacja
punktu #12 (`Projekt-tmask-transporter.md`) wprost nazywa to zaakceptowanym
długiem. Wolumen rośnie bezterminowo z każdym uploadem o unikalnej nazwie.

Uwaga: transfery **relay/Flow** (SFTP→SFTP) nie korzystają z `/transfers` —
`source_path` wskazuje tam na ścieżkę na zdalnym hoście źródłowym. Ten spec
dotyczy wyłącznie jobów `connection`-based (`job.connection_id`, `job.flow_id is
None`).

Analogiczny periodic task już istnieje: `transfers.cleanup_orphans`
(`worker/tasks.py:183`, zarejestrowany migracją
`0002_cleanup_periodic_task.py`) — czyści rekordy `TransferJob` utknięte w
statusie `running` po restarcie workera. To osobny problem (baza danych, nie
pliki); nowy task nie rozszerza go, tylko idzie tym samym wzorcem
implementacyjnym.

## Cel

Dwa niezależne, uzupełniające się mechanizmy sprzątania `/transfers`:

1. Plik znika **natychmiast** po udanym transferze.
2. Wszystko, co mimo to zostanie (transfer failed/cancelled, sierota bez
   powiązanego joba) — usuwane przez periodic task po przekroczeniu progu wieku.

## Decyzje projektowe

1. **Zakres natychmiastowego usuwania:** każdy plik pod `TRANSFERS_DIR`
   wskazany przez `job.source_path`, po `job.mark_done()`, niezależnie od
   pochodzenia (upload z formularza czy `source_path` z REST API trigger).
   Świadomie zaakceptowane ryzyko: zewnętrzny skrypt reużywający ten sam plik
   do kilku triggerów API pod rząd dostanie błąd przy drugim wywołaniu — to
   kontrakt do zmiany po stronie wołającego (re-upload przed każdym triggerem),
   nie powód do komplikowania mechanizmu w TMask.
2. **Zakres retention taska:** skanowanie **wieku pliku na dysku** (`mtime`),
   niezależnie od stanu w bazie — nie JOINuje z `TransferJob`. Prostsze (jedno
   zapytanie do filesystemu) i łapie też prawdziwe sieroty (np. plik zapisany
   przez upload, dla którego utworzenie joba nie powiodło się). `/transfers`
   potwierdzone jako płaski katalog — GPG pisze tymczasowe pliki do
   systemowego `/tmp` (`tempfile.mkstemp`), nie do `/transfers`, więc retention
   task nie musi obsługiwać podkatalogów.
3. **Próg retencji:** nowe ustawienie `TRANSFERS_RETENTION_DAYS` (domyślnie
   `1`), czytane z `.env` przez `python-decouple` (`config('TRANSFERS_RETENTION_DAYS',
   default=1, cast=int)`), analogicznie do istniejącego `EMAIL_PORT`. Krótki
   domyślny próg jest bezpieczny, bo pliki po sukcesie i tak znikają
   natychmiast — 1 dzień dotyczy tylko failed/cancelled/sierot.
4. **Harmonogram:** nowy `PeriodicTask` co **1 godzinę**
   (`IntervalSchedule(every=1, period='hours')`) — częstsze niż próg 1-dniowy
   nie ma sensu; rzadsze niż istniejący `cleanup-orphan-jobs` (5 min), bo task
   jest tani, ale nie ma presji czasowej porównywalnej do sprzątania utkniętych
   jobów.
5. **Obsługa błędów:** `os.unlink` w obu mechanizmach opakowane w
   `try/except OSError` → `logger.warning`, bez przerywania. Nigdy nie zmienia
   statusu joba (usuwanie pliku to sprzątanie, nie część kontraktu transferu) i
   nigdy nie przerywa pętli retention taska po pojedynczym pliku (np. gdy
   dwa mechanizmy trafią w wyścig o ten sam plik — `FileNotFoundError` jest
   oczekiwanym, nie wyjątkowym przypadkiem).

## Komponenty i zmiany

| Warstwa | Plik | Zmiana |
|---|---|---|
| Settings | `services/web/config/settings/base.py` | `TRANSFERS_RETENTION_DAYS = config('TRANSFERS_RETENTION_DAYS', default=1, cast=int)` |
| Task | `services/worker/tasks.py` | w `execute_transfer`, po `job.mark_done()`: usunięcie `job.source_path` gdy `job.connection_id` i ścieżka pod `TRANSFERS_DIR` |
| Task | `services/worker/tasks.py` | nowy task `@app.task(name='transfers.cleanup_old_transfers')` — skanuje `TRANSFERS_DIR`, usuwa pliki z `mtime` starszym niż `TRANSFERS_RETENTION_DAYS` |
| Migracja | `services/web/apps/transfers/migrations/000X_transfers_retention_periodic_task.py` | `PeriodicTask` + `IntervalSchedule(every=1, period='hours')`, wzorowane na `0002_cleanup_periodic_task.py` |

## Przepływ i logika

### Usuwanie po sukcesie (`execute_transfer`)

```python
def _cleanup_source_file(job) -> None:
    if job.connection_id is None:
        return  # flow/relay — source_path na zdalnym hoście, nie dotykamy
    path = job.source_path
    if not path or not path.startswith(settings.TRANSFERS_DIR):
        return
    try:
        os.unlink(path)
    except OSError as e:
        logger.warning(f'Nie udało się usunąć {path} po transferze: {e}')
```

Wywołanie: bezpośrednio po `job.mark_done()` w bloku `try` w `execute_transfer`
(przed `send_notification.delay(...)` — kolejność wobec powiadomień bez
znaczenia, ale sprzątanie logicznie kończy "udany transfer" przed
poinformowaniem o nim). Wywoływane wyłącznie w gałęzi sukcesu — `mark_failed`
nie usuwa niczego (plik zostaje do wglądu/retry, aż złapie go retention task).

### Retention task

```python
@app.task(name='transfers.cleanup_old_transfers')
def cleanup_old_transfers():
    import time
    cutoff = time.time() - settings.TRANSFERS_RETENTION_DAYS * 86400
    removed = 0
    for name in os.listdir(settings.TRANSFERS_DIR):
        path = os.path.join(settings.TRANSFERS_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.unlink(path)
                removed += 1
        except OSError as e:
            logger.warning(f'Retention: nie udało się usunąć {path}: {e}')
    logger.info(f'Retention: usunięto {removed} plików z {settings.TRANSFERS_DIR}')
```

`os.path.isfile` filtruje ewentualne podkatalogi (dziś ich nie ma, ale
zabezpiecza przed przyszłą zmianą); pojedynczy błąd (`OSError`) nie przerywa
pętli po pozostałych plikach.

### Migracja periodic task

Analogiczna do `0002_cleanup_periodic_task.py`: `RunPython` tworzący/usuwający
`PeriodicTask(name='cleanup-old-transfers', task='transfers.cleanup_old_transfers')`
z nowym `IntervalSchedule(every=1, period='hours')` (albo reużycie istniejącego
`IntervalSchedule`, jeśli `get_or_create` trafi na identyczny — `every=1,
period='hours'` nie koliduje z istniejącym `every=5, period='minutes'`), owinięta
w `try/except Exception: pass` na wypadek braku tabel `django_celery_beat` przy
pierwszym `migrate` (spójne z istniejącym wzorcem).

## Testy (TDD)

### Worker — `test_tasks.py` (nowe testy dla `execute_transfer`)

- `test_deletes_source_file_after_success_when_connection_job` — plik istnieje
  przed, znika po `mark_done()`
- `test_does_not_delete_when_flow_job` — `job.flow_id` ustawiony → plik zostaje
  (mock na `os.unlink` niewywołany)
- `test_does_not_delete_path_outside_transfers_dir` — `source_path` spoza
  `TRANSFERS_DIR` (teoretyczny przypadek z API) → nie usuwany
- `test_success_survives_missing_file` — plik już nie istnieje (`FileNotFoundError`)
  → `mark_done()` i tak przechodzi, brak wyjątku propagowanego z taska
- `test_does_not_delete_on_failed_transfer` — gałąź `mark_failed` → `os.unlink`
  niewywołany

### Worker — `test_tasks.py` (nowa klasa `TestCleanupOldTransfers`)

- `test_removes_files_older_than_threshold` — plik z `mtime` przed cutoff → usunięty
- `test_keeps_files_newer_than_threshold` — plik świeży → zostaje
- `test_empty_directory_no_error` — pusty `/transfers` → brak wyjątku
- `test_single_file_error_does_not_abort_loop` — mock `os.unlink` rzuca
  `OSError` na jednym z dwóch plików → drugi i tak usunięty, log warning

### Web — migracja

- `migrate --check` czysty po dodaniu migracji (spójne z istniejącym testem dla
  `0002_cleanup_periodic_task.py`, jeśli istnieje — do potwierdzenia przy
  planie)

### Kolejność TDD

Czerwone testy `_cleanup_source_file` → implementacja → integracja w
`execute_transfer` → czerwone testy `cleanup_old_transfers` → implementacja →
migracja periodic task → pełny zestaw worker zielony przed commitem.

## Poza zakresem (YAGNI)

- Usuwanie po statusie `TransferJob` w bazie zamiast po wieku pliku na dysku
  (odrzucone — patrz Decyzja 2)
- Ochrona plików reużywanych wielokrotnie przez REST API trigger (świadomie
  zaakceptowane ryzyko — patrz Decyzja 1)
- Konfigurowalny interwał periodic taska przez `.env` (na razie stała wartość
  w migracji, jak istniejący `cleanup-orphan-jobs`)
- Zmiana zachowania `mark_failed`/`mark_cancelled` — nie dotykamy istniejącej
  logiki statusów, tylko dokładamy sprzątanie plików
