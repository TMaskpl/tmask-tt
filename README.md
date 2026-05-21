# tmask-transporter

Webowa aplikacja do przesyłania plików między systemami Linux przez SSH (SFTP/rsync).

Panel użytkownika, harmonogram cron, szyfrowanie transferów (Fernet AES-256), interfejs Terminal/CRT.

## Wymagania

- Docker + Docker Compose

## Uruchomienie

```bash
cp .env.example .env
# Wygeneruj klucze:
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FIELD_ENCRYPTION_KEY
# Uzupełnij .env, następnie:
docker compose up -d
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
```

Aplikacja dostępna pod: http://localhost

## Architektura

| Serwis | Rola |
|--------|------|
| `web` | Django + Gunicorn — UI, auth, API |
| `worker` | Celery worker — moduły SFTP/rsync |
| `beat` | Celery Beat — harmonogram cron |
| `redis` | Broker Celery |
| `postgres` | Baza danych |
| `nginx` | Reverse proxy (jedyny port zewnętrzny) |

## Moduły transferu

- `services/worker/modules/sftp/` — SFTP/SCP przez Paramiko (retry 3x, known_host_key, multi-type SSH keys)
- `services/worker/modules/rsync/` — rsync przez SSH subprocess (compress, error classification, retry 3x)

## Bezpieczeństwo

- Hasła i klucze SSH szyfrowane Fernet AES-256 w bazie danych
- `SECRET_KEY` i `FIELD_ENCRYPTION_KEY` tylko w `.env` — nigdy w repo
- Izolacja użytkowników — każdy widzi tylko swoje połączenia i transfery
- Non-root kontenery Docker (użytkownik `app`)
