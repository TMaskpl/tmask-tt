---
name: pre-deploy
description: Checklist przed wdrożeniem tmask-tt na serwer produkcyjny — .env, testy, migracje, rebuild, healthchecki.
allowed-tools: [Bash, Read]
---

Wykonaj jako każdy krok po kolei. Nie wdrażaj jeśli którykolwiek punkt nie przejdzie.

## 1. Walidacja .env

Sprawdź że plik `.env` zawiera wszystkie wymagane zmienne z prawdziwymi wartościami:

```bash
# Czy plik istnieje i nie jest przykładem
test -f .env && echo OK || echo "BRAK .env"

# Kluczowe zmienne — każda musi mieć wartość (nie placeholder)
grep -E "^SECRET_KEY=.{20,}" .env          && echo "SECRET_KEY OK"      || echo "SECRET_KEY BRAKUJE"
grep -E "^FIELD_ENCRYPTION_KEY=.{30,}" .env && echo "FERNET_KEY OK"     || echo "FERNET_KEY BRAKUJE"
grep "^DEBUG=False" .env                    && echo "DEBUG OK"           || echo "DEBUG=False WYMAGANE"
grep -E "^ALLOWED_HOSTS=.+" .env            && echo "ALLOWED_HOSTS OK"   || echo "ALLOWED_HOSTS BRAKUJE"
grep -E "^POSTGRES_PASSWORD=.+" .env        && echo "DB_PASSWORD OK"     || echo "DB_PASSWORD BRAKUJE"
```

**Uwaga:** Utrata `FIELD_ENCRYPTION_KEY` oznacza trwałą utratę wszystkich zaszyfrowanych haseł SSH i kluczy prywatnych w bazie. Zrób backup `.env` przed wdrożeniem.

## 2. .env nie może trafić do repozytorium

```bash
grep "^\.env$" .gitignore && echo "OK — .env w .gitignore" || echo "BŁĄD — dodaj .env do .gitignore"
git status --short | grep "\.env" && echo "BŁĄD — .env widoczny w git" || echo "OK — .env poza gitem"
```

## 3. Testy

```bash
# Muszą przejść wszystkie przed wdrożeniem
docker compose run --rm web python -m pytest apps/ -v
docker compose run --rm worker python -m pytest tests/ -v
```

Nie wdrażaj jeśli jakikolwiek test fail.

## 4. Migracje

```bash
# Sprawdź czy są niezastosowane migracje
docker compose run --rm web python manage.py showmigrations | grep "\[ \]"
# Jeśli lista niepusta — zastosuj:
docker compose run --rm web python manage.py migrate
```

## 5. Rebuild kontenerów

```bash
docker compose build web worker beat nginx
docker compose up -d
```

Po rebuildzie poczekaj ~30s na inicjalizację serwisów przed sprawdzeniem healthchecków.

## 6. Weryfikacja healthchecków

```bash
docker compose ps
```

Wszystkie serwisy muszą mieć status `healthy` (nie `starting` ani `unhealthy`):
- `postgres` — `pg_isready`
- `redis` — `redis-cli ping`
- `web` — HTTP 200 na `/accounts/login/`
- `worker` — `celery inspect ping`

Jeśli serwis nie przechodzi healthcheka:

```bash
docker compose logs --tail=50 <service>
```

## 7. Smoke test po wdrożeniu

```bash
# Aplikacja odpowiada
curl -s -o /dev/null -w "%{http_code}" http://localhost/accounts/login/
# Oczekiwane: 200

# Celery worker gotowy
docker compose exec worker celery -A tasks inspect ping --timeout 5
```

## 8. Backup bazy przed wdrożeniem (jeśli aktualizujesz istniejące dane)

```bash
docker compose exec postgres pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup_$(date +%Y%m%d_%H%M).sql
```
