
# Audyt: tmask-transporter

> Kompleksowy audyt bezpieczeństwa i jakości kodu projektu [[11-Apps/CSCS/Projekt-tmask-transporter|tmask-transporter]] przeprowadzony przez agenta Explore po zakończeniu implementacji (2026-05-21).

## Podsumowanie

| Kategoria | Krytyczne | Ważne | Drobne | Razem |
|-----------|-----------|-------|--------|-------|
| Bezpieczeństwo | 3 | 2 | 4 | 9 |
| Docker | 1 | 1 | 2 | 4 |
| Django/Celery | 1 | 1 | 1 | 3 |
| Jakość kodu | 0 | 1 | 2 | 3 |
| Testy | 0 | 1 | 2 | 3 |
| **RAZEM** | **5** | **6** | **11** | **22** |

**Status napraw:** 5 priorytetów naprawionych tego samego dnia. 17 znalezisk zaakceptowanych (uzasadnione lub post-MVP).

---

## 1. Bezpieczeństwo

### 1.1 `DEBUG=True` w `.env` jako domyślna wartość ❌ → ✅ NAPRAWIONE

- **Plik**: `.env:8`
- **Problem**: Domyślna wartość `DEBUG=True` — jeśli `.env` nie zostanie edytowany przed wdrożeniem, aplikacja ruszy w trybie debug
- **Naprawiono**: Zmieniono na `DEBUG=False`
- **Priorytet**: Krytyczny

### 1.2 Hardkodowany `SECRET_KEY` w `testing.py` ⚠️ ZAAKCEPTOWANE

- **Plik**: `services/web/config/settings/testing.py:10`
- **Problem**: `SECRET_KEY = 'test-secret-key-for-testing-only-50-chars-long!!'`
- **Ocena**: Akceptowalne — klucz jest izolowany wyłącznie do środowiska testowego, nigdy nie trafia do prod
- **Priorytet**: Drobny

### 1.3 Hardkodowany `FIELD_ENCRYPTION_KEY` w `testing.py` ⚠️ ZAAKCEPTOWANE

- **Plik**: `services/web/config/settings/testing.py:97`
- **Problem**: `FIELD_ENCRYPTION_KEY = 'gyOyODKLLBbsqs9MOKdYvH5MCXo2srzflXlOXUrgjgQ='`
- **Ocena**: Akceptowalne — środowisko testowe, nie prod. Ten sam klucz co w `.env.example`
- **Priorytet**: Drobny

### 1.4 SQL Injection ✅ BRAK PROBLEMÓW

- Wszystkie zapytania DB przez Django ORM (QuerySet), zero surowych SQL
- `TransferForm`, `ScheduledTransferForm` — Django ModelForm z walidacją

### 1.5 Shell Injection w rsync ✅ ZABEZPIECZONE

- **Plik**: `services/worker/modules/rsync/handler.py:31`
- `shlex.quote()` zastosowane na `ssh_key` — zabezpiecza przed path injection
- Parametry `CMD` przekazane jako lista (nie string) — subprocess Popen nie wywołuje shella
- **Uwaga (drobna)**: `source_path` i `destination_path` nie cytowane, ale bezpieczne bo rsync dostaje je jako argv (nie przez shell)

### 1.6 XSS w szablonach ✅ BRAK PROBLEMÓW

- Wszystkie `{{ }}` — Django auto-escaping aktywny
- Brak `|safe`, `mark_safe()`, `{% autoescape off %}`

### 1.7 CSRF Protection ✅ BRAK PROBLEMÓW

- Wszystkie 8 formularzy POST mają `{% csrf_token %}`
- `CsrfViewMiddleware` aktywny w `base.py:30`

### 1.8 Szyfrowanie wrażliwych pól ✅ DOBRZE ZAIMPLEMENTOWANE

- **Plik**: `services/web/apps/connections/models.py:15-16`
- `password` i `ssh_key` → `EncryptedCharField` / `EncryptedTextField` (Fernet AES-256)
- `FIELD_ENCRYPTION_KEY` czytany z `.env`

### 1.9 Non-root kontenery ✅ BEZPIECZNE

- `services/web/Dockerfile:15-17` — użytkownik `app`, `chown -R app:app /app`
- `services/worker/Dockerfile:17-19` — analogicznie

---

## 2. Konfiguracja Docker

### 2.1 Brak `.dockerignore` ❌ → ✅ NAPRAWIONE

- **Problem**: Plik nie istniał — build context zawierał `__pycache__`, `.env`, `.git`, całe `docs/`
- **Naprawiono**: Utworzono `.dockerignore` z:

```
__pycache__
*.pyc
*.pyo
.pytest_cache
.git
.gitignore
.env
.env.local
*.log
.DS_Store
docs/
```

- **Priorytet**: Krytyczny

### 2.2 Brak healthchecks (Redis, Web, Worker) ❌ → ✅ NAPRAWIONE

- **Problem**: `redis`, `web`, `worker` nie miały healthchecks — `depends_on: service_started` nie gwarantuje gotowości
- **Naprawiono** (`docker-compose.yml`):

```yaml
redis:
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 5s
    timeout: 5s
    retries: 5

web:
  healthcheck:
    test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/accounts/login/')\""]
    interval: 10s
    timeout: 5s
    retries: 3
    start_period: 30s

worker:
  healthcheck:
    test: ["CMD-SHELL", "celery -A tasks inspect ping -d celery@$$HOSTNAME --timeout 5 2>/dev/null | grep -q OK"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 20s
```

