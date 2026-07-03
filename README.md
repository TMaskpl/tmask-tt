# tmask-transporter

<img width="459" height="459" alt="Zrzut ekranu z 2026-05-21 08-23-32" src="https://github.com/user-attachments/assets/9b08543f-bd36-4d38-88da-811959ad1139" />


Webowa aplikacja do przesyłania plików między systemami Linux przez SSH (SFTP/rsync).

Panel użytkownika, harmonogram cron, szyfrowanie transferów (Fernet AES-256), interfejs Terminal/CRT.

## Wymagania

- Docker + Docker Compose v2 (`docker compose`, nie legacy `docker-compose`), buildx ≥ 0.17.0 — na Debian/Ubuntu z pakietem `docker.io` z repo dystrybucji obie wtyczki bywają za stare lub nieobecne; instalacja per-user bez `sudo`:
  ```bash
  mkdir -p ~/.docker/cli-plugins
  curl -fSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" -o ~/.docker/cli-plugins/docker-compose
  curl -fSL "https://github.com/docker/buildx/releases/latest/download/buildx-v0.35.0.linux-amd64" -o ~/.docker/cli-plugins/docker-buildx
  chmod +x ~/.docker/cli-plugins/docker-compose ~/.docker/cli-plugins/docker-buildx
  ```

## Uruchomienie

```bash
cp .env.example .env
# Wygeneruj klucze:
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FIELD_ENCRYPTION_KEY
# Uzupełnij .env, następnie wygeneruj certyfikat TLS (jednorazowo, self-signed, 10 lat):
mkdir -p nginx/certs
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout nginx/certs/selfsigned.key -out nginx/certs/selfsigned.crt \
  -days 3650 -subj "/CN=tmask-transporter.local" \
  -addext "subjectAltName=DNS:tmask-transporter.local,DNS:localhost,IP:127.0.0.1"
docker compose up -d
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
```

Aplikacja dostępna pod: https://localhost lub https://tmask-transporter.local (dodaj wpis do `/etc/hosts`: `127.0.0.1 tmask-transporter.local` lub adres IP serwera w LAN). Certyfikat jest self-signed — przeglądarka pokaże ostrzeżenie o niezaufanym CA, zaakceptuj je ręcznie ("Zaawansowane → Kontynuuj"). HTTP (port 80) przekierowuje automatycznie na HTTPS.

## Deployment (CI/CD)

Push/merge na `main` automatycznie:
1. Uruchamia pełny suite testów (web + worker) na self-hosted runnerze zainstalowanym na serwerze produkcyjnym.
2. Jeśli testy przejdą, buduje obrazy produkcyjne (`docker compose build`) i podnosi je (`docker compose up -d`).
3. Sprawdza healthcheck (`https://localhost/accounts/login/`) — jeśli aplikacja nie odpowie w ~30s, workflow kończy się czerwono (kontener mimo to zostaje podniesiony — brak automatycznego rollbacku, patrz niżej).

Workflow: `.github/workflows/deploy.yml`. Podgląd przebiegów: `https://github.com/TMaskpl/tmask-tt/actions`.

**Ręczny redeploy bez nowego commita:** zakładka Actions → workflow "Test & Deploy" → **Run workflow** (branch `main`).

**Runner:** usługa systemd `actions.runner.TMaskpl-tmask-tt.tmask-tt-deploy-onlo.service` na serwerze produkcyjnym (`/opt/actions-runner`). Status: `sudo ./svc.sh status` w `/opt/actions-runner`. Jeśli runner jest offline, workflow wisi w statusie "Waiting for a runner" — restart: `sudo ./svc.sh start`.

**Rollback (ręczny, brak automatycznego):**
```bash
git checkout <poprzedni-dobry-commit>
git push --force-with-lease origin main   # albo: git revert <zły-commit> && git push
```
Push uruchomi normalną ścieżkę test→deploy i odbuduje poprzednią wersję. Brak wersjonowanych obrazów/tagów — to świadomy kompromis (jeden serwer, LAN-only, mała skala).

**Czego workflow NIE rusza:** `.env` i `nginx/certs/` na serwerze (gitignored, `actions/checkout` skonfigurowany z `clean: false` właśnie po to, by ich nie skasować). Oba zostały wygenerowane ręcznie, raz, przy pierwszym wdrożeniu (`docs/superpowers/plans/2026-07-03-cicd-github-actions-deploy.md`, Task 1).

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
