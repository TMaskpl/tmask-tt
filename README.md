# tmask-transporter

![Uploading obraz.png…]()


Webowa aplikacja do przesyłania i replikacji danych między systemami przez SSH (SFTP/rsync) oraz bezpośrednio między bazami danych (Postgres/MySQL/MSSQL) — z harmonogramem cron, szyfrowaniem transferów (Fernet AES-256), opcjonalnym maskowaniem danych (Faker) przy replikacji do środowisk testowych, 2FA, rolami użytkowników i powiadomieniami (e-mail/webhook/Telegram).

Interfejs "Dark Ops Console" — dark slate/navy, karty zamiast ramek, Inter (UI) + JetBrains Mono (logi/dane, self-hostowane), zero zewnętrznych CDN.

> Zrzut ekranu do dodania — obecny interfejs (2026-07-28, redesign "Dark Ops Console") nie ma jeszcze aktualnego screena w tym README. Uruchom aplikację lokalnie (patrz niżej) albo wrzuć własny zrzut przez drag&drop w edytorze GitHub, żeby go tu wstawić.

## Funkcje

- **Transfer plików**: SFTP/SCP i rsync przez SSH (retry, known_host_key, klucze z hasłem, batch upload wielu plików, dry-run, weryfikacja SHA-256, szyfrowanie GPG)
- **Relay (Flows)**: transfer SFTP→SFTP bez pośredniego zapisu na dysku lokalnym
- **Replikacja baz danych**: Postgres↔Postgres, MySQL↔MySQL, MSSQL↔MSSQL (cała baza albo pojedyncza tabela)
- **Maskowanie danych**: opcjonalne podmienianie wybranych kolumn tekstowych danymi Faker przy replikacji do środowisk testowych (ochrona PII)
- **Harmonogram**: Celery Beat + cron expressions, strefa czasowa
- **Role i organizacja**: Admin / Operator / Read-only, audit log zmian konfiguracji
- **Bezpieczeństwo**: 2FA (TOTP), szyfrowanie Fernet AES-256 haseł/kluczy SSH w bazie, HTTPS
- **Powiadomienia**: e-mail, webhook (generyczny + natywny Slack/Telegram) z historią dostarczeń i circuit breakerem
- **Dashboard**: wykresy sukces/porażka, historia transferów
- **API**: REST endpoint do triggerowania transferów z zewnętrznych skryptów/CI (token per-user)

## Wymagania

- Serwer Debian lub Ubuntu (on-prem albo VPS) z uprawnieniami `sudo`/root
- Docker Engine + Docker Compose v2 (wtyczka `docker compose`, nie legacy `docker-compose`) — na czystym serwerze zainstaluj jednym poleceniem:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/TMaskpl/tmask-tt/main/scripts/install-system-deps.sh | sudo bash
  ```
  Skrypt instaluje Docker Engine + Compose z oficjalnego repozytorium Docker (nie z pakietu dystrybucji, który bywa przestarzały), `git`, `openssl`, dodaje bieżącego użytkownika do grupy `docker`. Po pierwszym uruchomieniu na koncie bez roota **wyloguj się i zaloguj ponownie**, żeby zmiana grupy zadziałała — albo sklonuj repo i doinstaluj lokalnie: `sudo ./scripts/install-system-deps.sh` (idempotentny, bezpieczny do ponownego odpalenia).
- Na VPS: porty **80** i **443** muszą być otwarte na firewallu/security group dostawcy (np. `ufw allow 80,443/tcp` na Debian/Ubuntu z UFW).

## Uruchomienie

```bash
git clone git@github.com:TMaskpl/tmask-tt.git
cd tmask-tt
cp .env.example .env
# Wygeneruj klucze:
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # SECRET_KEY
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FIELD_ENCRYPTION_KEY
# Uzupełnij .env (SECRET_KEY, FIELD_ENCRYPTION_KEY, hasła Postgres, ALLOWED_HOSTS z domeną/IP serwera)
# Wygeneruj certyfikat TLS (jednorazowo, self-signed, 10 lat) — na produkcyjnym VPS podmień na Let's Encrypt jeśli masz domenę publiczną:
mkdir -p nginx/certs
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout nginx/certs/selfsigned.key -out nginx/certs/selfsigned.crt \
  -days 3650 -subj "/CN=tmask-transporter.local" \
  -addext "subjectAltName=DNS:tmask-transporter.local,DNS:localhost,IP:127.0.0.1"
