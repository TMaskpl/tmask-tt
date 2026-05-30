# CLAUDE.md — tmask-tt (tmask-transporter)

Webowa aplikacja Django do przesyłania plików między systemami Linux przez SSH (SFTP/rsync/relay).
Panel użytkownika, harmonogram cron, szyfrowanie Fernet AES-256, interfejs Terminal/CRT (fosforyzująca zieleń).

## Architektura serwisów

```
Browser → Nginx(:80) → web (Django+Gunicorn) → Postgres
                                              → Redis → worker (Celery)
                                                      → beat (Celery Beat)
```

| Serwis   | Rola                                              | Dockerfile            |
|----------|---------------------------------------------------|-----------------------|
| `web`    | Django 5.x + Gunicorn — UI, auth, API             | `services/web/`       |
| `beat`   | Celery Beat — harmonogram cron (`-A config`)      | `services/web/` ← tak samo jak web |
| `worker` | Celery worker — moduły SFTP/rsync/relay           | `services/worker/`    |
| `redis`  | Broker Celery (jedyny pośrednik)                  | `redis:7-alpine`      |
| `postgres` | PostgreSQL 17                                   | `postgres:17-alpine`  |
| `nginx`  | Reverse proxy — jedyny port zewnętrzny (:80)      | `nginx:stable-alpine` |

> `beat` używa `services/web/Dockerfile` (brak rsync/openssh/gnupg) i uruchamia `celery -A config beat` przez `config/celery.py`. Worker używa osobnego `services/worker/Dockerfile` z narzędziami SSH/rsync.

## Struktura projektu

```
services/
├── web/
│   ├── apps/
│   │   ├── accounts/     — auth, rejestracja, profil
│   │   ├── connections/  — konfiguracje SSH (host, login, hasło/klucz)
│   │   ├── transfers/    — TransferJob, TransferLog, widoki live-log
│   │   ├── scheduler/    — ScheduledTransfer + Celery Beat sync
│   │   └── flows/        — Flow (relay A→worker→B), CRUD + uruchamianie
│   ├── config/settings/
│   │   ├── base.py       — wspólne ustawienia
│   │   ├── production.py — serwer (DEBUG=False)
│   │   └── testing.py    — pytest (SQLite, hardkodowane klucze testowe)
│   └── templates/        — Django templates + HTMX (live log co 2s)
└── worker/
    ├── tasks.py           — execute_transfer + cleanup_orphan_jobs
    └── modules/
        ├── sftp/          — SFTPHandler (Paramiko, retry 3x)
        ├── rsync/         — RsyncHandler (subprocess, retry 3x)
        └── relay/         — RelayHandler (download A → BytesIO → upload B)
```

## Uruchamianie

```bash
# Pierwsze uruchomienie
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Wpisz wygenerowane klucze do .env, następnie:
docker compose up -d
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser

# Codzienne
docker compose up -d
docker compose logs -f web worker

# Po zmianie modeli
docker compose run --rm web python manage.py makemigrations
docker compose run --rm web python manage.py migrate

# Po zmianie frontendu lub Dockerfile — WYMAGANY rebuild
docker compose build web && docker compose up -d web
```

## Testy

```bash
# Web (225 testów)
docker compose run --rm web python -m pytest apps/ -v

# Worker (114 testów)
docker compose run --rm worker python -m pytest tests/ -v

# Konkretny test
docker compose run --rm web python -m pytest apps/connections/tests/test_views.py -v
```

Konfiguracja: `services/web/pytest.ini` → `DJANGO_SETTINGS_MODULE = config.settings.testing`

## Skan bezpieczeństwa — Trivy + SonarQube

Skrypt `Trivy/scan-trivy-sonar.sh` skanuje 6 obrazów Docker przez Trivy i importuje CVE do SonarQube jako external issues.

```bash
# Pełny pipeline (Trivy + SonarQube)
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
SONAR_TOKEN=<token> bash Trivy/scan-trivy-sonar.sh

# Tylko Trivy (bez SonarQube, nie wymaga tokenu)
bash Trivy/scan-trivy-sonar.sh --trivy-only

# Tylko SonarQube (używa istniejących raportów Trivy)
SONAR_TOKEN=<token> bash Trivy/scan-trivy-sonar.sh --sonar-only
```

**Token SonarQube** — zawsze przez `SONAR_TOKEN` env var, nigdy nie zapisuj do `sonar-project.properties`.

