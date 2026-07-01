# System ról ORG (Admin / Operator / Read-only) + Stop transferu — Design

**Data:** 2026-07-01
**Status:** zatwierdzony

## Cel

Wprowadzić kontrolę dostępu opartą o role w obrębie jednej wspólnej organizacji
(cała instalacja = jeden zespół, bez multi-tenancy):

- **Admin** — pełny dostęp: konfiguracja (Connections/Flows/Scheduler/role userów)
  + operowanie (uruchamianie/zatrzymywanie transferów) + podgląd.
- **Operator** — może uruchamiać i zatrzymywać transfery na istniejącej
  konfiguracji, ale nie może tworzyć/edytować/usuwać Connections, Flows,
  ScheduledTransfer ani zarządzać rolami innych userów.
- **Read-only** — wyłącznie podgląd (dashboard, listy, logi transferów), bez
  żadnej akcji.

Przy okazji: dziś **nie istnieje żadna funkcja zatrzymania trwającego
transferu** (`TransferJob.celery_task_id` jest zapisywany, ale nic go nie
`revoke`'uje) — Operator wymaga tej funkcji, więc powstaje jako nowa
funkcjonalność w ramach tego samego spec.

## Kontekst obecny

- `User.role` już istnieje: `ROLE_CHOICES = [('admin', 'Admin'), ('user', 'User')]`,
  używane w jednym miejscu (`accounts/views.py:users_list`, gate na `is_admin`).
- `users/list.html` to dziś czysty podgląd — brak akcji zmiany roli.
- `Connection`, `Flow`, `ScheduledTransfer`, `TransferJob` mają pole
  `owner = ForeignKey(User)` i **wszystkie** widoki filtrują ściśle
  `owner=request.user` (`connections/views.py`, `flows` odpowiednik,
  `scheduler/views.py`, `transfers/views.py`, `dashboard/views.py`) — zero
  współdzielenia między userami.
- Worker Celery działa w domyślnej puli `prefork`, `--concurrency=4`
  (`services/worker/Dockerfile`) — `celery.control.revoke(id, terminate=True)`
  wysyła SIGTERM do procesu wykonującego task, co realnie przerywa transfer.
- REST API (`apps/api/views.py`, `require_api_token`) autoryzuje przez
  `ApiToken` → `request.api_user`, dziś też filtrowane po ownerze zasobu.

## Decyzje (zatwierdzone)

1. **Jedna wspólna organizacja** — bez modelu `Organization`/`Membership`.
   Multi-tenant odrzucony jako przedwczesna komplikacja (YAGNI) przy jednym
   zespole.
2. **Connections/Flows/ScheduledTransfer/TransferJob stają się widoczne dla
   całego zespołu** — `owner` zostaje wyłącznie jako pole audytowe ("kto
   utworzył"), przestaje być filtrem widoczności czy uprawnień.
3. **Scheduler (ScheduledTransfer CRUD) to konfiguracja — tylko Admin.**
   Operator nie tworzy/edytuje harmonogramów, może jedynie ręcznie odpalić
   istniejący (`run now`) i zatrzymać trwający transfer.
4. **Hierarchia ról jest liniowa**: `readonly (0) < operator (1) < admin (2)`.
   Brak macierzy uprawnień per-akcja — jeden poziom wystarcza do wszystkich
   decyzji autoryzacyjnych w tym spec.
5. **Migracja istniejących userów**: `admin` → `admin` (bez zmian),
   `user` → `operator` (bezpieczny domyślny — obecni "zwykli" userzy już
   uruchamiają transfery, degradacja do `readonly` byłaby regresją
   funkcjonalną).
6. **Stop transferu**: znane ograniczenie — `SIGTERM` może przerwać transfer
   w połowie pliku (analogiczne ryzyko do awarii sieci w trakcie transferu,
   już zaakceptowane jako dług przy funkcji uploadu). Nie wprowadzamy nowej
   klasy ryzyka, tylko nowy sposób jego wywołania.

## Architektura zmian

### 1. `apps/accounts/models.py`
```python
ROLE_ADMIN    = 'admin'
ROLE_OPERATOR = 'operator'
ROLE_READONLY = 'readonly'
ROLE_CHOICES  = [(ROLE_ADMIN, 'Admin'), (ROLE_OPERATOR, 'Operator'), (ROLE_READONLY, 'Read-only')]
ROLE_LEVEL    = {ROLE_READONLY: 0, ROLE_OPERATOR: 1, ROLE_ADMIN: 2}

class User(AbstractUser):
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_OPERATOR)
    ...
    @property
    def role_level(self) -> int:
        return ROLE_LEVEL[self.role]

    @property
    def is_admin(self) -> bool:        # bez zmian sygnatury — istniejące call sites działają
        return self.role == ROLE_ADMIN

    @property
    def can_operate(self) -> bool:
        return self.role_level >= ROLE_LEVEL[ROLE_OPERATOR]
```

Migracja danych (`RunPython`): `User.objects.filter(role='user').update(role='operator')`
przed zmianą `choices` (żeby nie zostawić rekordów z nieistniejącą wartością).

### 2. `apps/accounts/permissions.py` (nowy plik)
```python
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from .models import ROLE_LEVEL

def require_role(min_role):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if request.user.role_level < ROLE_LEVEL[min_role]:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
```

Użycie w widokach: `@require_role(ROLE_READONLY)` (= zalogowany, jawne dla
czytelności), `@require_role(ROLE_OPERATOR)`, `@require_role(ROLE_ADMIN)`.

### 3. `apps/connections/views.py`, `apps/flows/*`, `apps/scheduler/views.py`
- Listy: `Connection.objects.all()` / `Flow.objects.all()` /
  `ScheduledTransfer.objects.all()` zamiast `.filter(owner=request.user)`.
- Detal/edycja/usuwanie: `get_object_or_404(Model, pk=pk)` bez `owner=`.
- Dekoratory: podgląd → `@require_role(ROLE_READONLY)`; create/update/delete →
  `@require_role(ROLE_ADMIN)`.
- `owner` przy tworzeniu nadal ustawiany na `request.user` (audyt).

### 4. `apps/transfers/views.py`, `apps/transfers/models.py`
- `TransferJob.objects.all()` zamiast `.filter(owner=request.user)` w liście i
  detalu (log widoku).
- `transfer_create` (Transfer Now), `flow_run` → `@require_role(ROLE_OPERATOR)`.
- Nowa wartość statusu:
  ```python
  STATUS_CANCELLED = 'cancelled'
  STATUS_CHOICES += [(STATUS_CANCELLED, 'CANCELLED')]
  ```
- Nowe pole: `cancelled_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='cancelled_jobs')`.
- Nowa metoda modelu:
  ```python
  def mark_cancelled(self, by) -> None:
      self.status = STATUS_CANCELLED
      self.cancelled_by = by
      self.finished_at = timezone.now()
      self.save(update_fields=['status', 'cancelled_by', 'finished_at'])
  ```
- Nowy widok:
  ```python
  @require_role(ROLE_OPERATOR)
  @require_POST
  def transfer_stop(request, pk):
      job = get_object_or_404(TransferJob, pk=pk)
      if job.status not in (STATUS_PENDING, STATUS_RUNNING):
          messages.error(request, 'Transfer nie jest aktywny.')
          return redirect(...)
      if job.celery_task_id:
          current_app.control.revoke(job.celery_task_id, terminate=True, signal='SIGTERM')
      job.mark_cancelled(by=request.user)
      messages.success(request, 'Transfer zatrzymany.')
      return redirect(...)
  ```
  URL: `POST /transfers/<pk>/stop/`.

### 5. `apps/dashboard/stats.py`, `apps/dashboard/views.py`
- Usunąć filtr `owner=request.user` z `TransferJob.objects.filter(...)` — statystyki
  liczone dla całego zespołu.
- `success_rate`: `cancelled` traktowany neutralnie jak `pending`/`running`
  (poza mianownikiem `done + failed`) — zatrzymanie ręczne nie jest porażką
  transferu.
- Nagłówki KPI w `dashboard.html`: "Transfery zespołu" zamiast sugerowania
  danych osobistych.

### 6. `apps/api/views.py`, `apps/api/auth.py`
- `require_api_token` dodatkowo wystawia `request.api_user.role_level`.
- Endpointy trigger (`trigger/connection/<id>/`, `trigger/flow/<id>/`) —
  wymagają `role_level >= ROLE_OPERATOR`, zwracają `403` z JSON-owym błędem
  zamiast Django `PermissionDenied` (spójnie z resztą API, które już zwraca
  JSON error responses).
- `Connection`/`Flow` lookup bez filtra `owner=` (współdzielona pula).

### 7. `apps/accounts/views.py`, `templates/users/list.html`
- Nowy widok `change_user_role`:
  ```python
  @require_role(ROLE_ADMIN)
  @require_POST
  def change_user_role(request, pk):
      target = get_object_or_404(User, pk=pk)
      new_role = request.POST.get('role')
      if new_role not in dict(ROLE_CHOICES):
          messages.error(request, 'Nieprawidłowa rola.')
          return redirect('accounts:users')
      if target.role == ROLE_ADMIN and new_role != ROLE_ADMIN:
          if User.objects.filter(role=ROLE_ADMIN).exclude(pk=target.pk).count() == 0:
              messages.error(request, 'Nie można odebrać roli Admin ostatniemu administratorowi.')
              return redirect('accounts:users')
      target.role = new_role
      target.save(update_fields=['role'])
      messages.success(request, f'Rola {target.username} zmieniona na {new_role}.')
      return redirect('accounts:users')
  ```
  URL: `POST /accounts/users/<pk>/role/`.
- `users/list.html` — select z rolą + przycisk `[ZAPISZ]` per wiersz (form POST),
  widoczne tylko gdy `request.user.is_admin` (już gated na poziomie widoku
  `users_list`, więc szablon zawsze renderuje się dla Admina).

### 8. Szablony — ukrywanie akcji per rola
- `connections/list.html`, `flows/list.html`, `scheduler/list.html`:
  przyciski `+ NOWY` / `EDYTUJ` / `USUŃ` owinięte w
  `{% if user.is_admin %}`; dodana kolumna `UTWORZYŁ` (`{{ obj.owner.username }}`).
- `transfers/create.html`, widok Flow run: dostępne tylko gdy
  `{% if user.can_operate %}` (odsłaniamy formularz, nie tylko disable).
- Lista transferów / detal joba: przycisk `[STOP]` gdy
  `{% if job.status == 'running' and user.can_operate %}`.
- `base.html` navbar: odznaka roli obok nazwy usera, kolor spójny z istniejącym
  stylem z `users/list.html` (amber=Admin, green=Operator, przygaszony=Read-only).

## Obsługa błędów

| Sytuacja | Zachowanie |
|----------|-----------|
| Read-only próbuje POST na widok configu/operacji | `403 PermissionDenied` (Django domyślna strona/`require_role`) |
| Operator próbuje edytować Connection/Flow/Scheduler (ręczny POST, ominięcie UI) | `403 PermissionDenied` |
| Admin odbiera sobie rolę Admin jako ostatniemu administratorowi | Błąd walidacji, rola bez zmian |
| Stop na jobie, który już się zakończył (race: done/failed zanim POST doszedł) | Komunikat "Transfer nie jest aktywny", brak `revoke` |
| `revoke(terminate=True)` na tasku, który już zdążył się zakończyć | Celery no-op (bezpieczne, task już nie istnieje) |
| API token usera z rolą `readonly` wywołuje `trigger/connection/` | `403` JSON error |

## Testy

**`apps/accounts`:**
- `role_level`, `is_admin`, `can_operate` dla każdej roli
- `require_role` — 403 dla niewystarczającej roli, przejście dla wystarczającej
- `change_user_role` — zmiana roli, blokada usunięcia ostatniego Admina, 403 dla nie-Admina

**`apps/connections`, `apps/flows`, `apps/scheduler` (regresja + nowe):**
- Odwrócenie istniejących testów "user B nie widzi connection usera A" →
  "user B widzi connection usera A" (świadoma zmiana kontraktu, nie bug)
- Nowe: Operator dostaje 403 na create/update/delete; Read-only dostaje 403 na
  wszystkie akcje poza GET listy/detalu

**`apps/transfers`:**
- `mark_cancelled` ustawia status/`cancelled_by`/`finished_at`
- `transfer_stop`: mock `current_app.control.revoke`, weryfikacja wywołania z
  poprawnym `task_id` i `terminate=True`; 403 dla Read-only; no-op + komunikat
  gdy job nie jest aktywny

**`apps/dashboard`:**
- Statystyki liczone ze wszystkich jobów (nie tylko `request.user`)
- `cancelled` wykluczony z `success_rate`

**`apps/api`:**
- Trigger endpoint zwraca 403 dla tokena usera z rolą `readonly`

**Migracja danych:**
- Test migracji: `role='user'` → `role='operator'` po `migrate`

## Poza zakresem

- Multi-tenant / wiele organizacji — odrzucone (decyzja #1).
- Granularne udostępnianie per-zasób (np. "ten Connection widoczny tylko dla
  wybranych userów") — cała pula jest wspólna dla wszystkich, bez wyjątków.
- Self-service rejestracja z wyborem roli — konta nadal tworzone przez Admina/CLI,
  zmienia się tylko możliwość zmiany roli istniejącego usera.
- Audit log zmian konfiguracji (kto edytował Connection kiedy) — osobny temat
  z listy propozycji rozbudowy (#13), nie wchodzi w ten spec.
- Gwarancja atomowego stopu bez ryzyka częściowego pliku — udokumentowane jako
  zaakceptowane ograniczenie (decyzja #6), nie rozwiązywane w tym spec.