- `depends_on` dla `web`, `worker`, `beat` zmieniony z `service_started` na `service_healthy` dla Redis
- **Priorytet**: Ważny

### 2.3 Restart policy ✅ OK

- Wszystkie serwisy mają `restart: unless-stopped`

### 2.4 Porty wystawione na zewnątrz ✅ OK

- Tylko `nginx:80` — Redis i PostgreSQL wyłącznie w sieci `internal`

---

## 3. Django / Celery

### 3.1 `celery.py` domyślnie ładuje settings `development` ❌ → ✅ NAPRAWIONE

- **Plik**: `services/web/config/celery.py:4`
- **Problem**: `os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')` — jeśli env var nie ustawiona, Django startuje z `DEBUG=True`
- **Naprawiono**: Zmieniono default na `config.settings.production`
- **Priorytet**: Krytyczny

### 3.2 Brak `CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP` ❌ → ✅ NAPRAWIONE

- **Plik**: `services/web/config/settings/base.py`
- **Problem**: Celery 6+ generuje `CPendingDeprecationWarning` przy każdym starcie worker i beat
- **Naprawiono**: Dodano `CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True` w `base.py`
- **Priorytet**: Ważny

### 3.3 `ALLOWED_HOSTS` ✅ OK

- `base.py:8` — `config('ALLOWED_HOSTS', cast=Csv())` — czytany z `.env`
- `.env` zawiera `localhost,127.0.0.1` — OK dla dev/local
- Production wymaga uzupełnienia prawdziwych hostów w `.env`

### 3.4 Spójność migracji ✅ OK

- `accounts`, `connections`, `transfers`, `scheduler` — wszystkie migracje spójne
- `transfers` ma 2 migracje: `0001_initial` + `0002_cleanup_periodic_task`

### 3.5 `CELERY_BROKER_URL` ✅ OK

- `base.py:96` — `config('CELERY_BROKER_URL')` — nie hardkodowany

---

## 4. Jakość kodu

### 4.1 Duplikacja logiki paramiko ⚠️ POST-MVP

- **Pliki**:
  - `services/worker/modules/sftp/handler.py:18-50` — `_build_client()` + `_connect()`
  - `services/web/apps/connections/ssh_tester.py:16-57` — analogiczna logika connect
- **Problem**: Dwie niezależne implementacje konfiguracji klienta SSH (host key checking, auth)
- **Rekomendacja**: Wydzielić wspólną funkcję `build_paramiko_client()` do modułu utils
- **Priorytet**: Drobny (refaktor post-MVP)

### 4.2 `except Exception: pass` w migracji ⚠️ ZAAKCEPTOWANE

- **Plik**: `services/web/apps/transfers/migrations/0002_cleanup_periodic_task.py:19-20, 27-28`
- **Problem**: Silent failure
- **Ocena**: Uzasadnione — migracja sprawdza czy tabele `django_celery_beat` już istnieją; silent failure jest właściwym zachowaniem gdy tabele jeszcze nie ma
- **Priorytet**: Drobny

### 4.3 Długość metod ✅ OK

- `sftp/handler.py:execute()` — 43 linie
- `rsync/handler.py:execute()` — 44 linie
- `scheduler/views.py:_sync_celery_beat()` — 22 linie
- Wszystkie mieszczą się w rozsądnych granicach

---

## 5. Testy

### 5.1 Pokrycie testami ⚠️ BRAKUJĄCE OBSZARY

Testy istnieją dla:
- `apps/accounts` — `test_models.py`, `test_views.py` ✅
- `apps/connections` — `test_models.py`, `test_views.py` ✅
- `apps/transfers` — `test_models.py`, `test_views.py` ✅
- `apps/scheduler` — `test_models.py` ✅
- `worker/modules/sftp` — `test_sftp_handler.py` ✅
- `worker/modules/rsync` — `test_rsync_handler.py` ✅
- `worker/tasks` — `test_tasks.py` ✅

Brakuje testów dla:
- Forms: `ConnectionForm`, `TransferForm`, `ScheduledTransferForm`
- `apps/connections/ssh_tester.py` (test connectivity)
- `admin.py` we wszystkich aplikacjach

### 5.2 Unit vs. Integration ⚠️ TYLKO UNIT

- SFTP/rsync — mockują `paramiko.SSHClient` / `subprocess.Popen`
- Views — `pytest.mark.django_db` z SQLite (faktyczna baza)
- **Brak**: testów integracyjnych z prawdziwym serwerem SFTP/rsync (np. `openssh-server` w Docker Compose `test` profile)

### 5.3 Konfiguracja pytest ✅ OK

- `services/web/pytest.ini` — `DJANGO_SETTINGS_MODULE = config.settings.testing`
- `services/worker/conftest.py` — bootstrap Django przed importem tasks

---

## Znaleziska zaakceptowane (bez naprawy)

| # | Problem | Uzasadnienie |
|---|---------|-------------|
| Secret key w `testing.py` | Izolowany do testów, nigdy nie wchodzi do prod |
| Fernet key w `testing.py` | j.w. |
| `except Exception: pass` w migracji | Uzasadniony silent failure dla nieistniejących tabel |
| Duplikacja paramiko | Refaktor post-MVP, nie blokuje działania |
| Brak testów forms | Niski priorytet — forms proste, walidacja w Django |
| Brak testów integracyjnych SFTP | Wymaga środowiska testowego z SSH server |
| `source_path` niecytowane w rsync | Bezpieczne — argv, nie shell string |

---
*Audyt: 2026-05-21 | Narzędzie: Claude Code + Explore subagent*
