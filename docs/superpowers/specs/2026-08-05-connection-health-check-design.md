# Health-check połączeń w tle — Design Spec

> Propozycja #26 z `Propozycje rozbudowy.md`. Cel: cykliczny, automatyczny test wszystkich zapisanych `Connection` (SSH/Postgres/MySQL/MSSQL), żeby wykryć zepsute hasło/klucz/certyfikat zanim zawiedzie zaplanowany transfer w nocy — zamiast dopiero po fakcie przez powiadomienie o nieudanym transferze.

## Zakres

**W zakresie:**
- Cykliczny task Celery sprawdzający **wszystkie** zapisane `Connection` (model nie ma pola `is_active` — sprawdzamy każde, YAGNI, bez nowego pola filtrującego).
- Częstotliwość: **co godzinę**, ta sama skala co istniejąca retencja `/transfers` (`cleanup-old-transfers`).
- Persystencja ostatniego wyniku na `Connection` (3 nowe pola).
- Powiadomienie **tylko przy zmianie stanu** (przejście w `failed` = nowy incydent, przejście `failed → ok` = odzyskanie) — nie przy każdym cyklicznym sprawdzeniu.
- Kanał powiadomień: reużycie istniejących flag właściciela połączenia (`notify_on_failed`, `webhook_on_failed`, `telegram_on_failed`) dla obu kierunków zmiany (failed i recovery).
- Minimalny badge statusu w liście Connections (UI), oparty wyłącznie o już zapisane pola.

**Poza zakresem:**
- Pole `is_active`/opt-in per połączenie — odrzucone w brainstormingu, sprawdzamy wszystko.
- Nowe dedykowane flagi powiadomień health-check na `User` — reużywamy `*_on_failed`.
- Wpis w `ConfigAuditLog` — health-check to zdarzenie runtime, nie zmiana konfiguracji; `ConfigAuditLog.action` (max_length=10, choices `created/updated/deleted`) semantycznie i technicznie do tego nie pasuje.
- Throttling/dedup poza "tylko przy zmianie stanu" (np. przypominanie co N godzin o wciąż zepsutym połączeniu) — YAGNI, można dodać później jeśli okaże się potrzebne.
- Równoległość/limity współbieżności ponad naturalną izolację Celery (patrz niżej) — brak dedykowanego limitu concurrency w tej iteracji.

## Model danych

Nowe pola na `apps.connections.models.Connection`:

| Pole | Typ | Domyślnie | Opis |
|------|-----|-----------|------|
| `health_status` | `CharField(max_length=10, choices=[('unknown','Unknown'),('ok','OK'),('failed','Failed')])` | `'unknown'` | Wynik ostatniego cyklu |
| `health_checked_at` | `DateTimeField(null=True, blank=True)` | `None` | Kiedy ostatnio sprawdzono |
| `health_error` | `TextField(blank=True, default='')` | `''` | Komunikat błędu z testera, gdy `failed`; puste gdy `ok` |

Brak osobnej tabeli historii — to prosty stan "na teraz", nie log. Migracja Django standardowa (`AddField` × 3) w `apps/connections/migrations/`.

## Architektura Celery

Dwa nowe taski w `services/worker/tasks.py` (health-check dzieli moduł z resztą tasków workera, tak jak `cleanup_orphan_jobs`/`cleanup_old_transfers`):

```python
@app.task(name='connections.health_check_all')
def health_check_all():
    for connection_id in Connection.objects.values_list('pk', flat=True):
        health_check_one.delay(connection_id)

@app.task(bind=True, name='connections.health_check_one', max_retries=0)
def health_check_one(self, connection_id: int):
    ...
```

**Dlaczego parent+child, nie jedna pętla:** każdy tester ma własny timeout 10s (`ssh_tester`/`pg_tester`/`mysql_tester`/`mssql_tester`, patrz niżej), ale sieciowe zawieszenie (np. `socket.timeout` niepoprawnie obsłużony przez sterownik DB) w jednym połączeniu nie może zablokować sprawdzenia pozostałych. Dispatch przez `.delay()` daje naturalną izolację przez Celery — taki sam wzorzec jak transfery (jeden `TransferJob` = jeden task).

`health_check_one`:
1. Pobiera `Connection` po `connection_id` (jeśli nie istnieje — log i return, wzorem `send_notification`/`send_webhook`).
2. Dispatch po `connection.kind` do właściwego testera (import bezpośrednio z `apps.connections.ssh_tester`, `pg_tester`, `mysql_tester`, `mssql_tester` — te same funkcje, których używa dziś widok `connection_test`, żaden duplikat logiki). Sygnatura każdego testera: `test_connection(connection) -> Result` gdzie `Result` to dataclass `{success: bool, message: str}`.
3. Oblicza `new_status = 'ok' if result.success else 'failed'`.
4. Zapamiętuje `old_status = connection.health_status` **przed** update.
5. Zapisuje `connection.health_status`, `connection.health_checked_at = timezone.now()`, `connection.health_error = '' if result.success else result.message`.
6. Jeśli `old_status != 'failed' and new_status == 'failed'` **lub** `old_status == 'failed' and new_status == 'ok'` → dispatch powiadomień (patrz niżej). Pierwsze przejście `unknown → ok` nic nie wysyła.

