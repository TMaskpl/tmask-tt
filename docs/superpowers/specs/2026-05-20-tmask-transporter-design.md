# tmask-transporter — Design Spec

**Data:** 2026-05-20  
**Status:** Zatwierdzony  
**Autor:** Daniel Niemczok

---

## Cel projektu

Webowa aplikacja do przesyłania plików między systemami Linux, przeznaczona dla małych ekip. Użytkownik loguje się, konfiguruje połączenia SSH i uruchamia transfery manualnie lub według harmonogramu cron. Interfejs w stylu Terminal/CRT.

---

## Stack technologiczny

| Warstwa | Technologia |
|---|---|
| Backend | Python 3.12, Django 5.x |
| Baza danych | PostgreSQL 16 |
| Task queue / broker | Celery 5.x + Redis 7 |
| Transfer SFTP/SCP | Paramiko |
| Transfer rsync | subprocess (rsync przez SSH) |
| Szyfrowanie pól DB | django-encrypted-model-fields (Fernet AES-256) |
| Frontend | Django templates + HTMX (live updates bez pełnego SPA) |
| Reverse proxy | Nginx |
| Konteneryzacja | Docker + Docker Compose |

---

## Architektura kontenerów

```
tmask-transporter/
├── docker-compose.yml
├── .env.example
│
├── services/
│   ├── web/                    # Django app (Gunicorn)
│   │   ├── Dockerfile
│   │   ├── config/             # settings, urls, wsgi — tylko globalne
│   │   ├── apps/
│   │   │   ├── accounts/       # auth, role admin/user
│   │   │   ├── connections/    # konfiguracje hostów
│   │   │   ├── transfers/      # zadania transferu, historia, status
│   │   │   └── scheduler/      # cron jobs, harmonogram
│   │   └── requirements.txt
│   │
│   ├── worker/                 # Celery worker
│   │   ├── Dockerfile
│   │   ├── modules/
│   │   │   ├── sftp/           # moduł SFTP/SCP (Paramiko)
│   │   │   │   ├── config.py
│   │   │   │   └── handler.py
│   │   │   └── rsync/          # moduł rsync przez SSH
│   │   │       ├── config.py
│   │   │       └── handler.py
│   │   └── tasks.py
│   │
│   └── beat/                   # Celery Beat (scheduler)
│       └── Dockerfile
│
├── nginx/
│   └── nginx.conf
│
└── postgres/
    └── init.sql
```

**Kontenery:**

| Kontener | Rola | Port zewnętrzny |
|---|---|---|
| `web` | Django + Gunicorn | — (przez nginx) |
| `worker` | Celery worker | brak |
| `beat` | Celery Beat scheduler | brak |
| `redis` | Broker zadań | brak (wewnętrzny) |
| `postgres` | Baza danych | brak (wewnętrzny) |
| `nginx` | Reverse proxy | 80, 443 |

**Zasada modularności:** każdy moduł transferu (`sftp/`, `rsync/`) ma własne `config.py` i `handler.py`. Zmiana jednego modułu nie dotyka drugiego.

---

## Zmienne środowiskowe (.env)

Wszystkie sekrety i konfiguracja środowiskowa wyłącznie w `.env`. Nigdy nie commitować `.env` do repo.

```env
# Postgres
POSTGRES_DB=transporter
POSTGRES_USER=transporter
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql://transporter:changeme@postgres:5432/transporter

# Django
SECRET_KEY=change-me-in-production
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1

# Redis / Celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Szyfrowanie pól w DB (Fernet)
FIELD_ENCRYPTION_KEY=your-fernet-key-here

# Opcjonalne
SENTRY_DSN=
```

---

## Modele danych

```python
# apps/accounts/models.py
class User(AbstractUser):
    role = CharField(choices=['admin', 'user'])

# apps/connections/models.py
class Connection:
    owner        = ForeignKey(User)
    name         = CharField()
    host         = CharField()
    port         = IntegerField(default=22)
    username     = CharField()
    password     = EncryptedCharField(null=True)   # Fernet AES-256
    ssh_key      = EncryptedTextField(null=True)   # private key PEM
    protocol     = CharField(choices=['sftp', 'rsync'])
    compress     = BooleanField(default=False)
    encrypt      = BooleanField(default=False)
    strict_host_key_checking = BooleanField(default=True)
    known_host_key = TextField(null=True)          # fingerprint zapisany przy 1. połączeniu
    created_at   = DateTimeField(auto_now_add=True)

# apps/transfers/models.py
class TransferJob:
    owner            = ForeignKey(User)
    connection       = ForeignKey(Connection)
    source_path      = CharField()
    destination_path = CharField()
    status           = CharField(choices=['pending','running','done','failed'])
    celery_task_id   = CharField(null=True)
    created_at       = DateTimeField(auto_now_add=True)
    started_at       = DateTimeField(null=True)
    finished_at      = DateTimeField(null=True)
    error_message    = TextField(null=True)

class TransferLog:
    job       = ForeignKey(TransferJob)
    timestamp = DateTimeField()
    level     = CharField(choices=['info','warn','error'])
    message   = TextField()

# apps/scheduler/models.py
class ScheduledTransfer:
    owner            = ForeignKey(User)
    connection       = ForeignKey(Connection)
    source_path      = CharField()
    destination_path = CharField()
    cron_expr        = CharField()       # "0 2 * * *"
    enabled          = BooleanField(default=True)
    last_run         = DateTimeField(null=True)
    next_run         = DateTimeField(null=True)
```

