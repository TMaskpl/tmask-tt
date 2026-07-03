# CI/CD: GitHub Actions Self-Hosted Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push/merge do `main` automatycznie uruchamia testy (web + worker) i, jeśli przejdą, wdraża tmask-transporter na serwer produkcyjny (VM/LXC w LAN, bez publicznego IP) — bez ręcznego SSH i bez ręcznego `docker compose build/up`.

**Architecture:** Jeden workflow (`.github/workflows/deploy.yml`) z dwoma jobami, oba na self-hosted runnerze zainstalowanym bezpośrednio na serwerze docelowym (jedyny sposób, by GitHub Actions dotarło do maszyny bez publicznego IP). Job `test` buduje i odpala pytest (web przez serwis `web-test`, worker przez serwis `worker`). Job `deploy` (`needs: test`) buduje obrazy produkcyjne, robi `docker compose up -d` i sprawdza healthcheck przez HTTPS. Migracje DB dzieją się automatycznie w `entrypoint.sh` kontenera `web` — brak osobnego kroku.

**Tech Stack:** GitHub Actions (self-hosted runner), Docker Compose v2, bash, curl, Python 3 + PyYAML (lokalna walidacja składni workflow).

## Kontekst zweryfikowany na żywym serwerze (2026-07-03)

- Serwer: `192.168.50.224`, SSH `runner@192.168.50.224` port 22 (klucz już skopiowany).
- Runner: usługa systemd `actions.runner.TMaskpl-tmask-tt.tmask-tt-deploy-onlo.service`, `WorkingDirectory=/opt/actions-runner`, działa jako user `runner`, status `active`.
- User `runner` **jest już** w grupie `docker` (`groups` → `runner sudo users docker`) — Task z Task 1 sprzed tej korekty planu ("dodaj do grupy docker") jest zbędny.
- **To jest świeży serwer — brak jakiegokolwiek istniejącego `docker-compose.yml`/`.env`/wdrożenia.** Pierwotny plan zakładał migrację istniejącej ręcznej produkcji na tę maszynę; w rzeczywistości to pierwszy deployment tmask-transporter na tym serwerze w ogóle. Task 1 poniżej został przepisany pod ten scenariusz (bootstrap od zera), zamiast "wyrównania katalogów".
- Konkretna ścieżka checkout (deterministyczna z konwencji `actions/checkout` + nazwa folderu roboczego `_work`, potwierdzona przy rejestracji runnera): **`/opt/actions-runner/_work/tmask-tt/tmask-tt`**.

## Global Constraints

