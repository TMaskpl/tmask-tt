# Organization Entity + User Creation UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a named, singleton `Organization` entity (editable by Admin, shown in the UI) and an in-app user-creation form for Admins, layered on top of the already-built role system (`admin`/`operator`/`readonly`).

**Architecture:** New `apps.organization` Django app holding a singleton `Organization` model (`pk=1` convention) plus an Admin-only settings view. A context processor exposes `organization` to every authenticated template. `apps.accounts` gets a new `UserCreateForm` (built on Django's `UserCreationForm`) and view, wired next to the existing role-management page.

**Tech Stack:** Django 5.x, pytest + pytest-django, Docker Compose.

## Global Constraints

- `Organization` is a singleton — exactly one row, always at `pk=1`. No UI to create a second one or delete the existing one.
- `get_organization()` lives in `apps/organization/models.py` (not `views.py`) because the context processor imports it independently of any view.
- No self-registration, no email invites — Admin creates accounts directly; password is communicated out-of-band.
- Password validation reuses Django's built-in `UserCreationForm` (`password1`/`password2`, `AUTH_PASSWORD_VALIDATORS` from `services/web/config/settings/base.py:73-76`: `UserAttributeSimilarityValidator`, `MinimumLengthValidator` — minimum 8 characters, not too similar to username). Do not write custom password-hashing code.
- No changes to Connections/Flows/Scheduler/Transfers visibility — `Organization` is not an FK on any of those models.
- Polish UI copy, consistent with existing CRT-style templates (see `services/web/templates/connections/form.html` and `services/web/templates/users/list.html` for the established box/field/button markup pattern).

---

### Task 1: `apps.organization` app — model, migration, singleton helper

**Files:**
- Create: `services/web/apps/organization/__init__.py` (empty)
- Create: `services/web/apps/organization/apps.py`
- Create: `services/web/apps/organization/models.py`
- Create: `services/web/apps/organization/migrations/__init__.py` (empty)
- Create: `services/web/apps/organization/migrations/0001_initial.py`
- Create: `services/web/apps/organization/tests/__init__.py` (empty)
- Create: `services/web/apps/organization/tests/test_models.py`
- Modify: `services/web/config/settings/base.py:10-27` (`INSTALLED_APPS`)

**Interfaces:**
- Produces: `Organization` model (`name: str`, `created_at: datetime`), `get_organization() -> Organization` in `apps.organization.models`. Task 2's view, Task 3's context processor, and Task 5's template all call `get_organization()`.

- [ ] **Step 1: Write the failing test**

Create `services/web/apps/organization/tests/test_models.py`:

```python
import pytest


@pytest.mark.django_db
class TestGetOrganization:
    def test_creates_default_organization_on_first_call(self):
        from apps.organization.models import Organization, get_organization
        assert Organization.objects.count() == 0
        org = get_organization()
        assert org.pk == 1
        assert org.name == 'Organizacja'
        assert Organization.objects.count() == 1

    def test_returns_same_row_on_subsequent_calls(self):
        from apps.organization.models import get_organization
        first = get_organization()
        first.name = 'Acme Corp'
        first.save()
        second = get_organization()
        assert second.pk == first.pk
        assert second.name == 'Acme Corp'


@pytest.mark.django_db
class TestOrganizationModel:
    def test_str_returns_name(self):
        from apps.organization.models import Organization
        org = Organization.objects.create(pk=1, name='Test Org')
        assert str(org) == 'Test Org'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/organization/tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.organization'`

- [ ] **Step 3: Create the app scaffold**

Create `services/web/apps/organization/__init__.py` (empty file).

Create `services/web/apps/organization/apps.py`:
```python
from django.apps import AppConfig


class OrganizationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.organization'
    label = 'organization'
```

Create `services/web/apps/organization/models.py`:
```python
from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


def get_organization() -> Organization:
    org, _ = Organization.objects.get_or_create(pk=1, defaults={'name': 'Organizacja'})
    return org
```

Create `services/web/apps/organization/migrations/__init__.py` (empty file).

- [ ] **Step 4: Register the app**

In `services/web/config/settings/base.py`, change:
```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_celery_beat',
    'django_celery_results',
    'django_htmx',
    'apps.accounts',
    'apps.connections',
    'apps.transfers',
    'apps.scheduler',
    'apps.flows',
    'apps.api',
    'apps.dashboard',
]
```
to:
```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_celery_beat',
    'django_celery_results',
    'django_htmx',
    'apps.accounts',
    'apps.connections',
    'apps.transfers',
    'apps.scheduler',
    'apps.flows',
    'apps.api',
    'apps.dashboard',
    'apps.organization',
]
```

- [ ] **Step 5: Generate the migration**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python manage.py makemigrations organization --name initial`

This creates `services/web/apps/organization/migrations/0001_initial.py` with a `CreateModel` for `Organization`. Open it and add a `RunPython` data migration after `CreateModel`, so a fresh install always has the default row without relying on `get_organization()`'s lazy creation:

```python
from django.db import migrations, models


def create_default_organization(apps, schema_editor):
    Organization = apps.get_model('organization', 'Organization')
    Organization.objects.get_or_create(pk=1, defaults={'name': 'Organizacja'})


def remove_default_organization(apps, schema_editor):
    Organization = apps.get_model('organization', 'Organization')
    Organization.objects.filter(pk=1, name='Organizacja').delete()


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Organization',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.RunPython(create_default_organization, remove_default_organization),
    ]
