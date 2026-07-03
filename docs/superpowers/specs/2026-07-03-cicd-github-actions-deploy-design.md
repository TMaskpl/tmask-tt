# CI/CD: Deployment przez GitHub Actions (self-hosted runner) — Design

**Data:** 2026-07-03
**Status:** zatwierdzony

## Cel

Zautomatyzować deployment tmask-transporter na serwer produkcyjny (VM/LXC na Proxmox, wyłącznie w LAN, bez publicznego IP). Dziś deploy jest ręczny — ktoś loguje się na serwer i odpala `docker compose build && docker compose up -d`. Cel: `git push`/merge na `main` ma automatycznie przetestować i wdrożyć zmianę, bez ręcznej interwencji, bez otwierania portów na zewnątrz i bez VPN.

## Kontekst obecny

- Serwer docelowy: VM/LXC w LAN, brak publicznego IP. GitHub-hosted runnery (chmura GitHuba) nie mają jak się do niego połączyć bezpośrednio.
- Dostęp SSH/login do serwera już skonfigurowany przez użytkownika (poza zakresem tego spec).
- Self-hosted GitHub Actions runner **już zarejestrowany** na serwerze dla repo `TMaskpl/tmask-tt` (nazwa `tmask-tt-deploy-onlo`, domyślne etykiety `self-hosted, Linux, X64`, katalog roboczy `_work`). Ponieważ runner jest zarejestrowany na poziomie repozytorium (nie organizacji), `runs-on: self-hosted` w workflow trafia wyłącznie na tę maszynę — dodatkowa etykieta nie jest potrzebna przy jednym runnerze.
- Repo już sklonowane na serwerze w katalogu, gdzie dotąd wykonywano ręczny deploy — runner pracuje w tym samym repo (checkout robi `git fetch`/`reset`, nie nowy clone).
- `.env` na serwerze jest niewersjonowany (gitignored), zawiera `SECRET_KEY`, dane DB, `ALLOWED_HOSTS` itd. — deployment go nie rusza.
- `docker-compose.yml`: serwisy `web` (target `production`), `web-test` (target `dev`, profil `test`, ma pytest), `worker`, `beat`, `nginx`, `postgres`, `redis`. `web`/`web-test`/`worker`/`beat` mają `env_file: .env`.
- `services/web/entrypoint.sh` uruchamia `manage.py migrate --noinput` **automatycznie przy każdym starcie kontenera** `web` — osobny krok migracji w workflow jest zbędny, `docker compose up -d` go załatwia.
- Komendy testowe (potwierdzone w `docs/superpowers/specs/2026-07-02-*` i pamięci projektowej — `CLAUDE.md` w tej kwestii jest nieaktualne, sprzed splitu `requirements-prod`/`requirements-dev` z 2026-07-02):
  - Web: `docker compose --profile test run --rm web-test python -m pytest apps/ -v`
  - Worker: `docker compose run --rm worker python -m pytest tests/ -v` (worker nie był objęty splitem prod/dev, pytest zostaje w jego jedynym obrazie)

## Decyzje (zatwierdzone)

1. **Wariant A**: self-hosted runner na samej maszynie docelowej, build lokalny przez `docker compose build`, bez registry pośredniego (GHCR). Rollback ręczny (`git checkout <poprzedni commit>` + redeploy), nie automatyczny. Uzasadnienie: jeden serwer, mała skala, LAN-only — dodatkowa infrastruktura (registry, tagowanie obrazów) nie daje proporcjonalnej korzyści.
2. **Oba joby (`test` i `deploy`) działają na self-hosted runnerze**, nie tylko `deploy`. Korekta względem wstępnego ustalenia (job `test` na GitHub-hosted) odkryta podczas pisania tego spec: `web-test`/`worker` wymagają `env_file: .env`, a `.env` istnieje wyłącznie na serwerze (gitignored, nie ma go w checkout na runnerze w chmurze). Uruchomienie testów na tej samej maszynie co produkcja jest bezpieczne — pytest-django tworzy własną, odizolowaną bazę `test_<nazwa>` na tym samym Postgresie, nie dotyka danych produkcyjnych; to jest już dziś ustalony sposób odpalania testów na tym projekcie (TDD lokalnie na serwerze/hoście z tym samym `.env`).
3. **Trigger**: `push` na `main` + `workflow_dispatch` (ręczne odpalenie z zakładki Actions, do redeployu bez nowego commita, np. po ręcznym rollbacku).
4. **Testy blokują deploy**: job `deploy` ma `needs: test` — jeśli pytest (web lub worker) nie przejdzie, `deploy` się nie odpala, produkcja nietknięta.
5. **Healthcheck po deployu**: krok w workflow odpytuje `https://localhost/accounts/login/` z retry (self-signed cert → `curl -k`), workflow kończy się failem jeśli aplikacja nie odpowie w rozsądnym czasie — ale kontener **nie jest** cofany automatycznie (patrz „Poza zakresem”).

