# Flows — Relay transfery (SFTP→SFTP)

> Przepływ danych między dwoma zdalnymi hostami bez udziału lokalnego systemu plików.

## Czym jest Flow

Flow (przekierowanie) to konfiguracja dwóch połączeń SSH:

- **SOURCE** — skąd pobieramy plik (host + ścieżka źródłowa)
- **DESTINATION** — dokąd wysyłamy plik (host + ścieżka docelowa)

Worker pobiera plik ze źródła do tymczasowej lokalizacji, a następnie wysyła go do celu.  
Oba połączenia mogą używać różnych protokołów (SFTP, rsync) i różnych systemów uwierzytelniania.

## Tworzenie Flow

Panel → `[ NEW FLOW ]`

| Pole                       | Opis                                           |
|----------------------------|------------------------------------------------|
| **NAME**                   | Etykieta identyfikująca Flow                   |
| **SOURCE CONNECTION**      | Połączenie SSH skąd pobieramy                  |
| **SOURCE PATH**            | Ścieżka pliku/katalogu na źródłowym serwerze   |
| **DESTINATION CONNECTION** | Połączenie SSH dokąd wysyłamy                  |
| **DESTINATION PATH**       | Ścieżka docelowa na serwerze docelowym         |

Przyciski `[ BROWSE ]` przy polach ścieżek otwierają modal SFTP — przeglądanie zdalnego FS.

## Walidacja

Flow jest odrzucany gdy `source_conn == dest_conn` i `source_path == dest_path` (ten sam plik na tym samym serwerze).

## Uruchamianie Flow

### Manualnie

Z listy Flows kliknij `[ RUN ]` — tworzy `TransferJob` w trybie relay i wysyła do Celery.

### Przez REST API

```bash
curl -X POST http://localhost/api/transfers/trigger/flow/1/ \
     -H "Authorization: Token <twoj-token-api>"
# Odpowiedź: {"job_id": 42}
```

### Przez harmonogram

W [Scheduler](scheduler.md) utwórz harmonogram i wybierz Flow zamiast bezpośredniego połączenia.

## Bezpieczeństwo relay

- Worker pobiera plik do temp lokalizacji z uprawnieniami `600`
- Plik tymczasowy usuwany w bloku `finally` — nawet przy błędzie transferu docelowego
- Strict host key checking działa niezależnie dla source i destination connection

## Kod źródłowy

| Zasób          | Ścieżka                                          |
|----------------|--------------------------------------------------|
| Model          | `services/web/apps/flows/models.py` — `Flow`     |
| Widoki         | `services/web/apps/flows/views.py`               |
| Relay handler  | `services/worker/modules/relay/handler.py`       |
| Testy          | `services/web/apps/flows/tests/`                 |
| Testy relay    | `services/worker/tests/test_relay_handler.py`    |
