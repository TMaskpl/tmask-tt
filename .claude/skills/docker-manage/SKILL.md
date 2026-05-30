---
name: docker-manage
description: Zarządzanie infrastrukturą Docker Compose projektu tmask-tt — migracje, testy, logi, rebuild.
allowed-tools: [Bash]
---

Operacje na infrastrukturze tmask-tt. Nazwy serwisów: `web`, `worker`, `beat`, `redis`, `postgres`, `nginx`.

## Migracje Django

```bash
docker compose run --rm web python manage.py makemigrations
docker compose run --rm web python manage.py migrate
```

Jeśli dodajesz nową app — najpierw upewnij się, że jest w `INSTALLED_APPS` w `services/web/config/settings/base.py`.

## Testy

```bash
# Web (apps/ — modele, widoki, formularze)
docker compose run --rm web python -m pytest apps/ -v

# Worker (tasks + moduły sftp/rsync/relay)
docker compose run --rm worker python -m pytest tests/ -v

# Konkretny plik
docker compose run --rm web python -m pytest apps/flows/tests/test_views.py -v
```

## Rebuild po zmianach

```bash
# Po zmianie kodu Python / Dockerfile / requirements.txt — WYMAGANY rebuild
docker compose build web && docker compose up -d web
docker compose build worker && docker compose up -d worker beat

# Po zmianie static CSS/JS — przebuduj nginx (nginx serwuje pliki statyczne przez wolumin)
docker compose build web nginx && docker compose up -d web nginx
```

## Baza danych

```bash
# Sprawdzenie gotowości
docker compose exec postgres pg_isready

# Psql (zmienne z .env)
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB

# Reset bazy (DESTRUKCYJNE — zatrzymuje kontenery i usuwa wolumin)
docker compose down -v
docker compose up -d
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
```

## Logi i diagnostyka

```bash
docker compose logs -f web worker beat
docker compose logs -f web           # tylko web
docker compose ps                    # status serwisów i healthchecków
```

## Celery

```bash
# Sprawdź czy worker odpowiada
docker compose exec worker celery -A tasks inspect ping

# Uruchom task ręcznie (z shella Django)
docker compose run --rm web python manage.py shell
# >>> from apps.transfers.models import TransferJob; ...
```

## Bezpieczeństwo przed resetem

Przed `docker compose down -v` **zawsze** sprawdź czy `.env` jest poza repozytorium i zawiera aktualne klucze (`SECRET_KEY`, `FIELD_ENCRYPTION_KEY`). Utrata klucza Fernet = nieodwracalne dane zaszyfrowane w Postgres.