**Rejestracja `PeriodicTask`** — data migration w `apps/connections/migrations/`, wzorem `apps/transfers/migrations/0005_transfers_retention_periodic_task.py`: `IntervalSchedule(every=1, period='hours')`, `PeriodicTask(name='connection-health-check', task='connections.health_check_all', enabled=True)`, `try/except Exception: pass` (`nosec B110`, tabele `django_celery_beat` mogą nie istnieć przy pierwszym `migrate`), `reverse` usuwający `PeriodicTask` po nazwie.

## Powiadomienia

Trzy nowe funkcje w `services/worker/notifications.py`, obok istniejących `send_email_notification(job)`/`send_telegram_notification(job)`/`send_webhook_notification(job)` — analogiczny wzorzec, ale przyjmują `connection` i `status` zamiast `job`:

```python
def send_connection_health_email(connection, status: str) -> bool:
    user = connection.owner
    if not user.email or not user.notify_on_failed:
        return False
    ...

def send_connection_health_telegram(connection, status: str) -> bool:
    user = connection.owner
    if not user.telegram_chat_id or not user.telegram_on_failed:
        return False
    ...

def send_connection_health_webhook(connection, status: str) -> bool:
    user = connection.owner
    if not user.webhook_url or not user.webhook_on_failed:
        return False
    ...
```

`status` to `'failed'` lub `'ok'` (odzyskanie) — obie ścieżki bramkowane tą samą flagą `*_on_failed` (jeden przełącznik "powiadamiaj o problemach z tym połączeniem", zgodnie z decyzją z brainstormingu — brak nowych flag na `User`).

**Nowe szablony** (wzorem `notifications/transfer_{status}.txt/html`):
- `notifications/connection_health_failed.txt` / `.html`
- `notifications/connection_health_recovered.txt` / `.html`

Kontekst szablonu: `{'connection': connection, 'error': connection.health_error}` (error pusty przy recovery).

**Webhook — reużycie circuit breakera**: `send_connection_health_webhook` respektuje `circuit_is_open(user)` i woła `record_success`/`record_failure` z `apps.webhook_deliveries.services` — to ten sam endpoint użytkownika co dla powiadomień transferowych, więc dzielenie circuit breakera jest poprawne (jeśli endpoint użytkownika jest down, health-check webhook nie powinien próbować obchodzić otwartego obwodu). Zapis do `WebhookDeliveryLog` z `job=None` (pole już nullable — `on_delete=models.SET_NULL, null=True`), `url=user.webhook_url`.

**Dispatch z `health_check_one`** (po kroku 6 powyżej, analogicznie do `execute_transfer`):
```python
if <przejście wymaga powiadomienia>:
    send_connection_health_notification.delay(connection.pk, new_status)
```
Jeden nowy task `connections.send_health_notification(connection_id, status)` wywołujący wszystkie trzy funkcje (email/telegram/webhook) — wzorem jak `execute_transfer` woła trzy osobne `.delay()`, ale tu wystarczy jeden zbiorczy task, bo (w przeciwieństwie do transferów) nie ma potrzeby osobnego retry per kanał — health-check i tak powtórzy się za godzinę.

## UI

W szablonie listy Connections (`connections/list.html` lub odpowiednik) — badge obok każdego połączenia:
- `unknown` → szary, brak tekstu poza "brak danych"
- `ok` → zielony, `health_checked_at` sformatowane
- `failed` → czerwony, `health_checked_at` + skrócony `health_error` (title/tooltip na pełny tekst)

Zero dodatkowych zapytań — pola są już na obiekcie `Connection` pobieranym przez istniejący widok listy.

## Testowanie

- Unit testy dla `health_check_one`: sukces (status→ok, brak powiadomienia gdy `unknown→ok`), pierwsza awaria (`unknown→failed`, powiadomienie wysłane), utrzymująca się awaria (`failed→failed`, **brak** powiadomienia), odzyskanie (`failed→ok`, powiadomienie wysłane), połączenie nieistniejące (graceful no-op).
- Unit testy dla trzech `send_connection_health_*` — analogiczne do istniejących testów `send_email_notification`/`send_webhook_notification`/`send_telegram_notification` (flaga wyłączona → `False`/brak wysyłki; circuit breaker otwarty → webhook pominięty).
- Rejestracja `PeriodicTask` przez migrację — bez dedykowanego testu, zgodnie z istniejącą praktyką w projekcie (`cleanup-orphan-jobs`/`cleanup-old-transfers` też nie mają testów migracji).
- UI: test że badge renderuje się poprawnie dla trzech stanów (test widoku sprawdzający obecność klasy CSS/tekstu w response).

## Global Constraints

- Timeout testera: 10s (już ustalone w `ssh_tester`/`pg_tester`/`mysql_tester`/`mssql_tester` — bez zmian).
- Częstotliwość cyklu: co 1 godzinę (`IntervalSchedule(every=1, period='hours')`).
- Brak nowego pola `is_active` na `Connection` — health-check obejmuje wszystkie połączenia.
- Powiadomienia bramkowane wyłącznie istniejącymi flagami `notify_on_failed`/`webhook_on_failed`/`telegram_on_failed` — brak nowych pól na `User`.
- Powiadomienie wysyłane wyłącznie przy zmianie stanu (`→failed` z dowolnego stanu ≠ `failed`, oraz `failed→ok`) — nigdy przy powtórnym potwierdzeniu tego samego stanu.
- `ConfigAuditLog` pozostaje nietknięty — health-check nie pisze tam wpisów.
- Wszystkie nowe taski Celery żyją w `services/worker/tasks.py`, testery importowane bezpośrednio z `apps.connections.*_tester` (bez duplikacji logiki testującej).
