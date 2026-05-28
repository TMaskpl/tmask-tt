# tmask-transporter — Dokumentacja projektu

> Webowa aplikacja do przesyłania plików między systemami Linux przez SSH (SFTP/rsync).  
> Panel użytkownika, harmonogram cron, szyfrowanie GPG, interfejs Terminal/CRT.

## Architektura

```
Browser → Nginx :80 → Django/Gunicorn → PostgreSQL
                              ↓
                            Redis (broker)
                              ↓
                    ┌─────────────────────┐
                    │   Celery Worker      │
                    │  sftp / rsync / gpg  │
                    └─────────────────────┘
                              ↓
                        Host docelowy SSH
```

| Serwis    | Technologia                | Rola                        |
|-----------|----------------------------|-----------------------------|
| `web`     | Python 3.12 + Django 5.1   | UI, auth, REST API          |
| `worker`  | Celery 5 (prefork ×4)      | Wykonanie transferów        |
| `beat`    | Celery Beat                | Harmonogram cron            |
| `redis`   | Redis 7                    | Broker kolejki zadań        |
| `postgres`| PostgreSQL 16              | Baza danych                 |
| `nginx`   | Nginx 1.25                 | Reverse proxy, jedyny port  |

## Stack technologiczny

| Warstwa           | Biblioteka / Narzędzie                         |
|-------------------|------------------------------------------------|
| ORM / migracje    | Django ORM, django-decouple                    |
| Szyfrowanie pól   | django-encrypted-model-fields (Fernet AES-256) |
| SFTP/SCP          | Paramiko 3.x                                   |
| rsync             | subprocess + systemowy `rsync`                 |
| GPG               | subprocess + system `gpg` (AES-256 symmetric)  |
| Frontend          | Django templates + HTMX (self-hosted)          |
| Harmonogram       | django-celery-beat                             |
| Testy             | pytest + pytest-django + pytest-mock           |

## Moduły workera

```
services/worker/modules/
├── sftp/
│   ├── config.py       # SFTP_TIMEOUT, SFTP_MAX_RETRIES, SFTP_RETRY_DELAY
│   └── handler.py      # SFTPHandler — połączenie, transfer, retry, known_hosts
├── rsync/
│   ├── config.py       # RSYNC_BASE_FLAGS, RSYNC_TIMEOUT, RSYNC_MAX_RETRIES
│   └── handler.py      # RsyncHandler — budowanie komendy, subprocess, retry
├── gpg/
│   ├── config.py       # GPG_CIPHER_ALGO=AES256, GPG_TIMEOUT
│   └── handler.py      # encrypt_file() — tempdir jako --homedir, stdin passphrase
└── relay/
    └── handler.py      # RelayHandler — pobierz ze źródła → wyślij do celu
```

## Konfiguracja środowiskowa (`.env`)

Kopiuj `.env.example` i uzupełnij:

```bash
cp .env.example .env
```

| Zmienna              | Opis                                     | Jak wygenerować                                                      |
|----------------------|------------------------------------------|----------------------------------------------------------------------|
| `SECRET_KEY`         | Django secret key                        | `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`     |
| `FIELD_ENCRYPTION_KEY` | Klucz Fernet do szyfrowania pól DB    | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `POSTGRES_PASSWORD`  | Hasło do PostgreSQL                      | losowe, min 16 znaków                                                |
| `ALLOWED_HOSTS`      | Domeny aplikacji, oddzielone przecinkami | np. `myserver.example.com,localhost`                                 |
| `DEBUG`              | Tryb debug Django                        | `False` na produkcji                                                 |

> Nigdy nie commituj `.env` z prawdziwymi wartościami. Plik jest w `.gitignore`.

## Uruchomienie

```bash
# 1. Przygotuj środowisko
cp .env.example .env
# Edytuj .env — wygeneruj SECRET_KEY i FIELD_ENCRYPTION_KEY

# 2. Zbuduj i uruchom
docker compose build
docker compose up -d

# 3. Inicjalizacja bazy danych
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser

# Aplikacja dostępna pod: http://localhost
```

## Uruchamianie testów

```bash
# Testy web (Django/pytest)
docker compose exec web pytest -v

# Testy worker (Celery tasks, GPG, SFTP/rsync handlers)
docker compose exec worker pytest -v

# Konkretny moduł
docker compose exec web pytest apps/transfers/tests/ -v
```

## Bezpieczeństwo — kluczowe zasady

- Hasła i klucze SSH **szyfrowane Fernet AES-256** w bazie (`EncryptedCharField`)
- `FIELD_ENCRYPTION_KEY` i `SECRET_KEY` wyłącznie w `.env` — nigdy w kodzie
- GPG passphrase przekazywany przez **stdin** (`--passphrase-fd 0`) — nie pojawia się w `ps aux`
- Strict host key checking per-connection — MITM protection
- Izolacja użytkowników — owner check na każdym zasobie
- Non-root kontenery Docker (użytkownik `app`)
- CSP + `server_tokens off` + `X-Content-Type-Options` w Nginx

## Dokumentacja funkcji

| Funkcja              | Plik                           |
|----------------------|--------------------------------|
| Manualne transfery   | [features/transfers.md](features/transfers.md) |
| Połączenia SSH       | [features/connections.md](features/connections.md) |
| Flows (relay)        | [features/flows.md](features/flows.md) |
| Harmonogram cron     | [features/scheduler.md](features/scheduler.md) |
| Historia logów       | [features/logs.md](features/logs.md) |
| Profil / API / Webhook | [features/profile.md](features/profile.md) |

## Historia audytów bezpieczeństwa

| Data       | Narzędzia              | Wynik                                    |
|------------|------------------------|------------------------------------------|
| 2026-05-21 | Explore (statyczny)    | 5 krytycznych → naprawione tego dnia     |
| 2026-05-25 | SonarQube + ZAP + Codex| Django CVE-2025-64459 → natychmiast naprawione |
| 2026-05-26 | SonarQube + ZAP + Codex| Path traversal, SSRF → naprawione         |
| 2026-05-27 | Codex                  | MITM fail-closed → naprawione            |

Szczegóły: [audyt/](audyt/)