```
(Keep the auto-generated `CreateModel` block exactly as `makemigrations` produced it — the fields shown above should match; only add the `RunPython` operation and its two functions.)

- [ ] **Step 6: Run migration and tests**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python manage.py migrate organization`
Expected: `Applying organization.0001_initial... OK`

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/organization/tests/test_models.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add services/web/apps/organization/ services/web/config/settings/base.py
git commit -m "feat: add Organization singleton model with default-row migration"
```

---

### Task 2: Organization settings view (Admin-only)

**Files:**
- Create: `services/web/apps/organization/forms.py`
- Create: `services/web/apps/organization/views.py`
- Create: `services/web/apps/organization/urls.py`
- Create: `services/web/templates/organization/settings.html`
- Create: `services/web/apps/organization/tests/test_views.py`
- Modify: `services/web/config/urls.py`

**Interfaces:**
- Consumes: `get_organization()` (Task 1), `require_role`, `ROLE_ADMIN` from `apps.accounts.permissions`/`apps.accounts.models` (already built in the org-roles feature, merged earlier on this branch).
- Produces: URL `organization:settings` (`GET/POST /organization/`). Task 5's template links to it.

- [ ] **Step 1: Write the failing test**

Create `services/web/apps/organization/tests/test_views.py`:

```python
import pytest


@pytest.mark.django_db
class TestOrganizationSettings:
    def test_admin_can_view_settings_page(self, admin_client):
        resp = admin_client.get('/organization/')
        assert resp.status_code == 200

    def test_admin_can_rename_organization(self, admin_client):
        from apps.organization.models import get_organization
        resp = admin_client.post('/organization/', {'name': 'Acme Corp'})
        assert resp.status_code == 302
        assert get_organization().name == 'Acme Corp'

    def test_operator_cannot_view_settings_page(self, auth_client):
        resp = auth_client.get('/organization/')
        assert resp.status_code == 403

    def test_readonly_cannot_rename_organization(self, readonly_client):
        resp = readonly_client.post('/organization/', {'name': 'Hacked'})
        assert resp.status_code == 403

    def test_empty_name_rejected(self, admin_client):
        from apps.organization.models import get_organization
        original_name = get_organization().name
        resp = admin_client.post('/organization/', {'name': ''})
        assert resp.status_code == 200
        assert get_organization().name == original_name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/organization/tests/test_views.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.organization.urls'` (or a 404, once the app is registered but no URL exists — either way, not yet 200/302/403 as expected)

- [ ] **Step 3: Implement the form and view**

Create `services/web/apps/organization/forms.py`:
```python
from django import forms
from .models import Organization


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name']
        labels = {'name': 'Nazwa organizacji'}
```

Create `services/web/apps/organization/views.py`:
```python
from django.contrib import messages
from django.shortcuts import render, redirect

from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN
from .forms import OrganizationForm
from .models import get_organization


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

Create `services/web/apps/organization/urls.py`:
```python
from django.urls import path
from . import views

app_name = 'organization'