- Oba joby (`test` i `deploy`) muszą działać na `runs-on: self-hosted` — GitHub-hosted runner nie ma dostępu do `.env` (gitignored, istnieje tylko na serwerze), a `web-test`/`worker` wymagają `env_file: .env` (spec decyzja #2).
- **Krok `actions/checkout` w KAŻDYM jobie musi mieć `clean: false`.** Domyślne zachowanie `actions/checkout` (`clean: true`) uruchamia `git clean -ffdx` przed checkoutem — flaga `-x` usuwa też pliki `.gitignore`owane, czyli **skasowałaby `.env` i `nginx/certs/`** na każdym uruchomieniu workflow. To nie było w spec — odkryte przy pisaniu planu, krytyczne dla bezpieczeństwa produkcji.
- Brak registry (GHCR) — obrazy budowane lokalnie na serwerze przez `docker compose build` (spec decyzja #1).
- Trigger wyłącznie: `push` na `main` + `workflow_dispatch` — żadnych innych eventów (np. `pull_request`) nie dodawać, self-hosted runner na produkcyjnej maszynie nie powinien wykonywać kodu z niezmergowanych PR-ów.
- `deploy` ma `needs: test` — nie usuwać, to jedyny mechanizm chroniący przed wdrożeniem czerwonego builda (spec decyzja #4).
- Nie dodawać automatycznego rollbacku ani powiadomień (Slack/Discord) — poza zakresem spec.
- `.env` produkcyjny generowany raz, ręcznie, w Task 1 — nigdy nie trafia do git (już objęty `.gitignore`), nigdy nie jest odtwarzany/nadpisywany przez workflow.
- Certyfikat nginx (SAN: `tmask-transporter.local`, `localhost`, `127.0.0.1`) generowany dokładnie komendą z `docs/superpowers/specs/2026-07-02-https-design.md` — bez zmian w SAN względem tego, co już zaakceptowane w tamtym spec.

---

### Task 1: Bootstrap pierwszego wdrożenia na serwerze (`.env`, cert nginx, baza, superuser)

**Files:** brak zmian w repo — praca wyłącznie na serwerze przez SSH. Efekt: pliki `.env` i `nginx/certs/{selfsigned.crt,selfsigned.key}` na dysku serwera w `/opt/actions-runner/_work/tmask-tt/tmask-tt/` (oba gitignored, nigdy nie trafiają do repo).

**Interfaces:**
- Produces: działający `.env` i `nginx/certs/` w `/opt/actions-runner/_work/tmask-tt/tmask-tt/` — Task 2 (workflow `test`) i Task 3 (workflow `deploy`) zakładają, że oba istnieją w tym katalogu, zanim workflow spróbuje tam cokolwiek zbudować/podnieść.

- [ ] **Step 1: Pierwszy checkout repo do katalogu roboczego runnera**

Katalog `_work/tmask-tt/tmask-tt` jeszcze nie istnieje (świeży serwer, runner nigdy nie wykonał joba). Najprostszy sposób, by go utworzyć bez ręcznego rozwiązywania autoryzacji do prywatnego repo na serwerze: wypchnij Task 2 (workflow z samym jobem `test`) na `main` **przed** wykonaniem reszty tego taska. `actions/checkout` w GitHub Actions używa tokena wstrzykiwanego automatycznie przez usługę Actions do self-hosted runnera — nie wymaga żadnej ręcznej konfiguracji `git`/`gh` na serwerze.

Kolejność wykonania w praktyce: zrób najpierw Step 1-3 z Task 2 (utworzenie i push `.github/workflows/deploy.yml` z samym jobem `test`), poczekaj aż job `test` się odpali i **zawiedzie** na kroku `docker compose --profile test build web-test` (oczekiwane — `.env` jeszcze nie istnieje). To wystarczy, by checkout utworzył katalog. Potem wróć tutaj i wykonaj Step 2 poniżej.

- [ ] **Step 2: Zweryfikuj że katalog istnieje i jest czystym checkoutem**

```bash
ssh runner@192.168.50.224 'ls -la /opt/actions-runner/_work/tmask-tt/tmask-tt/'
```
Expected: pliki repo (`docker-compose.yml`, `services/`, `.git/` itd.), brak `.env`, brak `nginx/certs/`.

- [ ] **Step 3: Wygeneruj `.env` produkcyjny**

```bash
ssh runner@192.168.50.224 bash -s <<'REMOTE'
set -e
cd /opt/actions-runner/_work/tmask-tt/tmask-tt

PG_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
FIELD_KEY=$(python3 -c "
try:
    from cryptography.fernet import Fernet
except ImportError:
    import subprocess
    subprocess.run(['pip3', 'install', '--user', 'cryptography'], check=True)
    from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
")

cat > .env <<EOF
POSTGRES_DB=transporter
POSTGRES_USER=transporter
POSTGRES_PASSWORD=${PG_PASS}
DATABASE_URL=postgresql://transporter:${PG_PASS}@postgres:5432/transporter

SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=tmask-transporter.local,localhost,127.0.0.1

REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

FIELD_ENCRYPTION_KEY=${FIELD_KEY}

SENTRY_DSN=

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=noreply@example.com
EMAIL_HOST_PASSWORD=secret
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=TMask Transporter <noreply@example.com>
EOF

chmod 600 .env
echo "OK: .env created, $(wc -l < .env) lines"
REMOTE
```
Expected: `OK: .env created, 22 lines` (lub zbliżona liczba), brak błędów. Hasła/klucze generowane losowo na serwerze — nigdy nie przechodzą przez lokalny terminal kontrolera w jawnej formie inaczej niż przez ten jednorazowy `heredoc` (nie są logowane/zapisywane lokalnie).

**Uwaga o `EMAIL_HOST_PASSWORD=secret` i innych placeholderach email:** to wartości z `.env.example` — jeśli e-mail nie jest jeszcze skonfigurowany na tym serwerze, zostają jako placeholder (backend `console` i tak tylko loguje maile, nie wysyła ich naprawdę). Do podmiany ręcznie przez użytkownika, gdy będzie miał prawdziwe dane SMTP — poza zakresem tego planu.

- [ ] **Step 4: Wygeneruj certyfikat nginx (self-signed, jak w spec HTTPS)**

```bash
ssh runner@192.168.50.224 bash -s <<'REMOTE'
set -e
cd /opt/actions-runner/_work/tmask-tt/tmask-tt
mkdir -p nginx/certs
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout nginx/certs/selfsigned.key -out nginx/certs/selfsigned.crt \
  -days 3650 -subj "/CN=tmask-transporter.local" \
  -addext "subjectAltName=DNS:tmask-transporter.local,DNS:localhost,IP:127.0.0.1"
ls -la nginx/certs/
REMOTE
```
Expected: `selfsigned.crt` i `selfsigned.key` utworzone w `nginx/certs/`.

- [ ] **Step 5: Pierwsze ręczne uruchomienie stosu (bootstrap bazy) + superuser**

```bash
ssh runner@192.168.50.224 bash -s <<'REMOTE'
set -e
cd /opt/actions-runner/_work/tmask-tt/tmask-tt
docker compose up -d
sleep 10
docker compose ps
REMOTE
```
Expected: wszystkie serwisy (`postgres`, `redis`, `web`, `worker`, `beat`, `nginx`) `Up`/`healthy`. `web` przy starcie sam wykonał `migrate` (entrypoint.sh) — świeża baza ma już schemat.

Następnie utwórz konto administratora (interaktywnie, hasło wpisywane ręcznie przez użytkownika — kontroler NIE generuje hasła admina automatycznie):
```bash
ssh -t runner@192.168.50.224 'cd /opt/actions-runner/_work/tmask-tt/tmask-tt && docker compose exec web python manage.py createsuperuser'
```
Expected: interaktywny prompt (username/email/password) na terminalu użytkownika — **ten krok wykonuje użytkownik osobiście**, nie kontroler, żeby hasło admina nie przeszło przez sesję agenta.

- [ ] **Step 6: Weryfikacja end-to-end bootstrapu**

```bash
ssh runner@192.168.50.224 'curl -sk https://localhost/accounts/login/ -o /dev/null -w "%{http_code}\n"'
```
Expected: `200`.

_Ten task nie ma "commita" — to czysto operacyjny bootstrap na serwerze, bez zmian w repo. Sekrety (`.env`, klucz prywatny certu) zostają wyłącznie na serwerze._

---

### Task 2: `.github/workflows/deploy.yml` — job `test`

**Files:**
- Create: `.github/workflows/deploy.yml`

**Interfaces:**
- Produces: plik workflow z jobem `test` — Task 3 dopisze do tego samego pliku job `deploy` z `needs: test`.

**Uwaga o kolejności:** Steps 1-3 tego taska (napisanie + push workflow) wykonują się **przed** Task 1 Step 2 (patrz Task 1 Step 1) — pierwszy push z samym jobem `test` posłuży też do utworzenia katalogu checkout na serwerze. Step 4 tego taska (finalna zielona weryfikacja) wykonuje się **po** ukończeniu całego Task 1.

- [ ] **Step 1: Utwórz katalog i plik workflow z jobem `test`**

Utwórz `.github/workflows/deploy.yml`:
```yaml
name: Test & Deploy

on:
  push:
    branches: [main]
  workflow_dispatch: {}

jobs:
  test:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
        with:
          clean: false

      - name: Build test image (web-test)
        run: docker compose --profile test build web-test

      - name: Run web test suite
        run: docker compose --profile test run --rm web-test python -m pytest apps/ -v

      - name: Build worker image
        run: docker compose build worker

      - name: Run worker test suite
        run: docker compose run --rm worker python -m pytest tests/ -v
```

- [ ] **Step 2: Zwaliduj składnię YAML lokalnie**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('OK: valid YAML')"
```
Expected: `OK: valid YAML`, brak wyjątku.

- [ ] **Step 3: Commit i push**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add test job (web + worker pytest) on self-hosted runner"
git push origin main
```

Expected natychmiast po push (na świeżym serwerze, patrz Task 1 Step 1): job `test` startuje, `actions/checkout` się udaje (tworzy `/opt/actions-runner/_work/tmask-tt/tmask-tt`), krok `Build test image (web-test)` **zawodzi** (brak `.env`) — to oczekiwane, wróć teraz do Task 1 Step 2.

- [ ] **Step 4: Finalna weryfikacja w GitHub Actions UI (PO ukończeniu Task 1)**

Po zakończeniu Task 1 (bootstrap `.env`/certu/bazy na serwerze), odpal ponownie workflow ręcznie: `https://github.com/TMaskpl/tmask-tt/actions/workflows/deploy.yml` → **Run workflow** (branch `main`).

Expected: job `test` zielony, logi pokazują `385 passed` (web) i `127 passed` (worker) — dokładne liczby zgodnie z ostatnim znanym stanem testów w dokumentacji projektu; jeśli się różnią, to nie błąd tego planu, tylko aktualny stan suite'u.

---

### Task 3: `.github/workflows/deploy.yml` — job `deploy`

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: job `test` z Task 2 (nazwa `test`, ten sam plik) — `needs: test`.

- [ ] **Step 1: Dopisz job `deploy` na końcu pliku**

Dodaj po jobie `test` (zachowując wcięcie na poziomie `jobs:`):
```yaml
  deploy:
    needs: test
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
        with:
          clean: false

      - name: Build production images
        run: docker compose build

      - name: Recreate containers
        run: docker compose up -d

      - name: Healthcheck
        run: |
          for i in $(seq 1 10); do
            if curl -sf -k https://localhost/accounts/login/ > /dev/null; then
              echo "Healthcheck OK"
              exit 0
            fi
            sleep 3
          done
          echo "Healthcheck FAILED — kontener podniesiony, ale aplikacja nie odpowiada"
          exit 1
```

- [ ] **Step 2: Zwaliduj składnię YAML lokalnie**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('OK: valid YAML')"
```
Expected: `OK: valid YAML`.

- [ ] **Step 3: Commit i push**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add deploy job (build + up + healthcheck) gated on tests passing"
git push origin main
```

- [ ] **Step 4: Zweryfikuj pełny przebieg test→deploy w Actions UI**

Otwórz `https://github.com/TMaskpl/tmask-tt/actions`, poczekaj aż oba joby się wykonają.

Expected: `test` zielony, potem `deploy` startuje automatycznie (dzięki `needs`), kończy się zielono z logiem `Healthcheck OK`.

- [ ] **Step 5: Ręczna weryfikacja na serwerze po deployu**

```bash
ssh runner@192.168.50.224 '
cd /opt/actions-runner/_work/tmask-tt/tmask-tt
docker compose ps
git status
'
```
Expected: wszystkie serwisy `Up`/`healthy`, `git status` pokazuje **tylko** pliki wersjonowane jako ewentualnie zmienione (zero wzmianek o `.env` czy `nginx/certs/` — muszą pozostać nietknięte, potwierdzenie że `clean: false` zadziałało).

---

### Task 4: Weryfikacja — nieprzechodzące testy blokują deploy

**Files:** brak trwałych zmian w `main` — praca na tymczasowym branchu.

**Interfaces:** brak (czysto weryfikacyjny task, nie zmienia workflow ani aplikacji).

- [ ] **Step 1: Utwórz branch z celowo zepsutym testem**

```bash
git checkout -b tmp/verify-test-gate
```
W dowolnym pliku testowym web, np. `services/web/apps/connections/tests/test_views.py`, dodaj na końcu:
```python
def test_deliberately_broken_for_ci_verification():
    assert False, "celowy fail do weryfikacji CI gate — usunąć po teście"
```

- [ ] **Step 2: Commit na branchu (bez push na main)**

```bash
git add services/web/apps/connections/tests/test_views.py
git commit -m "test: deliberately broken test to verify CI gate (temporary)"
git push origin tmp/verify-test-gate
```

- [ ] **Step 3: Odpal workflow ręcznie na tym branchu**

W `https://github.com/TMaskpl/tmask-tt/actions/workflows/deploy.yml` kliknij **Run workflow**, wybierz branch `tmp/verify-test-gate`.

Expected: job `test` czerwony (fail na `test_deliberately_broken_for_ci_verification`), job `deploy` **w ogóle się nie uruchamia** (status "Skipped" w UI, dzięki `needs: test`).

- [ ] **Step 4: Sprzątanie — usuń branch i test**

```bash
git checkout main
git branch -D tmp/verify-test-gate
git push origin --delete tmp/verify-test-gate
```

---

### Task 5: Weryfikacja — fail builda nie psuje działającego kontenera

**Files:** brak trwałych zmian w `main` — praca na tymczasowym branchu.

**Interfaces:** brak.

- [ ] **Step 1: Utwórz branch z celowo zepsutym Dockerfile**

```bash
git checkout -b tmp/verify-build-safety
```
Na końcu `services/web/Dockerfile` dodaj celowo błędną linię:
```dockerfile
RUN this-command-does-not-exist-verify-ci-safety
```

- [ ] **Step 2: Commit i push brancha**

```bash
git add services/web/Dockerfile
git commit -m "test: deliberately broken Dockerfile to verify build-fail safety (temporary)"
git push origin tmp/verify-build-safety
```

- [ ] **Step 3: Zapisz stan kontenerów PRZED odpaleniem workflow**

```bash
ssh runner@192.168.50.224 '
cd /opt/actions-runner/_work/tmask-tt/tmask-tt
docker inspect $(docker compose ps -q web) --format "{{.State.StartedAt}}"
'
```
Expected: zapisany timestamp startu obecnego kontenera `web` — punkt odniesienia do porównania.

- [ ] **Step 4: Odpal workflow ręcznie na tym branchu**

W Actions UI: **Run workflow**, branch `tmp/verify-build-safety`.

Expected: job `test` zielony (Dockerfile web-test/worker niezmieniony, tylko `web`/production dotknięty), job `deploy` czerwony na kroku `Build production images` (błąd `this-command-does-not-exist-verify-ci-safety: not found`), krok `Recreate containers` **nie wykonuje się** (poprzedni krok failował, GitHub Actions domyślnie przerywa job).

- [ ] **Step 5: Potwierdź brak przestoju na serwerze**

```bash
ssh runner@192.168.50.224 '
cd /opt/actions-runner/_work/tmask-tt/tmask-tt
docker inspect $(docker compose ps -q web) --format "{{.State.StartedAt}}"
curl -sk https://localhost/accounts/login/ -o /dev/null -w "%{http_code}\n"
'
```
Expected: identyczny `StartedAt` jak w Step 3 (kontener `web` nie został ruszony), `curl` zwraca `200`.

- [ ] **Step 6: Sprzątanie**

```bash
git checkout main
git branch -D tmp/verify-build-safety
git push origin --delete tmp/verify-build-safety
```
Na serwerze usuń nieudany obraz z cache builda (opcjonalne, porządkowe):
```bash
ssh runner@192.168.50.224 'docker image prune -f'
```

---

### Task 6: Dokumentacja mechanizmu w README.md

**Files:**
- Modify: `README.md`

**Interfaces:** brak (dokumentacja, nie kod).

- [ ] **Step 1: Dodaj sekcję "Deployment (CI/CD)" w `README.md`**

Dodaj nową sekcję (po istniejącej sekcji instalacji/HTTPS, przed lub po sekcją testów — dopasuj do obecnej struktury pliku):

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document CI/CD deployment mechanism (workflow, rollback, runner status)"
git push origin main
```

---

## Self-Review (wykonane przy pisaniu planu, zaktualizowane po weryfikacji na żywym serwerze)

**Pokrycie spec:**
- Wariant A (self-hosted, brak registry) → Task 2, 3 ✓
- Oba joby self-hosted (korekta #2 w spec) → Task 2, 3 (`runs-on: self-hosted` w obu) ✓
- Trigger push+workflow_dispatch → Task 2 Step 1 (`on:` blok) ✓
- Testy blokują deploy → Task 3 (`needs: test`), zweryfikowane w Task 4 ✓
- Healthcheck → Task 3 Step 1 ✓
- Rollback ręczny → udokumentowany w Task 6 ✓
- Weryfikacja mechanizmu (spec sekcja "Testy/Weryfikacja") → Task 2 Step 4, Task 4, Task 5 ✓

**Korekty znalezione podczas planowania i wykonania (poza pierwotnym spec):**
1. `clean: false` na `actions/checkout` — bez tego każdy deploy kasowałby `.env`/`nginx/certs/`. Dodane do Global Constraints i obu jobów.
2. Serwer okazał się świeżą maszyną bez istniejącej produkcji (spec/pierwsza wersja planu zakładały migrację istniejącego ręcznego wdrożenia) — Task 1 przepisany na pełny bootstrap (`.env`, cert, baza, superuser) zamiast "wyrównania katalogów".
3. Kolejność Task 1/Task 2 odwrócona operacyjnie: pierwszy push workflow (Task 2 Steps 1-3) musi poprzedzić bootstrap sekretów (Task 1 Steps 2-6), bo to jedyny sposób utworzenia katalogu checkout na serwerze bez ręcznej konfiguracji auth do prywatnego repo.

**Poza zakresem (zgodnie ze spec, nieujęte w tym planie):** GHCR, automatyczny rollback, powiadomienia, staging, aktualizacja nieaktualnych komend testowych w `CLAUDE.md`, konfiguracja prawdziwego SMTP (zostaje placeholder z `.env.example`).