| Plik | Rola |
|------|------|
| `Trivy/scan-trivy-sonar.sh` | Główny skrypt pipeline |
| `Trivy/Dockerfile.{nginx,postgres,redis}` | Pliki referencyjne dla obrazów bazowych (potrzebne do indeksacji CVE w SonarQube) |
| `Trivy/sonar-trivy-tmask-tt-*.json` | Raporty SonarQube (generowane, nie commitowane) |
| `sonar-project.properties` | Konfiguracja SonarQube (`sonar.token=REPLACE_WITH_YOUR_SONARQUBE_TOKEN`) |

Obrazy do skanowania: `nginx:stable-alpine`, `tmask-tt-web`, `tmask-tt-beat`, `tmask-tt-worker`, `postgres:17-alpine`, `redis:7-alpine`.

> `tmask-tt-beat` builduje z `services/web/Dockerfile` — te same CVE co web. `tmask-tt-worker` builduje z `services/worker/Dockerfile` — dodatkowe pakiety rsync/openssh/gnupg.

## Kluczowe konwencje

### Bezpieczeństwo — absolutne zakazy
- `SECRET_KEY` i `FIELD_ENCRYPTION_KEY` **wyłącznie w `.env`** — nigdy w kodzie, nigdy w repozytorium
- Nigdy nie dodawać `DEBUG=True` do domyślnych ustawień (`celery.py` i `entrypoint.sh` domyślnie ładują `production`)
- Hasła SSH i klucze prywatne przechowywane jako `EncryptedCharField`/`EncryptedTextField` (Fernet AES-256)

### Izolacja użytkowników
- Każdy użytkownik widzi **tylko swoje** połączenia, transfery i flow — QuerySety zawsze filtrowane po `owner=request.user`

### Moduły transferu — niezależność
- `sftp/`, `rsync/`, `relay/` są izolowane — zmiana jednego nie dotyka pozostałych
- Każdy handler przyjmuje `params: dict` i opcjonalny `log_callback(level, message)`

### Worker a web — granica kontenerów
- `web` ma stub `@shared_task` — może wywołać `.delay()` bez importu kodu workera
- Worker kopiuje `services/web/config/` i `services/web/apps/` do swojego kontenera (patrz `services/worker/Dockerfile`)

### SSH/klucze
- Używaj `paramiko.PKey.from_private_key()` zamiast `RSAKey` — obsługuje Ed25519/ECDSA
- `shlex.quote()` na ścieżce `ssh_key` w rsync — zabezpieczenie przed shell injection

### Relay Flows (tryb relay)
- `Flow`: source_conn + source_path → dest_conn + dest_path
- `TransferJob.connection` i `ScheduledTransfer.connection` są nullable — dokładnie jeden z (`connection`, `flow`) musi być ustawiony
- `RelayHandler`: pobiera plik przez SFTP do `BytesIO` / `tempfile` (próg: `RELAY_STREAM_THRESHOLD = 100 MB`), następnie wgrywa na serwer docelowy

### Scheduler
- `Celery Beat` sprawdza co 5 minut osierocone zadania (>1h w stanie `running`) i resetuje je
- `ScheduledTransfer` synchronizuje się z `PeriodicTask` django-celery-beat przez `_sync_celery_beat()`

## Zmienne środowiskowe (`.env`)

| Zmienna | Opis |
|---------|------|
| `SECRET_KEY` | Django secret key |
| `FIELD_ENCRYPTION_KEY` | Klucz Fernet AES-256 do szyfrowania pól |
| `DEBUG` | `False` w prod, `True` tylko lokalnie dev |
| `ALLOWED_HOSTS` | Lista hostów (CSV) |
| `DATABASE_URL` | URL bazy Postgres |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` |

## Dokumentacja (Obsidian vault)

- `11-Apps/CSCS/tmask-transporter/Projekt-tmask-transporter.md` — architektura, decyzje, historia
- `11-Apps/CSCS/tmask-transporter/audyt/` — audyty bezpieczeństwa (DevSecOps, ZAP, Trivy)
- `11-Apps/CSCS/tmask-transporter/audyt/Projekt-tmask-transporter-Trivy-2026-05-30.md` — Trivy: 1859 CVE w 6 obrazach, 82 HIGH
- `11-Apps/CSCS/tmask-transporter/testy/Projekt-tmask-transporter-Testy.md` — historia wyników testów
- `08-Migracje-Projekty/Projekt-TMask-Relay-Flows.md` — specyfikacja trybu relay
- `docs/superpowers/specs/` — design specs (transporter + relay flows)
- `docs/superpowers/plans/` — plany implementacji (transporter + relay flows)
