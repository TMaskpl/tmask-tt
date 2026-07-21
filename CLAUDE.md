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
# Web (479 testów)
docker compose --profile test run --rm web-test python -m pytest apps/ -v

# Worker (185 testów)
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

Struktura rozdziela "stan obecny" (czytany przy każdej sesji) od historii (czytana na żądanie) — patrz sekcja niżej "Zasady dokumentacji vault".

- `11-Apps/CSCS/tmask-transporter/Projekt-tmask-transporter.md` — **stan obecny**: architektura, stack, status, linki. Krótki, nie rośnie z każdą funkcją.
- `11-Apps/CSCS/tmask-transporter/Projekt-tmask-transporter-HISTORIA.md` — pełna chronologia zrealizowanych funkcji, bugów, incydentów (append-only)
- `11-Apps/CSCS/tmask-transporter/audyt/INDEKS.md` — wskaźnik na najnowszy audyt każdego typu (DevSecOps/Trivy/Semgrep/Linter/ZAP); reszta plików w `audyt/` to historia (data w nazwie)
- `11-Apps/CSCS/tmask-transporter/testy/Projekt-tmask-transporter-Testy.md` — aktualny stan testów (nadpisywany) + kompaktowa tabela trendu
- `08-Migracje-Projekty/Projekt-TMask-Relay-Flows.md` — specyfikacja trybu relay
- `docs/superpowers/specs/` — design specs (transporter + relay flows)
- `docs/superpowers/plans/` — plany implementacji (transporter + relay flows)

## Zasady dokumentacji vault (nadpisują domyślne zachowanie skilli `obsidian-*`)

Wyłącznie dla tego projektu (pilotaż od 2026-07-20) — domyślne zachowanie skilli `obsidian-testy`/`obsidian-aktualizuj`/`audyt-devsecops` (dopisuj wszystko do jednego rosnącego pliku) jest tu **nadpisane**, żeby sesje nie musiały czytać coraz większego pliku przy każdej pracy nad projektem:

| Sytuacja | Co robić |
|----------|----------|
| Nowa funkcja / bugfix / incydent | Wpis `### N. Nazwa ✅ ZREALIZOWANE (data)` trafia do `Projekt-tmask-transporter-HISTORIA.md`, **nie** do `Projekt-tmask-transporter.md`. Główny plik dostaje co najwyżej aktualizację sekcji "Status" (1 zdanie), jeśli w ogóle. |
| Nowy audyt bezpieczeństwa (`/audyt-devsecops`, `/trivy-sonar`, `/tmask-semgrep`, `/tmask-python-linter`) | Nowy plik z datą w `audyt/` jak dotychczas (bez zmian) + zaktualizuj 1 wiersz w `audyt/INDEKS.md`. Nie kopiuj streszczenia raportu do `Projekt-tmask-transporter.md`. |
| Nowy wynik testów (`/obsidian-testy` lub ręcznie) | **Nadpisz** sekcję "Aktualny stan" w pliku testów (nie dopisuj nowej pełnej sekcji na górze). Dodaj jeden wiersz do tabeli "Historia (trend)" (data, web, worker, razem, 1 zdanie kontekstu) — nie pełną tabelę ze szczegółami jak przed 2026-07-20. |
| `Projekt-tmask-transporter-brainstorming.md` | Nie czytać ani nie edytować przy zwykłej pracy — czysto archiwalne. |

## Standardowy workflow dla nowej funkcjonalności

Dla nietrywialnych zmian (nowa funkcja, zmiana modelu danych, zmiana bezpieczeństwa) stosuj pełny cykl, mapowany na istniejące skille `superpowers`:

1. **Plan** — `superpowers:brainstorming` → `superpowers:writing-plans` (spec + plan w `docs/superpowers/`)
2. **Branch/worktree** — `superpowers:using-git-worktrees`, osobny branch per funkcja (unika kolizji, gdyby pracowało więcej sesji/osób równolegle)
3. **Implementacja + testy nowej funkcji** — `superpowers:subagent-driven-development` (TDD per zadanie, review spec+jakość po każdym)
4. **Pełna regresja** — cały suite (web + worker) musi przejść po każdej zmianie, nie tylko nowe testy
5. **Testy bezpieczeństwa** — `/audyt-devsecops` (SonarQube + ZAP + code review); przy zmianach zależności/obrazów też `/trivy-sonar`
6. **Naprawa rekomendacji** — jeśli audyt/review coś zgłosi: fix → pełna regresja ponownie → powtórka kroku 5 jeśli zmiana była istotna; wszystkie testy muszą przejść zanim dalej
7. **Dokumentacja + push** — `superpowers:finishing-a-development-branch` (merge/PR, rozwiązanie konfliktów) + aktualizacja HISTORIA/testy/audyt jak w sekcji wyżej

**Kiedy branch jest obowiązkowy:** nowa funkcja, zmiana modelu danych, zmiana bezpieczeństwa.
**Kiedy można iść bezpośrednio na `main`:** drobne bugfixy, sprzątanie code smells, aktualizacje dokumentacji — zakres nieuzasadniający pełnego cyklu (dotychczasowa praktyka w tym repo, np. poprawki UX #17b czy sprzątanie audytu z 2026-07-14/15).