urlpatterns = [
    path('', views.organization_settings, name='settings'),
]
```

- [ ] **Step 4: Wire the URL into the project**

In `services/web/config/urls.py`, change:
```python
urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('connections/', include('apps.connections.urls')),
    path('flows/', include('apps.flows.urls')),
    path('transfers/', include('apps.transfers.urls')),
    path('scheduler/', include('apps.scheduler.urls')),
    path('api/', include('apps.api.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('', RedirectView.as_view(url='/transfers/', permanent=False)),
]
```
to:
```python
urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('connections/', include('apps.connections.urls')),
    path('flows/', include('apps.flows.urls')),
    path('transfers/', include('apps.transfers.urls')),
    path('scheduler/', include('apps.scheduler.urls')),
    path('api/', include('apps.api.urls')),
    path('dashboard/', include('apps.dashboard.urls')),
    path('organization/', include('apps.organization.urls')),
    path('', RedirectView.as_view(url='/transfers/', permanent=False)),
]
```

- [ ] **Step 5: Create the template**

Create `services/web/templates/organization/settings.html`:
```html
{% extends "base.html" %}
{% block title %}ORGANIZACJA — ADMIN{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">USTAWIENIA ORGANIZACJI</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error" style="margin-bottom:1rem;">
      {% for error in form.non_field_errors %}&gt; {{ error }}<br>{% endfor %}
    </div>
    {% endif %}
    {% for field in form %}
    <div class="field">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      {% if field.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ field.errors }}</div>{% endif %}
    </div>
    {% endfor %}
    <button type="submit" class="btn">[ ZAPISZ ]</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/organization/ -v`
Expected: all PASS (8 passed: 3 from Task 1 + 5 from this task)

- [ ] **Step 7: Commit**

```bash
git add services/web/apps/organization/forms.py services/web/apps/organization/views.py services/web/apps/organization/urls.py services/web/templates/organization/settings.html services/web/apps/organization/tests/test_views.py services/web/config/urls.py
git commit -m "feat: add admin-only organization settings view"
```

---

### Task 3: Context processor — organization name available in every template

**Files:**
- Create: `services/web/apps/organization/context_processors.py`
- Modify: `services/web/config/settings/base.py:44-56` (`TEMPLATES`)
- Modify: `services/web/templates/base.html`
- Create: `services/web/apps/organization/tests/test_context_processors.py`

**Interfaces:**
- Consumes: `get_organization()` (Task 1).
- Produces: `organization` key in template context for authenticated requests, used by `base.html` (this task) and `templates/users/list.html` (Task 5).

- [ ] **Step 1: Write the failing test**

Create `services/web/apps/organization/tests/test_context_processors.py`:

```python
import pytest


@pytest.mark.django_db
class TestOrganizationContextProcessor:
    def test_authenticated_request_gets_organization_name_in_navbar(self, auth_client):
        from apps.organization.models import get_organization
        get_organization()  # ensure the row exists with default name
        resp = auth_client.get('/transfers/')
        assert b'Organizacja' in resp.content

    def test_anonymous_request_does_not_crash(self, client):
        resp = client.get('/accounts/login/')
        assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/organization/tests/test_context_processors.py -v`
Expected: FAIL — `test_authenticated_request_gets_organization_name_in_navbar` fails because `base.html` doesn't render the org name yet (`b'Organizacja' in resp.content` is False).

- [ ] **Step 3: Implement the context processor**

Create `services/web/apps/organization/context_processors.py`:
```python
from .models import get_organization


def organization(request):
    if not request.user.is_authenticated:
        return {}
    return {'organization': get_organization()}
```

- [ ] **Step 4: Register the context processor**

In `services/web/config/settings/base.py`, change:
```python
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
```
to:
```python
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.organization.context_processors.organization',
            ],
```

- [ ] **Step 5: Render the organization name in the navbar**

In `services/web/templates/base.html`, find the nav's brand link:
```html
    <a href="{% url 'dashboard:index' %}" class="logo {% if request.resolver_match.app_name == 'dashboard' %}active{% endif %}" title="Dashboard">[ TMASK-TRANSPORTER ]</a>
```
Add the organization name directly after it:
```html
    <a href="{% url 'dashboard:index' %}" class="logo {% if request.resolver_match.app_name == 'dashboard' %}active{% endif %}" title="Dashboard">[ TMASK-TRANSPORTER ]</a>
    <span class="org-name">{{ organization.name }}</span>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/organization/ -v`
Expected: all PASS (10 passed).

Run the full suite once to confirm no template-rendering regressions on unrelated pages (the context processor runs on every request):
Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/ -q`
Expected: all PASS, same count as before plus the 10 new organization tests.

- [ ] **Step 7: Commit**

```bash
git add services/web/apps/organization/context_processors.py services/web/config/settings/base.py services/web/templates/base.html services/web/apps/organization/tests/test_context_processors.py
git commit -m "feat: show organization name in navbar via context processor"
```

---

### Task 4: In-app user creation (Admin-only)

**Files:**
- Modify: `services/web/apps/accounts/forms.py`
- Modify: `services/web/apps/accounts/views.py`
- Modify: `services/web/apps/accounts/urls.py`
- Create: `services/web/templates/users/create.html`
- Modify: `services/web/apps/accounts/tests/test_views.py`

