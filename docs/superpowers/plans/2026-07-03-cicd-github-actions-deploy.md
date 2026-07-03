# CI/CD: GitHub Actions Self-Hosted Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push/merge do `main` automatycznie uruchamia testy (web + worker) i, jeśli przejdą, wdraża tmask-transporter na serwer produkcyjny (VM/LXC w LAN, bez publicznego IP) — bez ręcznego SSH i bez ręcznego `docker compose build/up`.

**Architecture:** Jeden workflow (`.github/workflows/deploy.yml`) z dwoma jobami, oba na self-hosted runnerze zainstalowanym bezpośrednio na serwerze docelowym (jedyny sposób, by GitHub Actions dotarło do maszyny bez publicznego IP). Job `test` buduje i odpala pytest (web przez serwis `web-test`, worker przez serwis `worker`). Job `deploy` (`needs: test`) buduje obrazy produkcyjne, robi `docker compose up -d` i sprawdza healthcheck przez HTTPS. Migracje DB dzieją się automatycznie w `entrypoint.sh` kontenera `web` — brak osobnego kroku.

**Tech Stack:** GitHub Actions (self-hosted runner), Docker Compose v2, bash, curl, Python 3 + PyYAML (lokalna walidacja składni workflow).

## Global Constraints

- Oba joby (`test` i `deploy`) muszą działać na `runs-on: self-hosted` — GitHub-hosted runner nie ma dostępu do `.env` (gitignored, istnieje tylko na serwerze), a `web-test`/`worker` wymagają `env_file: .env` (spec decyzja #2).
- **Krok `actions/checkout` w KAŻDYM jobie musi mieć `clean: false`.** Domyślne zachowanie `actions/checkout` (`clean: true`) uruchamia `git clean -ffdx` przed checkoutem — flaga `-x` usuwa też pliki `.gitignore`owane, czyli **skasowałaby `.env` i `nginx/certs/`** na każdym uruchomieniu workflow. To nie było w spec — odkryte przy pisaniu tego planu, krytyczne dla bezpieczeństwa produkcji.
- Brak registry (GHCR) — obrazy budowane lokalnie na serwerze przez `docker compose build` (spec decyzja #1).
- Trigger wyłącznie: `push` na `main` + `workflow_dispatch` — żadnych innych eventów (np. `pull_request`) nie dodawać, self-hosted runner na produkcyjnej maszynie nie powinien wykonywać kodu z niezmergowanych PR-ów.
- `deploy` ma `needs: test` — nie usuwać, to jedyny mechanizm chroniący przed wdrożeniem czerwonego builda (spec decyzja #4).
- Nie dodawać automatycznego rollbacku ani powiadomień (Slack/Discord) — poza zakresem spec.
- Runner zarejestrowany jako `tmask-tt-deploy-onlo` dla repo `TMaskpl/tmask-tt`, uruchomiony jako usługa systemd (`sudo ./svc.sh install && start`) — już wykonane przez użytkownika przed tym planem, Task 1 tylko to weryfikuje i dostosowuje working directory.

---

### Task 1: Weryfikacja i wyrównanie working directory runnera z istniejącą produkcją (na serwerze)

**Files:** brak zmian w repo — praca wyłącznie na serwerze przez SSH.

**Interfaces:**
- Produces: potwierdzoną ścieżkę `<RUNNER_DIR>/_work/tmask-tt/tmask-tt` jako katalog, w którym `web`/`worker`/`beat`/`nginx` znajdą działający `.env` i `nginx/certs/` — Task 2 i Task 3 zakładają, że ta ścieżka istnieje i zawiera oba pliki/katalogi.

- [ ] **Step 1: Znajdź katalog instalacji runnera i jego working directory**

SSH na serwer produkcyjny (`ssh runner@192.168.50.224`, port 22, klucz już skopiowany), następnie:
```bash
systemctl list-units --type=service | grep -i actions.runner
systemctl cat "$(systemctl list-units --type=service | grep -io 'actions\.runner\.[^ ]*\.service' | head -1)" | grep WorkingDirectory
```
Expected: linia `WorkingDirectory=<RUNNER_DIR>` — to jest katalog, w którym leży `config.sh`/`svc.sh`. Runner był rejestrowany z domyślną nazwą folderu roboczego `_work` (potwierdzone w transkrypcie rejestracji), więc GitHub Actions `checkout` umieści repo pod `<RUNNER_DIR>/_work/tmask-tt/tmask-tt`.

- [ ] **Step 2: Znajdź istniejący katalog produkcyjny (dzisiejszy ręczny deploy)**

```bash
find / -maxdepth 6 -iname "docker-compose.yml" -not -path "*/_work/*" 2>/dev/null
```
Expected: jedna ścieżka, np. `/root/tmask-tt` lub podobna — katalog, w którym dziś ręcznie odpalane jest `docker compose up -d`, zawierający `.env` i `nginx/certs/selfsigned.{crt,key}`.

- [ ] **Step 3: Potwierdź zawartość katalogu produkcyjnego**

```bash
ls -la <ISTNIEJACY_KATALOG>/.env <ISTNIEJACY_KATALOG>/nginx/certs/
docker compose -f <ISTNIEJACY_KATALOG>/docker-compose.yml ps
```
Expected: `.env` istnieje, `nginx/certs/selfsigned.crt` i `.key` istnieją, `docker compose ps` pokazuje działające kontenery (`web`, `worker`, `beat`, `nginx`, `postgres`, `redis` — status `Up`/`healthy`).

- [ ] **Step 4: Wyrównaj katalogi — jeśli `<ISTNIEJACY_KATALOG>` różni się od `<RUNNER_DIR>/_work/tmask-tt/tmask-tt`**

```bash
mkdir -p <RUNNER_DIR>/_work/tmask-tt
mv <ISTNIEJACY_KATALOG> <RUNNER_DIR>/_work/tmask-tt/tmask-tt
```
Jeśli katalog docelowy (`_work/tmask-tt/tmask-tt`) już istnieje pusty (bo runner nigdy jeszcze nie robił checkoutu) — `mv` zadziała wprost. Jeśli już zawiera pliki z wcześniejszego joba, najpierw `rm -rf <RUNNER_DIR>/_work/tmask-tt/tmask-tt`. Jeśli `<ISTNIEJACY_KATALOG>` należy do innego użytkownika niż `runner` (np. `root`, bo deploy był dotąd ręczny) — dodaj `sudo` przed `mv`/`mkdir` i na końcu `sudo chown -R runner:runner <RUNNER_DIR>/_work/tmask-tt/tmask-tt`, żeby usługa runnera (działająca jako `runner`) mogła czytać/pisać w tym katalogu.

- [ ] **Step 5: Zweryfikuj że po przeniesieniu docker compose nadal widzi te same kontenery**

```bash
cd <RUNNER_DIR>/_work/tmask-tt/tmask-tt
docker compose ps
curl -sk https://localhost/accounts/login/ -o /dev/null -w "%{http_code}\n"
```
Expected: te same kontenery co w Step 3 (przenosiny katalogu nie restartują kontenerów — Compose identyfikuje je po nazwie projektu, nie po ścieżce), `200` z curla.

- [ ] **Step 6: Zweryfikuj że użytkownik runnera ma dostęp do Dockera bez sudo**

```bash
whoami
groups
docker ps
```
Expected: `docker ps` działa bez błędu `permission denied`. Jeśli błąd: `usermod -aG docker $(whoami)`, potem `sudo ./svc.sh stop && sudo ./svc.sh start` w `<RUNNER_DIR>` (restart usługi runnera wymagany, żeby proces odziedziczył nową grupę).

_Ten task nie ma "commita" — to czysto operacyjny krok na serwerze, bez zmian w repo._

---

### Task 2: `.github/workflows/deploy.yml` — job `test`

**Files:**
- Create: `.github/workflows/deploy.yml`

**Interfaces:**
- Produces: plik workflow z jobem `test` — Task 3 dopisze do tego samego pliku job `deploy` z `needs: test`.

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

- [ ] **Step 4: Zweryfikuj w GitHub Actions UI**

Otwórz `https://github.com/TMaskpl/tmask-tt/actions` — nowy workflow run powinien się pojawić (trigger: push na `main`), job `test` powinien przejść na zielono. Jeśli runner nie podejmuje joba: sprawdź `sudo ./svc.sh status` na serwerze (Task 1 musiał zostawić usługę działającą).

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
cd <RUNNER_DIR>/_work/tmask-tt/tmask-tt   # ścieżka ustalona w Task 1
docker compose ps
git status
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

Na serwerze:
```bash
docker compose ps --format json > /tmp/before-state.json
docker inspect $(docker compose ps -q web) --format '{{.State.StartedAt}}'
```
Expected: zapisany timestamp startu obecnego kontenera `web` — punkt odniesienia do porównania.

- [ ] **Step 4: Odpal workflow ręcznie na tym branchu**

W Actions UI: **Run workflow**, branch `tmp/verify-build-safety`.

Expected: job `test` zielony (Dockerfile web-test/worker niezmieniony, tylko `web`/production dotknięty), job `deploy` czerwony na kroku `Build production images` (błąd `this-command-does-not-exist-verify-ci-safety: not found`), krok `Recreate containers` **nie wykonuje się** (poprzedni krok failował, GitHub Actions domyślnie przerywa job).

- [ ] **Step 5: Potwierdź brak przestoju na serwerze**

```bash
docker inspect $(docker compose ps -q web) --format '{{.State.StartedAt}}'
curl -sk https://localhost/accounts/login/ -o /dev/null -w "%{http_code}\n"
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
docker image prune -f
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

**Runner:** usługa systemd na serwerze produkcyjnym, nazwa `tmask-tt-deploy-onlo`. Status: `sudo ./svc.sh status` w katalogu instalacji runnera. Jeśli runner jest offline, workflow wisi w statusie "Waiting for a runner" — restart: `sudo ./svc.sh start`.

**Rollback (ręczny, brak automatycznego):**
```bash
git checkout <poprzedni-dobry-commit>
git push --force-with-lease origin main   # albo: git revert <zły-commit> && git push
```
Push uruchomi normalną ścieżkę test→deploy i odbuduje poprzednią wersję. Brak wersjonowanych obrazów/tagów — to świadomy kompromis (jeden serwer, LAN-only, mała skala).

**Czego workflow NIE rusza:** `.env` i `nginx/certs/` na serwerze (gitignored, `actions/checkout` skonfigurowany z `clean: false` właśnie po to, by ich nie skasować).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document CI/CD deployment mechanism (workflow, rollback, runner status)"
git push origin main
```

---

## Self-Review (wykonane przy pisaniu planu)

**Pokrycie spec:**
- Wariant A (self-hosted, brak registry) → Task 2, 3 ✓
- Oba joby self-hosted (korekta #2 w spec) → Task 2, 3 (`runs-on: self-hosted` w obu) ✓
- Trigger push+workflow_dispatch → Task 2 Step 1 (`on:` blok) ✓
- Testy blokują deploy → Task 3 (`needs: test`), zweryfikowane w Task 4 ✓
- Healthcheck → Task 3 Step 1 ✓
- Rollback ręczny → udokumentowany w Task 6 ✓
- Weryfikacja mechanizmu (spec sekcja "Testy/Weryfikacja", punkty 1-4) → Task 2 Step 4, Task 4, Task 5 pokrywają punkty 1-3; punkt 4 (workflow_dispatch jako redeploy) pokryty pośrednio przez Task 4/5 Step 3 (użycie Run workflow) i opisany w Task 6 dokumentacji
- Wyrównanie katalogu runnera z produkcją (otwarta kwestia ze spec) → Task 1, rozwiązane konkretnymi krokami

**Dodatkowa korekta znaleziona przy planowaniu (poza spec):** `clean: false` na `actions/checkout` — bez tego każdy deploy kasowałby `.env`/`nginx/certs/`. Dodane do Global Constraints i obu jobów.

**Poza zakresem (zgodnie ze spec, nieujęte w tym planie):** GHCR, automatyczny rollback, powiadomienia, staging, aktualizacja nieaktualnych komend testowych w `CLAUDE.md`.
