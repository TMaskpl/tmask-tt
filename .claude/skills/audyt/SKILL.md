---
name: audyt
description: Use when performing a full technical audit of tmask-tt — runs Codex code review, SonarQube static analysis with Quality Gate check, verifies docker compose health, then git push.
allowed-tools: [Bash, Read, Edit, Agent]
---

Wykonaj każdy etap po kolei. Nie przechodź dalej jeśli poprzedni zgłasza błędy krytyczne.

## 1. Codex — analiza kodu

Uruchom skill jako sub agent `codex:rescue` z zadaniem pełnego przeglądu kodu pod kątem:
- błędów logicznych i regresji
- podatności bezpieczeństwa (injection, brak owner filtering, niezaszyfrowane pola)
- jakości kodu (dead code, zbędne importy, niespójności)

```
Scope: services/ (cały katalog aplikacji)
Focus: bugs, security, code quality
```

Poczekaj na wynik Codexa. Jeśli zgłosi problemy krytyczne — napraw przed przejściem do kroku 2.

## 2. SonarQube — skan statyczny

Uruchom skaner z katalogu projektu (`/Users/dniemczok/Desktop/TMaskPL/tmask-tt`):

```bash
docker run --rm \
  -e SONAR_HOST_URL=http://10.254.0.1:9000 \
  -e SONAR_TOKEN=$(grep sonar.token sonar-project.properties | cut -d= -f2) \
  -v "$(pwd):/usr/src" \
  sonarsource/sonar-scanner-cli
```

Skan trwa ~2 minuty. Poczekaj na `EXECUTION SUCCESS` w logach.

## 3. Weryfikacja Quality Gate

Po zakończeniu skanu sprawdź status Quality Gate przez API:

```bash
SONAR_TOKEN=$(grep sonar.token sonar-project.properties | cut -d= -f2)
PROJECT_KEY=$(grep sonar.projectKey sonar-project.properties | cut -d= -f2)

curl -s -u "${SONAR_TOKEN}:" \
  "http://10.254.0.1:9000/api/qualitygates/project_status?projectKey=${PROJECT_KEY}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['projectStatus']['status'])"
```

**Oczekiwany wynik: `OK`**

Jeśli wynik to `ERROR` lub `WARN` — sprawdź szczegóły:

```bash
curl -s -u "${SONAR_TOKEN}:" \
  "http://10.254.0.1:9000/api/issues/search?projectKeys=${PROJECT_KEY}&severities=CRITICAL,BLOCKER&resolved=false" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
for i in d.get('issues', []):
    print(f\"{i['severity']:10} {i['component']}:{i.get('line','?')} — {i['message']}\")"
```

Napraw wszystkie BLOCKER i CRITICAL przed przejściem dalej.

## 4. Weryfikacja działania aplikacji

### 4a. Status kontenerów

```bash
docker compose ps
```

Wszystkie serwisy muszą być `healthy` (nie `starting` ani `unhealthy`):
- `postgres` — `pg_isready`
- `redis` — `redis-cli ping`
- `web` — HTTP 200 na `/accounts/login/`
- `worker` — `celery inspect ping`
- `beat` — uruchomiony

### 4b. Logi — brak błędów krytycznych

```bash
docker compose logs --tail=50 web worker beat 2>&1 | grep -iE "error|exception|traceback|critical" | grep -v "DEBUG"
```

**Oczekiwany wynik: brak wyjścia** (żadnych błędów).

Jeśli są błędy, sprawdź konkretny serwis:
```bash
docker compose logs --tail=100 <service>
```

### 4c. Smoke test HTTP

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost/accounts/login/
# Oczekiwane: 200
```

### 4d. Celery worker gotowy

```bash
docker compose exec worker celery -A tasks inspect ping --timeout 5
```

## 5. Git push

Jeśli wszystkie poprzednie kroki przeszły bez błędów krytycznych:

```bash
# Sprawdź co idzie do commita
git status
git diff --stat

# Zacommituj zmiany (jeśli są)
git add -p   # interaktywny staging — tylko celowe zmiany

# Wypchnij
git push
```

**Nie pushuj jeśli:**
- Quality Gate zwrócił `ERROR`
- Jakikolwiek kontener jest `unhealthy`
- W logach są `Traceback` lub `CRITICAL` błędy

## Podsumowanie audytu

Po zakończeniu całości zgłoś wyniki w formacie:

```
Codex:      OK / N problemów (lista)
SonarQube:  OK / ERROR (lista BLOCKER/CRITICAL)
QualityGate: OK / ERROR
Docker:     healthy / N serwisów z problemem
Logi:       czyste / N błędów
Push:       wykonany / wstrzymany (powód)
```