**Interfaces:**
- Consumes: `require_role`, `ROLE_ADMIN` (already present in `apps.accounts`, from the earlier org-roles feature on this same branch).
- Produces: URL `accounts:user_create` (`GET/POST /accounts/users/new/`). Task 5's template links to it.

This task is independent of Tasks 1-3 (touches `apps.accounts`, not `apps.organization`) and can be implemented in either order relative to them, but Task 5 needs both this task's URL and Task 2's URL, so it must come after both.

- [ ] **Step 1: Write the failing test**

Add to `services/web/apps/accounts/tests/test_views.py` (new test class):

```python
@pytest.mark.django_db
class TestUserCreate:
    def test_admin_can_create_user(self, admin_client, django_user_model):
        resp = admin_client.post('/accounts/users/new/', {
            'username': 'newoperator',
            'email': 'newoperator@example.com',
            'role': 'operator',
            'password1': 'a-decent-password-1',
            'password2': 'a-decent-password-1',
        })
        assert resp.status_code == 302
        user = django_user_model.objects.get(username='newoperator')
        assert user.role == 'operator'
        assert user.email == 'newoperator@example.com'
        assert user.check_password('a-decent-password-1')

    def test_operator_cannot_create_user(self, auth_client):
        resp = auth_client.get('/accounts/users/new/')
        assert resp.status_code == 403

    def test_readonly_cannot_create_user(self, readonly_client):
        resp = readonly_client.post('/accounts/users/new/', {
            'username': 'x', 'password1': 'a-decent-password-1', 'password2': 'a-decent-password-1', 'role': 'operator',
        })
        assert resp.status_code == 403

    def test_duplicate_username_rejected(self, admin_client, regular_user):
        resp = admin_client.post('/accounts/users/new/', {
            'username': regular_user.username,
            'email': 'dup@example.com',
            'role': 'operator',
            'password1': 'a-decent-password-1',
            'password2': 'a-decent-password-1',
        })
        assert resp.status_code == 200
        assert resp.context['form'].errors

    def test_mismatched_passwords_rejected(self, admin_client, django_user_model):
        resp = admin_client.post('/accounts/users/new/', {
            'username': 'mismatched',
            'email': 'mismatched@example.com',
            'role': 'operator',
            'password1': 'a-decent-password-1',
            'password2': 'a-different-password-2',
        })
        assert resp.status_code == 200
        assert not django_user_model.objects.filter(username='mismatched').exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/accounts/tests/test_views.py::TestUserCreate -v`