docker compose up -d
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
# createsuperuser nadaje uprawnienia Django (is_superuser/is_staff), ale NIE
# rolę aplikacji (nowe konta domyślnie dostają rolę Operator) — bez tego kroku
# nie zobaczysz sekcji Admin-only (Connections, Masking, Users, Audit Log):
docker compose run --rm web python manage.py shell -c "
from apps.accounts.models import User
u = User.objects.get(username='TWOJA_NAZWA_UZYTKOWNIKA')
u.role = 'admin'
u.save(update_fields=['role'])
"
```

Aplikacja dostępna pod: `https://<adres-IP-serwera>` albo `https://tmask-transporter.local` (dodaj wpis do `/etc/hosts` na maszynie klienckiej: `<adres-IP-serwera> tmask-transporter.local`). Certyfikat jest self-signed — przeglądarka pokaże ostrzeżenie o niezaufanym CA, zaakceptuj je ręcznie ("Zaawansowane → Kontynuuj"). HTTP (port 80) przekierowuje automatycznie na HTTPS.

## Deployment (CI/CD)

Push/merge na `main` automatycznie:
1. Uruchamia pełny suite testów (web + worker) na self-hosted runnerze zainstalowanym na serwerze produkcyjnym.
2. Jeśli testy przejdą, buduje obrazy produkcyjne (`docker compose build`) i podnosi je (`docker compose up -d`).
3. Sprawdza healthcheck (`https://localhost/accounts/login/`) — jeśli aplikacja nie odpowie w ~30s, workflow kończy się czerwono (kontener mimo to zostaje podniesiony — brak automatycznego rollbacku, patrz niżej).

Workflow: `.github/workflows/deploy.yml`. Podgląd przebiegów: `https://github.com/TMaskpl/tmask-tt/actions`.

**Ręczny redeploy bez nowego commita:** zakładka Actions → workflow "Test & Deploy" → **Run workflow** (branch `main`). Uwaga: **Run workflow zawsze wdraża wybrany branch na produkcję** — zawsze wybieraj `main`, chyba że świadomie testujesz mechanizm na branchu tymczasowym.

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
| `worker` | Celery worker — moduły transferu (patrz niżej) |
| `beat` | Celery Beat — harmonogram cron |
| `redis` | Broker Celery |
| `postgres` | Baza danych |
| `nginx` | Reverse proxy (jedyny port zewnętrzny) |

## Moduły transferu

Niezależne moduły w `services/worker/modules/` — zmiana jednego nie dotyka pozostałych:

- `sftp/` — SFTP/SCP przez Paramiko (retry 3x, known_host_key, klucze z hasłem, multi-type SSH keys)
- `rsync/` — rsync przez SSH subprocess (compress, error classification, retry 3x, dry-run)
- `relay/` — SFTP→SFTP bez pośredniego zapisu na dysku lokalnym (Flows)
- `postgres/`, `mysql/`, `mssql/` — replikacja baza/tabela między instancjami tego samego silnika (`pg_dump`/`mysqldump`/`bcp` + introspekcja schematu)
- `masking/` — wspólny moduł Faker używany przez `postgres/`, `mysql/`, `mssql/` do opcjonalnego maskowania kolumn w locie

## Bezpieczeństwo

- Hasła i klucze SSH szyfrowane Fernet AES-256 w bazie danych
- `SECRET_KEY` i `FIELD_ENCRYPTION_KEY` tylko w `.env` — nigdy w repo
- Izolacja użytkowników — każdy widzi tylko swoje połączenia i transfery
- Non-root kontenery Docker (użytkownik `app`)
