# Organizacja (nazwany singleton) + tworzenie userów w UI — Design

**Data:** 2026-07-01
**Status:** zatwierdzony

## Cel

Uzupełnić system ról (Admin/Operator/Read-only, zbudowany w `2026-07-01-org-roles-design.md`) o:

1. **Nazwaną organizację** — jeden byt `Organization` z polem `name`, edytowalny przez Admina, widoczny w UI (navbar + strona zarządzania userami).
2. **Tworzenie kont użytkowników z poziomu UI apki** — dziś konta powstają wyłącznie przez Django admin/CLI (`createsuperuser`); Admin ma dostać formularz `[ + DODAJ USERA ]` bezpośrednio w panelu.

To warstwa czysto addytywna — nie zmienia niczego w istniejącym systemie ról, dekoratorach `require_role`, ani widoczności Connections/Flows/Scheduler/Transfers (nadal jedna wspólna pula, bo jest dokładnie jedna organizacja).

## Kontekst obecny

- `apps/accounts/models.py::User` ma pole `role` (`admin`/`operator`/`readonly`), zbudowane w poprzednim spec.
- `apps/accounts/views.py::users_list` (Admin-only) renderuje tabelę wszystkich userów z możliwością zmiany roli (`change_user_role`, Task 10 poprzedniego spec).
- Brak jakiegokolwiek modelu organizacji — cała instalacja to jeden domyślny, niejawny "zespół".
- Brak formularza tworzenia konta w UI — `apps/accounts/urls.py` nie ma takiego endpointu; jedyne sposoby to `python manage.py createsuperuser` lub Django admin (`/admin/`).
- `apps/accounts/forms.py` zawiera `LoginForm` i `ProfileForm` (proste `forms.Form`/`forms.ModelForm`, ręcznie renderowane w CRT-stylowych szablonach — brak django-crispy-forms czy podobnych).

## Decyzje (zatwierdzone)

1. **Singleton, nie multi-tenant.** `Organization` ma zawsze dokładnie jeden wiersz w bazie. Brak UI do tworzenia/usuwania organizacji — tylko edycja nazwy istniejącej. Odrzucono pełny multi-tenant jako przedwczesną komplikację (ta sama decyzja co w poprzednim spec, teraz jawnie potwierdzona dla samego bytu `Organization`).
2. **Tworzenie userów przez Admina w UI**, oparte o wbudowany `django.contrib.auth.forms.UserCreationForm` (Django obsługuje hashowanie hasła + `AUTH_PASSWORD_VALIDATORS` bez dodatkowego kodu). Rozszerzony o `email` i `role`.
3. **Brak zmian w widoczności zasobów** — Connections/Flows/Scheduler/Transfers pozostają współdzielone tak jak dziś; `Organization` nie jest FK-iem na żadnym z tych modeli.
4. **Brak maila powitalnego / self-service** — Admin tworzy konto i przekazuje hasło userowi poza systemem (spójne z obecnym brakiem SMTP-dependent onboardingu poza istniejącymi powiadomieniami transferowymi).

## Architektura zmian

### 1. Nowa appka `apps/organization` (model + widok ustawień)

Osobna appka, żeby nie rozdymać `apps/accounts` o niepowiązaną domenę:

```
apps/organization/
├── models.py       — Organization(name)
├── migrations/0001_initial.py  — model + RunPython tworzący domyślny wiersz
├── forms.py        — OrganizationForm (ModelForm, pole name)
├── views.py        — organization_settings (Admin-only, GET/POST)
├── urls.py         — /organization/  (app_name='organization')
└── tests/
```

`services/web/config/settings/base.py::INSTALLED_APPS` — dodać `'apps.organization'`.
`services/web/config/urls.py` — dodać `path('organization/', include('apps.organization.urls'))`.

**Model:**
```python
from django.db import models

class Organization(models.Model):
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
```

**Singleton helper** (w `models.py`, prosta funkcja — bez zewnętrznych bibliotek typu django-solo, YAGNI; umieszczona w `models.py`, bo `context_processors.py` musi ją importować bez zależności od `views.py`):
```python
def get_organization() -> Organization:
    org, _ = Organization.objects.get_or_create(pk=1, defaults={'name': 'Organizacja'})
    return org
```
`pk=1` wymuszony jawnie — jedyny wiersz zawsze ma ten sam klucz, upraszcza `get_or_create` bez dodatkowej logiki "znajdź pierwszy".

**Migracja danych** (`0001_initial.py`, `RunPython` po `CreateModel`):
```python
def create_default_organization(apps, schema_editor):
    Organization = apps.get_model('organization', 'Organization')
    Organization.objects.get_or_create(pk=1, defaults={'name': 'Organizacja'})
```

**Widok:**
```python
@require_role(ROLE_ADMIN)
def organization_settings(request):
    org = get_organization()
    form = OrganizationForm(request.POST or None, instance=org)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Nazwa organizacji zaktualizowana.')
        return redirect('organization:settings')
    return render(request, 'organization/settings.html', {'form': form, 'organization': org})
```

### 2. Tworzenie userów w UI (`apps/accounts`)

**Forma** (`apps/accounts/forms.py`, nowa klasa obok `LoginForm`/`ProfileForm`):
```python
from django.contrib.auth.forms import UserCreationForm

class UserCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ['username', 'email', 'role']
        labels = {'email': 'Adres email', 'role': 'Rola'}
```
`UserCreationForm` już dostarcza `password1`/`password2` z walidacją zgodności i siły hasła (`AUTH_PASSWORD_VALIDATORS` w `settings/base.py`) — brak potrzeby ręcznego kodu hashującego.

