# Logs — Historia i logi transferów

> Przeglądanie historii zadań transferu i live logów w czasie rzeczywistym.

## Lista transferów

Panel główny wyświetla tabelę `TransferJob` zalogowanego użytkownika:

| Kolumna         | Opis                                              |
|-----------------|---------------------------------------------------|
| **ID**          | Numer zadania                                     |
| **CONNECTION**  | Nazwa połączenia lub `RELAY: NazwaFlow`           |
| **SOURCE**      | Ścieżka źródłowa                                  |
| **DESTINATION** | Ścieżka docelowa                                  |
| **STATUS**      | `PENDING` / `RUNNING` / `DONE` / `FAILED`        |
| **CREATED**     | Czas zlecenia transferu                           |

Każdy użytkownik widzi wyłącznie swoje własne transfery (owner isolation).

## Szczegóły transferu — live logi

Kliknięcie `[ VIEW ]` otwiera widok szczegółowy z logami:

- Logi odświeżane co **2 sekundy** przez HTMX (`hx-trigger="every 2s"`)
- Odświeżanie zatrzymuje się gdy status = `DONE` lub `FAILED`
- Każdy wpis ma: `timestamp`, `level`, `message`

## Poziomy logów

| Poziom    | Znaczenie                                                       |
|-----------|-----------------------------------------------------------------|
| `info`    | Normalny przebieg — start transferu, postęp, zakończenie       |
| `warning` | Ostrzeżenie — np. brak klucza hosta (MITM warning)             |
| `error`   | Błąd — szczegóły wyjątku GPG/SFTP/rsync, kod błędu             |

## Przykładowe logi

Udany transfer z GPG:

```
[10:15:01] Transfer started: /transfers/backup.tar.gz → srv2:/backup/
[10:15:01] GPG: szyfrowanie pliku...
[10:15:02] GPG: ok → /tmp/backup_abc123.gpg
[10:15:02] SFTP: łączenie z 192.168.1.10:22...
[10:15:02] SFTP: połączono jako user
[10:15:03] SFTP: transfer zakończony (1.2 MB)
[10:15:03] Transfer DONE
```

Błąd GPG:

```
[10:20:05] GPG: szyfrowanie pliku...
[10:20:05] GPG FAILED — gpg: bad passphrase
[10:20:05] Transfer FAILED
```

## Model danych

```python
# TransferJob — meta zadania transferu
class TransferJob(models.Model):
    owner            # FK → User
    connection       # FK → Connection
    source_path      # str
    destination_path # str
    status           # PENDING | RUNNING | DONE | FAILED
    created_at, started_at, finished_at

# TransferLog — pojedyncza linia logu
class TransferLog(models.Model):
    job        # FK → TransferJob
    level      # 'info' | 'warning' | 'error'
    message    # str
    created_at # datetime
```

## Fragment endpoint (HTMX)

```
GET /transfers/<job_id>/log-fragment/
```

Zwraca HTML z listą `TransferLog` dla danego zadania.

## Kod źródłowy

| Zasób           | Ścieżka                                                   |
|-----------------|-----------------------------------------------------------|
| Modele          | `services/web/apps/transfers/models.py`                   |
| Fragment view   | `services/web/apps/transfers/views.py` — `log_fragment`   |
| Template        | `services/web/templates/transfers/log_fragment.html`      |
| Testy           | `services/web/apps/transfers/tests/test_views.py`         |