Expected: FAIL with 404 (`/accounts/users/new/` doesn't exist yet)

- [ ] **Step 3: Add the form**

In `services/web/apps/accounts/forms.py`, add the import and new form class. Change the top of the file from:
```python
from django import forms
from django.contrib.auth import get_user_model
from utils.url_validator import block_private_url
```
to:
```python
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from utils.url_validator import block_private_url
```

Add at the end of the file:
```python
class UserCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ['username', 'email', 'role']
        labels = {'email': 'Adres email', 'role': 'Rola'}
```

- [ ] **Step 4: Add the view**

In `services/web/apps/accounts/views.py`, add `UserCreateForm` to the existing form import:
```python
from .forms import LoginForm, ProfileForm
```
becomes:
```python
from .forms import LoginForm, ProfileForm, UserCreateForm
```

Add the view next to `change_user_role` (from the earlier org-roles feature already on this branch):
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
(`USERS_LIST`, `require_role`, `ROLE_ADMIN`, `messages`, `render`, `redirect` are all already imported/defined in this file from the earlier org-roles work — no new imports needed beyond `UserCreateForm` above.)

- [ ] **Step 5: Add the URL**

In `services/web/apps/accounts/urls.py`, add the new route. Current file has:
```python
    path('users/', views.users_list, name='users'),
    path('users/<int:pk>/role/', views.change_user_role, name='change_user_role'),
```
Change to:
```python
    path('users/', views.users_list, name='users'),
    path('users/new/', views.user_create, name='user_create'),
    path('users/<int:pk>/role/', views.change_user_role, name='change_user_role'),
```

- [ ] **Step 6: Create the template**

Create `services/web/templates/users/create.html`:
```html
{% extends "base.html" %}
{% block title %}NOWY USER — ADMIN{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">NOWY UŻYTKOWNIK</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error" style="margin-bottom:1rem;">
      {% for error in form.non_field_errors %}&gt; {{ error }}<br>{% endfor %}
    </div>
    {% endif %}
    {% for field in form %}
    <div class="field">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      {% if field.help_text %}<div style="color:#6a8a6a;font-size:0.75rem;">{{ field.help_text }}</div>{% endif %}
      {% if field.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ field.errors }}</div>{% endif %}
    </div>
    {% endfor %}
    <button type="submit" class="btn">[ UTWÓRZ ]</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/accounts/ -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add services/web/apps/accounts/forms.py services/web/apps/accounts/views.py services/web/apps/accounts/urls.py services/web/templates/users/create.html services/web/apps/accounts/tests/test_views.py
git commit -m "feat: admin-only in-app user creation form"
```

---

### Task 5: Wire organization + user-create into the User Management page

**Files:**
- Modify: `services/web/apps/accounts/views.py` (`users_list`)
- Modify: `services/web/templates/users/list.html`
- Modify: `services/web/apps/accounts/tests/test_views.py`

**Interfaces:**
- Consumes: `get_organization()` (Task 1), `organization:settings` URL (Task 2), `accounts:user_create` URL (Task 4).

- [ ] **Step 1: Write the failing test**

Add to `services/web/apps/accounts/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestUsersListShowsOrganization:
    def test_page_shows_organization_name_and_links(self, admin_client):
        from apps.organization.models import get_organization
        org = get_organization()
        org.name = 'Acme Corp'
        org.save()
        resp = admin_client.get('/accounts/users/')
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'Acme Corp' in content
        assert '/organization/' in content
        assert '/accounts/users/new/' in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/accounts/tests/test_views.py::TestUsersListShowsOrganization -v`
Expected: FAIL — `'Acme Corp' in content` is False (page doesn't render org name yet).

- [ ] **Step 3: Update the view**

In `services/web/apps/accounts/views.py`, add the import:
```python
from apps.organization.models import get_organization
```
(add this alongside the other `from apps...` imports near the top of the file, e.g. next to `from apps.api.models import ApiToken, MAX_TOKENS_PER_USER`)

Change `users_list` from:
```python
@require_role(ROLE_ADMIN)
def users_list(request):
    User = get_user_model()
    users = User.objects.all().order_by('username')
    return render(request, 'users/list.html', {'users': users, 'role_choices': ROLE_CHOICES})
```
to:
```python
@require_role(ROLE_ADMIN)
def users_list(request):
    User = get_user_model()
    users = User.objects.all().order_by('username')
    return render(request, 'users/list.html', {
        'users': users,
        'role_choices': ROLE_CHOICES,
        'organization': get_organization(),
    })
```
(Passing `organization` explicitly in this view's context, rather than relying solely on Task 3's context processor, keeps this test independent of context-processor wiring and matches how every other view in this codebase passes its own template data.)

- [ ] **Step 4: Update the template**

In `services/web/templates/users/list.html`, change:
```html
<div class="box">
  <span class="box-title">USER MANAGEMENT</span>
  <table>
```
to:
```html
<div class="box">
  <span class="box-title">{{ organization.name|upper }} — CZŁONKOWIE</span>
  <div class="toolbar" style="margin-bottom:1rem;">
    <a href="{% url 'organization:settings' %}" class="btn btn-small">[ EDYTUJ NAZWĘ ORGANIZACJI ]</a>
    <a href="{% url 'accounts:user_create' %}" class="btn">[ + DODAJ USERA ]</a>
  </div>
  <table>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/accounts/ apps/organization/ -v`
Expected: all PASS.

Run the full suite:
Run: `docker compose --project-name tmask-tt run --rm -v "$PWD/services/web:/app" web python -m pytest apps/ -q`
Expected: all PASS, count = previous total (309) + 3 (Task 1) + 5 (Task 2) + 2 (Task 3) + 5 (Task 4) + 1 (Task 5) = 325.

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/accounts/views.py services/web/templates/users/list.html services/web/apps/accounts/tests/test_views.py
git commit -m "feat: show organization name and add-user link on User Management page"
```

---

### Task 6: Production rebuild verification

**Files:** none modified — verification only.

- [ ] **Step 1: Full rebuild**

Run: `docker compose --project-name tmask-tt build web worker beat`
Expected: all three images build without error.

- [ ] **Step 2: Migrate on the built image**

Run: `docker compose --project-name tmask-tt run --rm web python manage.py migrate`
Expected: `organization.0001_initial` listed as applied, no errors.

- [ ] **Step 3: Full suite on the built image (no bind mount)**

Run: `docker compose --project-name tmask-tt run --rm web python -m pytest apps/ -q`
Expected: all PASS, 325 passed (per Task 5's count).

- [ ] **Step 4: Worker suite (sanity check — this plan never touches worker code)**

Run: `docker compose --project-name tmask-tt run --rm worker python -m pytest tests/ -q`
Expected: all PASS, 127 passed (unchanged from before this plan).
