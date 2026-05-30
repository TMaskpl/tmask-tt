---
name: new-module
description: Tworzy nowy moduł w tmask-tt — Django app (web) lub moduł transferu (worker).
argument-hint: "[module_name] [app|transfer-module]"
---

Projekt nie ma frontendu React ani DRF. Stack: Django 5 templates + HTMX, Celery worker z modułami transfer.

## Django app (nowa sekcja funkcjonalna)

Wzorzec: `services/web/apps/flows/` (CRUD Flow + uruchamianie).

```bash
# 1. Utwórz app
docker compose run --rm web python manage.py startapp $0 apps/$0

# 2. Dodaj do INSTALLED_APPS w services/web/config/settings/base.py
#    'apps.$0',

# 3. Podłącz URL w services/web/config/urls.py
#    path('$0/', include('apps.$0.urls')),
```

Struktura nowej app powinna wyglądać jak `apps/flows/`:
```
apps/$0/
├── __init__.py
├── admin.py
├── forms.py        — ModelForm (bez serializers — nie ma DRF)
├── migrations/
│   └── __init__.py
├── models.py
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   └── test_views.py
├── urls.py
└── views.py
```

### Izolacja i widoczność danych

- Widoki **ZAWSZE** filtrują QuerySet po `owner=request.user` — użytkownik widzi tylko swoje zasoby
- Import modeli z innych apps jest dozwolony (np. `from apps.connections.models import Connection`)
- Unikaj tylko importów cyklicznych (gdy A importuje B i B importuje A)

### Szablony

Umieść w `services/web/templates/$0/` i dziedzicz z `base.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="box">
  <span class="box-title">TYTUŁ SEKCJI</span>
  <!-- treść -->
</div>
{% endblock %}
```

## Moduł transferu (worker)

Wzorzec: `services/worker/modules/relay/` (RelayHandler).

```
services/worker/modules/$0/
├── __init__.py
├── config.py     — stałe konfiguracyjne (timeout, retry, progi)
└── handler.py    — klasa $0Handler z metodą execute(log_callback=None)
```

Handler musi:
- Przyjmować `params: dict` w konstruktorze
- Mieć metodę `execute(log_callback=None)` gdzie `log_callback(level, message)`
- Rzucać dedykowany wyjątek `$0TransferError` przy niepowodzeniu
- Być zarejestrowany w `services/worker/tasks.py` w `execute_transfer()`

Testy workera umieszczaj w `services/worker/tests/test_$0_handler.py`.

## Weryfikacja po dodaniu

```bash
# App Django
docker compose run --rm web python manage.py makemigrations $0
docker compose run --rm web python manage.py migrate
docker compose run --rm web python -m pytest apps/$0/ -v

# Moduł workera
docker compose run --rm worker python -m pytest tests/test_$0_handler.py -v
```