---

## UI — styl Terminal/CRT

**Paleta:**
- Tło: `#0a0a0a`
- Tekst: `#33ff33` (fosforyzująca zieleń)
- Akcent: `#00ff41` (headers)
- Ostrzeżenie: `#ffb000` (bursztyn)
- Błąd: `#ff3333`
- Ramki: ASCII `─ │ ┌ ┐ └ ┘ ├ ┤`

**Font:** monospace (JetBrains Mono / Courier New)  
**Efekty CSS:** scanlines, text-shadow glow, blinkający cursor w polach input

### Ekrany

1. **Login** — pełnoekranowy terminal prompt, logo ASCII art
2. **Dashboard** — 4 karty statusu + ostatnie 5 jobów
3. **Connections** — tabela połączeń, formularz new/edit, przycisk `[TEST CONNECTION]`
4. **Transfer Now** — wybór połączenia, source/dest path, opcjonalny `[BROWSE]` (modal file browser), live log (HTMX polling co 2s)
5. **Scheduler** — tabela cron jobów, cron helper UI
6. **Logs** — historia transferów z filtrowaniem
7. **Users** *(admin only)* — zarządzanie kontami

### Uprawnienia

| Akcja | User | Admin |
|---|---|---|
| Swoje połączenia (CRUD) | ✅ | ✅ |
| Cudze połączenia | ❌ | ✅ read-only |
| Transfer manualny | ✅ (swoje) | ✅ (wszystkie) |
| Scheduler | ✅ (swoje) | ✅ (wszystkie) |
| Logi | ✅ (swoje) | ✅ (wszystkie) |
| Zarządzanie użytkownikami | ❌ | ✅ |

---

## Obsługa błędów

| Błąd | Reakcja | Komunikat użytkownika |
|---|---|---|
| Brak połączenia SSH | Retry 3x co 5s → `failed` | "CONNECTION TIMEOUT — host unreachable" |
| Błąd auth | Natychmiast `failed`, bez retry | "AUTH FAILED — check credentials" |
| Brak pliku źródłowego | Natychmiast `failed` | "SOURCE NOT FOUND: /path" |
| Brak miejsca na docelowym | Zatrzymaj → `failed` | "INSUFFICIENT SPACE ON DESTINATION" |
| Osierocony task (>1h w `running`) | Beat resetuje do `failed` co 5min | "TASK INTERRUPTED — retry?" |
| Błąd krytyczny Django | Custom 500 CRT-style page | "SYSTEM ERROR — contact admin" |

**Retry policy:** tylko błędy sieciowe — max 3 próby. Brak retry dla: auth failure, file not found, insufficient space.

---

## Bezpieczeństwo

- Hasła i klucze SSH szyfrowane Fernet (AES-256) w Postgres; klucz z `.env`
- Django session auth (HttpOnly + Secure cookies), CSRF na wszystkich formularzach
- Hasła użytkowników: bcrypt
- Izolacja danych: każde query filtruje po `owner=request.user`
- Worker Celery otrzymuje tylko serializowane parametry (nie obiekty ORM)
- Kontenery: tylko `nginx` ma porty zewnętrzne (80/443)
- SSH: `StrictHostKeyChecking=yes` domyślnie; known_hosts per-user w DB
- `encrypt=True`: dodatkowe szyfrowanie GPG AES-256 przed wysłaniem; hasło podawane per-transfer, nie zapisywane

---

## Moduły transferu

### sftp/config.py
```python
SFTP_TIMEOUT = 30          # sekundy
SFTP_MAX_RETRIES = 3
SFTP_RETRY_DELAY = 5       # sekundy między retry
```

### rsync/config.py
```python
RSYNC_BASE_FLAGS = ['-avz', '--progress']
RSYNC_COMPRESS_FLAG = '-z'   # dodawany gdy compress=True (nadmiarowy przy -avz, jawny)
RSYNC_TIMEOUT = 60
RSYNC_MAX_RETRIES = 3
```

---

## Decyzje projektowe

- **HTMX zamiast SPA** — live log i status bez budowania osobnego frontendu JS; wystarczający dla skali "mała ekipa"
- **Celery Beat w osobnym kontenerze** — crash Beat nie zatrzymuje workerów i odwrotnie
- **Encrypt = GPG per-transfer** — hasło nie jest zapisywane celowo; SSH tunnel już szyfruje transfer, GPG to opcjonalna warstwa dla archiwów
- **Brak publicznego API** — tylko sesja webowa; upraszcza auth i CSRF, zbędne REST API przy tej skali