## Architektura zmian

### Nowy plik: `.github/workflows/deploy.yml`

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

      - name: Build test image (web-test)
        run: docker compose --profile test build web-test

      - name: Run web test suite
        run: docker compose --profile test run --rm web-test python -m pytest apps/ -v

      - name: Build worker image
        run: docker compose build worker

      - name: Run worker test suite
        run: docker compose run --rm worker python -m pytest tests/ -v

  deploy:
    needs: test
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4

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

Uwagi do implementacji:
- `actions/checkout@v4` w katalogu roboczym runnera (`_work/tmask-tt/tmask-tt`) — **nie** w katalogu, gdzie dziś ręcznie stoi produkcja. To oznacza, że produkcyjny `docker-compose.yml`/`nginx/certs`/`.env` muszą być dostępne (skopiowane raz) do katalogu roboczego runnera, albo runner musi być skonfigurowany tak, by `_work` wskazywało na istniejący katalog repo. **Do ustalenia w planie implementacji** — dwie opcje: (a) przenieść dzisiejszy ręczny checkout tak, by stał się katalogiem roboczym runnera, (b) skopiować `.env` i `nginx/certs/` (oba gitignored) do nowej lokalizacji przy pierwszym uruchomieniu. Plan implementacji musi to zweryfikować na żywym serwerze przed pierwszym prawdziwym deployem.
- Kolejność `test` → `deploy` na jednym runnerze wykonuje się sekwencyjnie niezależnie od `needs` (jeden runner = jeden job naraz), `needs: test` dodatkowo gwarantuje, że `deploy` nie wystartuje przy czerwonym `test`.

## Obsługa błędów

| Sytuacja | Zachowanie |
|----------|-----------|
| Testy web lub worker nie przechodzą | Job `deploy` się nie odpala (`needs: test`), workflow czerwony, produkcja nietknięta |
| `docker compose build` (w `deploy`) failuje | Stary kontener nadal działa (nie było `down`/`stop`), zero przestoju, workflow czerwony |
| `docker compose up -d` się wykonuje, ale nowy kontener crashuje po starcie | **Realne ryzyko przestoju** — stary kontener już zastąpiony. Healthcheck to wykryje i zaczerwieni workflow, ale nie cofnie automatycznie (patrz „Poza zakresem") |
| Runner offline (usługa systemd nie działa) | Workflow wisi w statusie „Waiting for a runner" w zakładce Actions — brak automatycznego alertu w MVP, wymaga ręcznej weryfikacji `sudo ./svc.sh status` na serwerze |
| Awaryjny rollback | Ręczny: `git checkout <poprzedni-dobry-commit>` na `main` (lub `git revert` + push) → workflow przejeżdża normalną ścieżką test→deploy i odbudowuje poprzednią wersję. Brak wersjonowanych obrazów/tagów (świadomy kompromis wariantu A) |

## Testy / Weryfikacja mechanizmu

Weryfikacja samego workflow (nie logiki aplikacji) przed uznaniem za gotowe:

1. Push commita bez realnej zmiany (np. komentarz) na `main` → oba joby (`test`, `deploy`) zielone w zakładce Actions, aplikacja odpowiada po deployu.
2. Celowo zepsuty test (np. tymczasowy `assert False`) na branchu → merge do `main` → potwierdzić, że `deploy` się nie odpala.
3. Celowo błędny `Dockerfile` (błąd składni) na branchu testowym → merge → `test` przechodzi, `deploy` failuje na `docker compose build`, ręczna weryfikacja na serwerze że stary kontener nadal działa (`docker compose ps`, `curl -k https://localhost`).
4. Po udanym deployu: `docker compose ps` (wszystkie kontenery `Up`/`healthy`), `.env` i `nginx/certs/` niezmienione (`git status` w katalogu produkcyjnym pokazuje tylko pliki wersjonowane).
5. `workflow_dispatch` — ręczne odpalenie z zakładki Actions bez nowego commita, potwierdzenie że działa jako redeploy.

## Poza zakresem

- GHCR / registry pośredni i wersjonowane obrazy (wariant B) — odrzucone na rzecz prostoty (decyzja #1).
- Automatyczny rollback przy nieudanym healthchecku — MVP kończy się na czerwonym workflow i ręcznej interwencji.
- Powiadomienia (Slack/Discord) o statusie deployu.
- Staging environment przed produkcją — jeden serwer, brak środowiska pośredniego.
- Aktualizacja `CLAUDE.md` (nieaktualne komendy testowe sprzed splitu `requirements-prod`/`requirements-dev`) — realny dług, ale osobne zadanie, niepowiązane z mechanizmem deploymentu.
