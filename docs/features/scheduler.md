# Scheduler — Harmonogram transferów

> Automatyczne uruchamianie transferów lub Flows według wyrażeń cron.

## Tworzenie harmonogramu

Panel → `[ NEW SCHEDULE ]`

| Pole                 | Opis                                                                |
|----------------------|---------------------------------------------------------------------|
| **CONNECTION**       | Połączenie SSH dla ręcznego transferu (ustaw albo to, albo Flow)    |
| **FLOW**             | Flow relay do uruchomienia (ustaw albo to, albo Connection)          |
| **SOURCE PATH**      | Ścieżka źródłowa (wymagana gdy wybrane Connection)                  |
| **DESTINATION PATH** | Ścieżka docelowa (wymagana gdy wybrane Connection)                  |
| **CRON EXPRESSION**  | Wyrażenie cron, np. `0 2 * * *`                                     |
| **ENABLED**          | Czy harmonogram jest aktywny                                        |

Walidacja wymusza wybranie dokładnie jednego: `CONNECTION` albo `FLOW`.

## Składnia wyrażeń CRON

```
┌─── minuta (0-59)
│ ┌─── godzina (0-23)
│ │ ┌─── dzień miesiąca (1-31)
│ │ │ ┌─── miesiąc (1-12)
│ │ │ │ ┌─── dzień tygodnia (0-7, 0 i 7 = niedziela)
│ │ │ │ │
* * * * *
```

| Wyrażenie     | Znaczenie                          |
|---------------|------------------------------------|
| `0 2 * * *`   | Codziennie o 02:00                 |
| `*/15 * * * *`| Co 15 minut                        |
| `0 8 * * 1-5` | Poniedziałek–Piątek o 08:00        |
| `0 0 1 * *`   | Pierwszy dzień miesiąca o północy  |
| `0 * * * *`   | Co godzinę, o pełnej               |

## Jak działa Celery Beat

1. Serwis `beat` co 5 minut sprawdza tabelę `ScheduledTransfer`
2. Dla każdego harmonogramu z `enabled=True` i `next_run <= now` tworzy `TransferJob` i wysyła do kolejki
3. Po uruchomieniu aktualizuje `last_run` i `next_run`
4. Beat resetuje zadania zawieszone w stanie `RUNNING` przez >1h — ochrona przed osieroconym zadaniem

## Strefa czasowa

Kontenery `beat` i `worker` działają w strefie `Europe/Warsaw` (konfiguracja przez `TZ=Europe/Warsaw` w `docker-compose.yml`). Wyrażenia cron interpretowane są w czasie polskim.

## Kod źródłowy

| Zasób          | Ścieżka                                             |
|----------------|-----------------------------------------------------|
| Model          | `services/web/apps/scheduler/models.py`             |
| Formularz      | `services/web/apps/scheduler/forms.py`              |
| Widoki         | `services/web/apps/scheduler/views.py`              |
| Beat task      | `services/web/apps/scheduler/tasks.py`              |
| Testy          | `services/web/apps/scheduler/tests/`                |