**Widok** (`apps/accounts/views.py`, obok `users_list`/`change_user_role`):
```python
@require_role(ROLE_ADMIN)
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        messages.success(request, f'Użytkownik {user.username} utworzony z rolą {user.get_role_display()}.')
        return redirect(USERS_LIST)
    return render(request, 'users/create.html', {'form': form})
```

**URL** (`apps/accounts/urls.py`):
```python
path('users/new/', views.user_create, name='user_create'),
```
(wstawić przed `users/<int:pk>/role/`, żeby `new/` nie kolidowało z `<int:pk>` — Django rozróżnia je poprawnie niezależnie od kolejności dzięki typom konwertera, ale kolejność „bardziej specyficzne przed ogólnym” jest tu praktyką defensywną, nie wymogiem).

### 3. UI — szablony

**`templates/users/list.html`** (rozszerzenie istniejącego, z poprzedniego spec):
- Nagłówek boxa zamiast statycznego `USER MANAGEMENT` → `{{ organization.name|upper }} — CZŁONKOWIE`, z linkiem `[ EDYTUJ NAZWĘ ]` do `organization:settings`.
- Nad tabelą: przycisk `[ + DODAJ USERA ]` → `accounts:user_create`.
- Widok `users_list` przekazuje `organization` w kontekście (import `get_organization` z `apps.organization.models`).

**`templates/users/create.html`** (nowy, wzorowany na `connections/form.html` — pojedynczy box z formularzem, styl CRT):
```html
{% extends "base.html" %}
{% block title %}NOWY USER — ADMIN{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">NOWY UŻYTKOWNIK</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}<div class="msg-error">{{ form.non_field_errors }}</div>{% endif %}
    {% for field in form %}
    <div class="field">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      {% if field.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ field.errors }}</div>{% endif %}
    </div>
    {% endfor %}
    <button type="submit" class="btn">[ UTWÓRZ ]</button>
  </form>
</div>
{% endblock %}
```

**`templates/organization/settings.html`** (nowy, analogiczny prosty box).

**`base.html`** — navbar, obok brandu:
```html
<a href="{% url 'dashboard:index' %}" class="logo ...">[ TMASK-TRANSPORTER ]</a>
<span class="org-name">{{ request.organization.name|default:"" }}</span>
```
Nazwa organizacji musi być dostępna globalnie bez powtarzania `get_organization()` w każdym widoku — najprościej przez lekki **context processor**:
```python
# apps/organization/context_processors.py
from .models import get_organization

def organization(request):
    if not request.user.is_authenticated:
        return {}
    return {'organization': get_organization()}
```
Dodać do `TEMPLATES[0]['OPTIONS']['context_processors']` w `settings/base.py`. Wtedy `base.html` używa `{{ organization.name }}` (bez `request.`), spójnie z resztą kontekstu.

## Obsługa błędów

| Sytuacja | Zachowanie |
|----------|-----------|
| Operator/Read-only próbuje otworzyć `/accounts/users/new/` lub `/organization/` | `403 PermissionDenied` (`require_role(ROLE_ADMIN)`) |
| Formularz tworzenia usera — zajęty `username` | Standardowy błąd walidacji Django (`UserCreationForm` już to obsługuje) |
| Formularz tworzenia usera — niezgodne `password1`/`password2` | Standardowy błąd walidacji Django |
| Hasło niespełniające `AUTH_PASSWORD_VALIDATORS` | Standardowy błąd walidacji Django |
| Pusta nazwa organizacji w formularzu ustawień | Błąd walidacji (`CharField` wymagane domyślnie) |
| Brak wiersza `Organization` w bazie (np. świeża instalacja bez migracji danych) | `get_organization()` tworzy go leniwie przez `get_or_create(pk=1, ...)` — nigdy nie 500 |

## Testy

**`apps/organization`:**
- `get_organization()` — tworzy domyślny wiersz przy pierwszym wywołaniu, zwraca istniejący przy kolejnych (idempotencja `pk=1`)
- `organization_settings` — Admin może zmienić nazwę (200 → redirect, `Organization.objects.get(pk=1).name` zaktualizowane); Operator/Read-only → 403
- Migracja danych — `RunPython` tworzy wiersz `pk=1` z domyślną nazwą

**`apps/accounts` (nowe testy obok `TestChangeUserRole`):**
- `user_create` — Admin tworzy usera z rolą `operator`, redirect, nowy user istnieje z poprawną rolą i zahashowanym hasłem (`check_password`)
- Operator/Read-only → 403 na `GET`/`POST` `/accounts/users/new/`
- Duplikat `username` → błąd walidacji, brak utworzenia drugiego usera
- Niezgodne hasła → błąd walidacji

**Context processor:**
- Zalogowany user w dowolnym widoku → `organization` w kontekście z poprawną nazwą
- Niezalogowany (np. strona logowania) → brak `organization` w kontekście (context processor zwraca `{}`), `base.html`'s `{% if user.is_authenticated %}` i tak nie renderuje navbaru dla anonima, więc brak ryzyka `AttributeError` w szablonie

## Poza zakresem

- Multi-tenant / wiele organizacji — odrzucone (decyzja #1), spójne z poprzednim spec.
- Zaproszenia email / self-service rejestracja — odrzucone (decyzja #4).
- Usuwanie organizacji lub tworzenie drugiej — brak UI do tego, singleton wymuszony konwencją `pk=1`.
- Usuwanie/dezaktywacja userów z poziomu nowego UI — `is_active` toggle nie wchodzi w zakres tego spec (User Management już pokazuje `is_active`, ale bez akcji zmiany — pozostaje jak dziś).
- Zmiana modelu widoczności Connections/Flows/Scheduler/Transfers — bez zmian, nadal współdzielone globalnie.
