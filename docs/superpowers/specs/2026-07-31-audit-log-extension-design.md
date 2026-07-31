# Rozszerzenie audit logu poza Connection/Flow — Design

**Propozycja:** #29 z `Propozycje rozbudowy.md` (vault Obsidian).

## Cel

`ConfigAuditLog` (#19, `apps.audit_log`) dziś rejestruje zmiany tylko dla `Connection`, `Flow` i `MaskingRule` (#25). W środowisku wieloosobowym z modelem ról ORG (#13) Admin ma szerokie uprawnienia nad kontami innych userów i nad harmonogramem transferów, a te zmiany nie zostawiają żadnego śladu. Cel: rozszerzyć istniejący audit log o `User` i `ScheduledTransfer`, bez zmiany architektury audytu.

## Zakres

**W zakresie:**
- `User` (`apps.accounts`):
  - `user_create` → utworzenie konta
  - `change_user_role` → zmiana pola `role`
- `ScheduledTransfer` (`apps.scheduler`):
  - `schedule_create` → utworzenie harmonogramu
  - `schedule_edit` → zmiana `flow`/`cron_expr`/`enabled`
  - `schedule_toggle` → włączenie/wyłączenie (traktowane jako zmiana `enabled`)
  - `schedule_delete` → usunięcie harmonogramu

**Poza zakresem (świadomie):**
- Usuwanie kont użytkowników — taki widok/endpoint dziś nie istnieje w aplikacji. Dodanie go to osobna funkcja, nie część rozszerzenia audytu. Gdy powstanie, zalogowanie go (`log_deleted`) będzie jednowierszową zmianą korzystającą z tego samego mechanizmu.
- `Organization` (ustawienia całej instancji) — pojedynczy, rzadko zmieniany widok, świadomie odłożony poza tę iterację (YAGNI).
- `ApiToken` (generate/revoke) — samoobsługowe tokeny właściciela konta, inna kategoria niż nadzór Admina nad cudzymi zasobami.

## Architektura

Zero zmian w `apps.audit_log` (model, `services.py`, szablon listy). Rozszerzenie polega wyłącznie na dopisaniu wywołań istniejącego serwisu w dwóch widokach — dokładnie ten sam wzorzec co dla `Connection`/`Flow`/`MaskingRule`:

- Jawne wywołania `log_created` / `log_updated` / `log_deleted` w widokach (nie sygnały `post_save`/`post_delete`) — spójne z decyzją podjętą w #19: sygnały wymagałyby dodatkowego mechanizmu przekazania `request.user` (threadlocals/middleware), a projekt świadomie tego uniknął.
- `diff_fields(before, after, tracked_fields, secret_fields=None)` do budowy `changed_fields` przy edycjach. Żadne z pól `User`/`ScheduledTransfer` objętych logowaniem nie jest sekretem (`username`, `email`, `role`, `flow`, `cron_expr`, `enabled`) — `secret_fields` zostaje pusty/pominięty.
- `ConfigAuditLog.model_name` przyjmie wartości `'User'` i `'ScheduledTransfer'` (nazwa klasy, jak dla pozostałych modeli — `type(instance).__name__`). Szablon listy audytu jest już generyczny (renderuje `model_name`/`object_repr`/`changed_fields` bez rozgałęzień per-typ) — zero zmian w `templates/audit_log/list.html`.

## Komponenty i zmiany plików

### `services/web/apps/accounts/views.py`

- Import: dopisać `from apps.audit_log.services import log_created, log_updated, diff_fields` (obok istniejących importów).
- `user_create`: po `user = form.save()` dodać `log_created(request.user, user)`.
- `change_user_role`: przed `target.role = new_role` przechwycić stary stan (`old_role = target.role`), po `target.save(...)` wywołać `log_updated(request.user, target, {'role': [old_role, new_role]})` — bez `diff_fields`, bo to jedno pole i wartość już jest znana z walidacji; unika dodatkowego zapytania do bazy po `save()`.

`User(AbstractUser)` nie nadpisuje `__str__` — dziedziczy z `AbstractBaseUser.__str__()`, które zwraca `username`. Wystarczające jako `object_repr`, bez zmian w modelu.

### `services/web/apps/scheduler/views.py`

- Import: dopisać `from apps.audit_log.services import log_created, log_updated, log_deleted, diff_fields`.
- Stała modułowa: `SCHEDULE_TRACKED_FIELDS = ['flow', 'cron_expr', 'enabled']`.
- `schedule_create`: po `sched.save()` (i po `_sync_celery_beat`, żeby log nie blokował głównej ścieżki jeśli sync padnie — patrz Obsługa błędów) dodać `log_created(request.user, sched)`.
- `schedule_edit`: przed `form.save()` przechwycić `before = ScheduledTransfer.objects.get(pk=sched.pk)`, po zapisie `changes = diff_fields(before, sched, SCHEDULE_TRACKED_FIELDS)` i `log_updated(request.user, sched, changes)`.
- `schedule_toggle`: po `sched.save(update_fields=['enabled'])` dodać `log_updated(request.user, sched, {'enabled': [str(not sched.enabled), str(sched.enabled)]})` — ręcznie zbudowany diff (analogicznie do `change_user_role`), bo `not sched.enabled` już nie istnieje jako obiekt do porównania po toggle.
- `schedule_delete`: przed `_delete_celery_beat(sched)` / `sched.delete()` dodać `log_deleted(request.user, sched)` (wzorem `connection_delete` — log przed fizycznym usunięciem, żeby `object_repr` mógł jeszcze odczytać `sched.flow.name`).

`ScheduledTransfer.__str__` już zwraca `f'{flow_name}: {cron_expr}'` — czytelny `object_repr` bez zmian w modelu.

## Przepływ danych

Bez zmian względem istniejącego wzorca: widok → `log_*()` → `ConfigAuditLog.objects.create()` → zapis synchroniczny w tej samej transakcji HTTP co operacja na `User`/`ScheduledTransfer`. Odczyt: `/audit-log/` (Admin-only, bez zmian) pokazuje wszystkie typy razem w jednej chronologicznej liście, tak jak dziś miesza Connection/Flow/Masking.

## Obsługa błędów

- `log_created`/`log_updated`/`log_deleted` nie rzucają wyjątków w normalnym użyciu (proste `objects.create()`) — brak nowej obsługi błędów potrzebnej.
- `schedule_create`/`schedule_edit` wywołują `_sync_celery_beat(sched)`, które może teoretycznie rzucić (np. błędny `cron_expr` — choć ten jest już walidowany w `clean_cron_expr`). Log audytu ma być wywołany **po** `_sync_celery_beat`, żeby nie zostawić wpisu audytu dla harmonogramu, który finalnie nie został zsynchronizowany z Celery Beat — utrzymuje spójność: wpis audytu istnieje wtedy i tylko wtedy, gdy operacja faktycznie się powiodła end-to-end.
- `change_user_role` ma już logikę ochrony ostatniego Admina wewnątrz `transaction.atomic()` z wczesnym `return redirect(...)` przy błędzie walidacji — `log_updated` dopisujemy **po** `target.save(...)`, wewnątrz tego samego bloku, więc log nigdy nie powstanie dla odrzuconej zmiany roli.

## Testowanie

Rozszerzenie dwóch istniejących plików testowych, wzorem `apps/connections/tests/test_views.py` (assercje na `ConfigAuditLog.objects.filter(model_name=...)`):

- `apps/accounts/tests/test_views.py`: nowy test `test_user_create_logs_audit_entry` (sprawdza `model_name='User'`, `action='created'`), nowy test `test_change_user_role_logs_audit_entry` (sprawdza `changed_fields == {'role': [old, new]}`).
- `apps/scheduler/tests/test_views.py`: cztery nowe testy — `test_schedule_create_logs_audit_entry`, `test_schedule_edit_logs_audit_entry`, `test_schedule_toggle_logs_audit_entry`, `test_schedule_delete_logs_audit_entry` — każdy weryfikuje `model_name='ScheduledTransfer'` i odpowiednią `action`/`changed_fields`.
- Test regresyjny (wzorem #25 "bez reguł = identyczne zachowanie"): tu nie ma analogicznego trybu opcjonalnego do wyłączenia — audyt jest zawsze aktywny dla tych akcji, więc nie ma osobnego przypadku "audyt wyłączony" do przetestowania.
- Brak zmian w `apps/audit_log/tests/` — model i serwis nie są modyfikowane, istniejące testy `test_services.py`/`test_views.py` pozostają bez zmian i muszą dalej przechodzić.

## Global Constraints

- Model `ConfigAuditLog`, `services.py` (`log_created`/`log_updated`/`log_deleted`/`diff_fields`) i `templates/audit_log/list.html` pozostają **niezmienione** — to rozszerzenie punktów wywołania, nie zmiana mechanizmu.
- Logowanie wyłącznie przez jawne wywołania w widokach — żadnych sygnałów `post_save`/`post_delete`.
- Żadne pole `User`/`ScheduledTransfer` objęte logowaniem nie jest sekretem — `secret_fields` nie jest używane w tym zadaniu.
- Usuwanie kont użytkowników pozostaje poza zakresem — nie dodawać widoku `user_delete`.
- `Organization` i `ApiToken` pozostają poza zakresem tej iteracji.
