# Email Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać konfigurowane per-użytkownik powiadomienia email (sukces/błąd transferu) jako osobny Celery task, z multipart emailem (plain text ASCII + HTML CRT) i stroną profilu.

**Architecture:** Dwa nowe pola BooleanField na modelu User (`notify_on_done`, `notify_on_failed`). Pomocnik `send_email_notification()` w `notifications.py` (czysty Python, bez Celery). Celery task `send_notification` w `tasks.py` — dispatchowany po `mark_done()` / `mark_failed()`. Strona `/accounts/profile/` z formularzem preferencji.

**Tech Stack:** Django 5.x, Celery 5.x, `django.core.mail.send_mail`, `django.template.loader.render_to_string`, `python-decouple`, pytest-django

---

## Mapa plików

| Plik | Akcja | Odpowiedzialność |
|------|-------|-----------------|
| `services/web/apps/accounts/models.py` | Modyfikuj | Dodaj `notify_on_done`, `notify_on_failed` |
| `services/web/apps/accounts/forms.py` | Modyfikuj | Dodaj `ProfileForm` |
| `services/web/apps/accounts/views.py` | Modyfikuj | Dodaj `profile_view` |
| `services/web/apps/accounts/urls.py` | Modyfikuj | Dodaj URL `profile/` |
| `services/web/apps/accounts/tests/test_models.py` | Modyfikuj | Testy nowych pól |
| `services/web/apps/accounts/tests/test_views.py` | Modyfikuj | Testy profile_view |
| `services/web/config/settings/base.py` | Modyfikuj | Dodaj EMAIL_* ustawienia |
| `.env.example` | Modyfikuj | Dodaj EMAIL_* zmienne |
| `services/web/templates/base.html` | Modyfikuj | Link PROFIL w nawigacji |
| `services/web/templates/accounts/profile.html` | Utwórz | Formularz preferencji |
| `services/web/templates/notifications/transfer_done.txt` | Utwórz | Plain text — sukces |
| `services/web/templates/notifications/transfer_failed.txt` | Utwórz | Plain text — błąd |
| `services/web/templates/notifications/transfer_done.html` | Utwórz | HTML — sukces |
| `services/web/templates/notifications/transfer_failed.html` | Utwórz | HTML — błąd |
| `services/worker/notifications.py` | Utwórz | `send_email_notification()` helper |
| `services/worker/tasks.py` | Modyfikuj | `send_notification` task + wywołania `.delay()` |
| `services/worker/tests/conftest.py` | Modyfikuj | Stub dla `notifications` |
| `services/worker/tests/test_notifications.py` | Utwórz | Testy helpera i tasku |
| `services/worker/tests/test_tasks.py` | Modyfikuj | Testy wywołań send_notification |
| `services/worker/Dockerfile` | Modyfikuj | `COPY services/web/templates ./templates` |

---

### Task 1: User model — pola notify + migracja

**Files:**
- Modify: `services/web/apps/accounts/models.py`
- Modify: `services/web/apps/accounts/tests/test_models.py`
- Create: migracja (auto-generowana)

- [ ] **Krok 1: Napisz testy**

Dodaj do `services/web/apps/accounts/tests/test_models.py`:

```python
def test_user_has_notify_on_done_default_false(self, django_user_model):
    user = django_user_model.objects.create_user(
        username='notif_test', password='pass'
    )
    assert user.notify_on_done is False

def test_user_has_notify_on_failed_default_true(self, django_user_model):
    user = django_user_model.objects.create_user(
        username='notif_test2', password='pass'
    )
    assert user.notify_on_failed is True
```

- [ ] **Krok 2: Uruchom testy — muszą być FAIL**

```bash
cd services/web && python -m pytest apps/accounts/tests/test_models.py -v -k "notify"
```

Oczekiwany wynik: `AttributeError: 'User' object has no attribute 'notify_on_done'`

- [ ] **Krok 3: Dodaj pola do modelu**

W `services/web/apps/accounts/models.py`, po polu `role`:

```python
notify_on_done   = models.BooleanField(default=False)
notify_on_failed = models.BooleanField(default=True)
```

- [ ] **Krok 4: Utwórz i zastosuj migrację**

```bash
cd services/web
python manage.py makemigrations accounts --name notify_fields
python manage.py migrate
```

Oczekiwany wynik: `Applying accounts.0002_notify_fields... OK`

- [ ] **Krok 5: Uruchom testy — muszą być PASS**

```bash
python -m pytest apps/accounts/tests/test_models.py -v -k "notify"
```

Oczekiwany wynik: `2 passed`

- [ ] **Krok 6: Commit**

```bash
git add services/web/apps/accounts/models.py services/web/apps/accounts/migrations/ services/web/apps/accounts/tests/test_models.py
git commit -m "feat: add notify_on_done and notify_on_failed fields to User model"
```

---

### Task 2: Konfiguracja SMTP w settings i .env.example

**Files:**
- Modify: `services/web/config/settings/base.py`
- Modify: `.env.example`

- [ ] **Krok 1: Dodaj ustawienia EMAIL do `services/web/config/settings/base.py`**

Dodaj po bloku `FIELD_ENCRYPTION_KEY`:

```python
# Email / powiadomienia
EMAIL_BACKEND       = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST          = config('EMAIL_HOST', default='')
EMAIL_PORT          = config('EMAIL_PORT', default=587, cast=int)
EMAIL_HOST_USER     = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS       = config('EMAIL_USE_TLS', default=True, cast=bool)
DEFAULT_FROM_EMAIL  = config('DEFAULT_FROM_EMAIL', default='noreply@localhost')
```

- [ ] **Krok 2: Dodaj zmienne do `.env.example`**

Dodaj na końcu pliku:

```
# Email / powiadomienia (opcjonalne — domyślnie logi do konsoli)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=noreply@example.com
EMAIL_HOST_PASSWORD=secret
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=TMask Transporter <noreply@example.com>
```

- [ ] **Krok 3: Commit**

```bash
git add services/web/config/settings/base.py .env.example
git commit -m "feat: add EMAIL_* settings for SMTP notifications"
```

---

### Task 3: ProfileForm

**Files:**
- Modify: `services/web/apps/accounts/forms.py`
- Modify: `services/web/apps/accounts/tests/test_models.py`

- [ ] **Krok 1: Napisz testy**

Dodaj do `services/web/apps/accounts/tests/test_models.py` (nowa klasa pod `TestUser`):

```python
@pytest.mark.django_db
class TestProfileForm:
    def test_form_has_required_fields(self):
        from apps.accounts.forms import ProfileForm
        form = ProfileForm()
        assert 'email' in form.fields
        assert 'notify_on_done' in form.fields
        assert 'notify_on_failed' in form.fields

    def test_form_saves_email_and_prefs(self, django_user_model):
        from apps.accounts.forms import ProfileForm
        user = django_user_model.objects.create_user(username='ptest', password='p')
        form = ProfileForm(
            data={'email': 'user@example.com', 'notify_on_done': True, 'notify_on_failed': False},
            instance=user,
        )
        assert form.is_valid(), form.errors
        saved = form.save()
        assert saved.email == 'user@example.com'
        assert saved.notify_on_done is True
        assert saved.notify_on_failed is False
```

- [ ] **Krok 2: Uruchom testy — muszą być FAIL**

```bash
cd services/web && python -m pytest apps/accounts/tests/test_models.py -v -k "ProfileForm"
```

Oczekiwany wynik: `ImportError: cannot import name 'ProfileForm'`

- [ ] **Krok 3: Dodaj ProfileForm do `services/web/apps/accounts/forms.py`**

```python
from django.contrib.auth import get_user_model


class ProfileForm(forms.ModelForm):
    class Meta:
        model  = get_user_model()
        fields = ['email', 'notify_on_done', 'notify_on_failed']
        labels = {
            'email':            'Adres email',
            'notify_on_done':   'Powiadamiaj o sukcesach transferu',
            'notify_on_failed': 'Powiadamiaj o błędach transferu',
        }
```

- [ ] **Krok 4: Uruchom testy — muszą być PASS**

```bash
python -m pytest apps/accounts/tests/test_models.py -v -k "ProfileForm"
```

Oczekiwany wynik: `2 passed`

- [ ] **Krok 5: Commit**

```bash
git add services/web/apps/accounts/forms.py services/web/apps/accounts/tests/test_models.py
git commit -m "feat: add ProfileForm for email and notification preferences"
```

---

### Task 4: profile_view + URL

**Files:**
- Modify: `services/web/apps/accounts/views.py`
- Modify: `services/web/apps/accounts/urls.py`
- Modify: `services/web/apps/accounts/tests/test_views.py`

- [ ] **Krok 1: Napisz testy**

Dodaj do `services/web/apps/accounts/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestProfileView:
    def test_unauthenticated_redirects_to_login(self, client):
        url = reverse('accounts:profile')
        response = client.get(url)
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_get_renders_form_with_current_values(self, auth_client, regular_user):
        regular_user.email = 'existing@example.com'
        regular_user.save()
        url = reverse('accounts:profile')
        response = auth_client.get(url)
        assert response.status_code == 200
        assert response.context['form'].initial.get('email') == 'existing@example.com' or \
               response.context['form'].instance.email == 'existing@example.com'

    def test_post_saves_prefs_and_redirects(self, auth_client, regular_user):
        url = reverse('accounts:profile')
        response = auth_client.post(url, {
            'email': 'updated@example.com',
            'notify_on_done': True,
            'notify_on_failed': False,
        })
        assert response.status_code == 302
        regular_user.refresh_from_db()
        assert regular_user.email == 'updated@example.com'
        assert regular_user.notify_on_done is True
        assert regular_user.notify_on_failed is False

    def test_post_with_invalid_email_shows_errors(self, auth_client):
        url = reverse('accounts:profile')
        response = auth_client.post(url, {
            'email': 'not-an-email',
            'notify_on_done': False,
            'notify_on_failed': True,
        })
        assert response.status_code == 200
        assert 'email' in response.context['form'].errors
```

- [ ] **Krok 2: Uruchom testy — muszą być FAIL**

```bash
cd services/web && python -m pytest apps/accounts/tests/test_views.py -v -k "Profile"
```

Oczekiwany wynik: `NoReverseMatch: Reverse for 'profile' not found`

- [ ] **Krok 3: Dodaj widok do `services/web/apps/accounts/views.py`**

Dodaj import na górze:

```python
from django.contrib import messages
from .forms import LoginForm, ProfileForm
```

Dodaj widok na końcu pliku:

```python
@login_required
def profile_view(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Ustawienia zapisane.')
            return redirect('accounts:profile')
    else:
        form = ProfileForm(instance=request.user)
    return render(request, 'accounts/profile.html', {'form': form})
```

- [ ] **Krok 4: Dodaj URL do `services/web/apps/accounts/urls.py`**

```python
path('profile/', views.profile_view, name='profile'),
```

- [ ] **Krok 5: Uruchom testy — muszą być PASS**

```bash
python -m pytest apps/accounts/tests/test_views.py -v -k "Profile"
```

Oczekiwany wynik: `4 passed` (szablon jeszcze nie istnieje — testy mogą fail na rendering; jeśli tak — utwórz minimalny szablon `templates/accounts/profile.html` z `{% extends "base.html" %}{% block content %}{% endblock %}` i wróć)

- [ ] **Krok 6: Commit**

```bash
git add services/web/apps/accounts/views.py services/web/apps/accounts/urls.py services/web/apps/accounts/tests/test_views.py
git commit -m "feat: add profile_view with notification preferences"
```

---

### Task 5: Szablon profilu + link w nawigacji

**Files:**
- Create: `services/web/templates/accounts/profile.html`
- Modify: `services/web/templates/base.html`

- [ ] **Krok 1: Utwórz `services/web/templates/accounts/profile.html`**

```html
{% extends "base.html" %}
{% block title %}PROFIL — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel">
  <div class="panel-header">[ PROFIL UŻYTKOWNIKA ]</div>

  <div class="panel-section">
    <div class="field-row">
      <span class="label">UŻYTKOWNIK:</span>
      <span class="value">{{ user.username|upper }}</span>
    </div>
    <div class="field-row">
      <span class="label">ROLA:</span>
      <span class="value">{{ user.role|upper }}</span>
    </div>
  </div>

  <div class="panel-section">
    <div class="panel-subheader">[ POWIADOMIENIA EMAIL ]</div>
    <form method="post">
      {% csrf_token %}
      <div class="field-row">
        <label class="label" for="{{ form.email.id_for_label }}">ADRES EMAIL:</label>
        {{ form.email }}
        {% if form.email.errors %}
          <span class="error">{{ form.email.errors|join:", " }}</span>
        {% endif %}
      </div>
      <div class="field-row checkbox-row">
        {{ form.notify_on_failed }}
        <label for="{{ form.notify_on_failed.id_for_label }}">
          {{ form.notify_on_failed.label|upper }}
        </label>
      </div>
      <div class="field-row checkbox-row">
        {{ form.notify_on_done }}
        <label for="{{ form.notify_on_done.id_for_label }}">
          {{ form.notify_on_done.label|upper }}
        </label>
      </div>
      {% if not user.email %}
      <div class="warn">
        &gt; BRAK ADRESU EMAIL — POWIADOMIENIA NIEAKTYWNE
      </div>
      {% endif %}
      {% if messages %}
        {% for message in messages %}
        <div class="msg-success">&gt; {{ message }}</div>
        {% endfor %}
      {% endif %}
      <div class="form-actions">
        <button type="submit" class="btn">[ ZAPISZ USTAWIENIA ]</button>
      </div>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Krok 2: Dodaj link PROFIL do nawigacji w `services/web/templates/base.html`**

Znajdź linię z `LOGOUT` w bloku `nav-right` i dodaj link PROFIL przed nią:

```html
<span class="nav-right">
  USER: {{ user.username|upper }} [{{ user.role|upper }}]
  &nbsp;|&nbsp;
  <a href="{% url 'accounts:profile' %}">PROFIL</a>
  &nbsp;|&nbsp;
  <form method="post" action="{% url 'accounts:logout' %}" style="display:inline">
    {% csrf_token %}
    <button type="submit" class="btn" style="border:none;padding:0;">LOGOUT</button>
  </form>
</span>
```

- [ ] **Krok 3: Uruchom testy widoku profilu**

```bash
cd services/web && python -m pytest apps/accounts/tests/test_views.py -v -k "Profile"
```

Oczekiwany wynik: `4 passed`

- [ ] **Krok 4: Commit**

```bash
git add services/web/templates/accounts/profile.html services/web/templates/base.html
git commit -m "feat: add profile template with notification settings and nav link"
```

---

### Task 6: Szablony email (plain text + HTML)

**Files:**
- Create: `services/web/templates/notifications/transfer_done.txt`
- Create: `services/web/templates/notifications/transfer_failed.txt`
- Create: `services/web/templates/notifications/transfer_done.html`
- Create: `services/web/templates/notifications/transfer_failed.html`
- Modify: `services/web/apps/accounts/tests/test_views.py`

- [ ] **Krok 1: Napisz testy renderowania szablonów**

Dodaj do `services/web/apps/accounts/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestNotificationTemplates:
    def _make_job(self, django_user_model, status, error_message=None):
        from apps.transfers.models import TransferJob
        from apps.connections.models import Connection
        user = django_user_model.objects.create_user(username='tpl_user', password='p')
        conn = Connection.objects.create(
            owner=user, name='TestSrv', host='10.0.0.1', port=22,
            username='u', password='p', protocol='sftp',
        )
        job = TransferJob.objects.create(
            owner=user, connection=conn,
            source_path='/data/file.tar',
            destination_path='/backup/file.tar',
            status=status,
        )
        if error_message:
            job.error_message = error_message
            job.save()
        return job

    def test_done_plain_text_contains_key_data(self, django_user_model):
        from django.template.loader import render_to_string
        job = self._make_job(django_user_model, 'done')
        result = render_to_string('notifications/transfer_done.txt', {'job': job})
        assert 'DONE' in result
        assert str(job.pk) in result
        assert '/data/file.tar' in result
        assert '/backup/file.tar' in result

    def test_failed_plain_text_contains_error(self, django_user_model):
        from django.template.loader import render_to_string
        job = self._make_job(django_user_model, 'failed', error_message='AUTH FAILED')
        result = render_to_string('notifications/transfer_failed.txt', {'job': job})
        assert 'FAILED' in result
        assert 'AUTH FAILED' in result
        assert str(job.pk) in result

    def test_done_html_contains_job_data(self, django_user_model):
        from django.template.loader import render_to_string
        job = self._make_job(django_user_model, 'done')
        result = render_to_string('notifications/transfer_done.html', {'job': job})
        assert str(job.pk) in result
        assert '/data/file.tar' in result
        assert '33ff33' in result  # CRT zielony kolor

    def test_failed_html_contains_error_color(self, django_user_model):
        from django.template.loader import render_to_string
        job = self._make_job(django_user_model, 'failed', error_message='TIMEOUT')
        result = render_to_string('notifications/transfer_failed.html', {'job': job})
        assert 'TIMEOUT' in result
        assert 'ff3333' in result  # CRT czerwony kolor
```

- [ ] **Krok 2: Uruchom testy — muszą być FAIL**

```bash
cd services/web && python -m pytest apps/accounts/tests/test_views.py -v -k "NotificationTemplates"
```

Oczekiwany wynik: `TemplateDoesNotExist: notifications/transfer_done.txt`

- [ ] **Krok 3: Utwórz `services/web/templates/notifications/transfer_done.txt`**

```
╔══════════════════════════════════════════════════╗
║  TMASK TRANSPORTER — TRANSFER DONE               ║
╚══════════════════════════════════════════════════╝

Job #{{ job.pk }} zakończony sukcesem.

  FROM : {{ job.source_path }}
  TO   : {{ job.destination_path }}
  START: {% if job.started_at %}{{ job.started_at|date:"Y-m-d H:i" }}{% else %}—{% endif %}
  END  : {% if job.finished_at %}{{ job.finished_at|date:"Y-m-d H:i" }}{% else %}—{% endif %}
  HOST : {% if job.connection %}{{ job.connection.name }} ({{ job.connection.protocol|upper }}){% elif job.flow %}RELAY: {{ job.flow.name }}{% else %}—{% endif %}

--
TMask Transporter | ustawienia powiadomień: /accounts/profile/
```

- [ ] **Krok 4: Utwórz `services/web/templates/notifications/transfer_failed.txt`**

```
╔══════════════════════════════════════════════════╗
║  TMASK TRANSPORTER — TRANSFER FAILED             ║
╚══════════════════════════════════════════════════╝

Job #{{ job.pk }} zakończony błędem.

  FROM  : {{ job.source_path }}
  TO    : {{ job.destination_path }}
  START : {% if job.started_at %}{{ job.started_at|date:"Y-m-d H:i" }}{% else %}—{% endif %}
  ERROR : {{ job.error_message|default:"UNKNOWN ERROR" }}
  HOST  : {% if job.connection %}{{ job.connection.name }} ({{ job.connection.protocol|upper }}){% elif job.flow %}RELAY: {{ job.flow.name }}{% else %}—{% endif %}

--
TMask Transporter | ustawienia powiadomień: /accounts/profile/
```

- [ ] **Krok 5: Utwórz `services/web/templates/notifications/transfer_done.html`**

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { background:#0a0a0a; color:#33ff33; font-family:monospace; padding:20px; }
  .header { border:1px solid #33ff33; padding:10px 20px; margin-bottom:20px; }
  .header h1 { color:#00ff41; font-size:16px; margin:0; letter-spacing:2px; }
  table { border-collapse:collapse; width:100%; }
  td { padding:4px 12px; color:#33ff33; }
  td:first-child { color:#aaffaa; width:80px; }
  .footer { margin-top:20px; border-top:1px solid #33ff33; padding-top:10px; font-size:11px; color:#557755; }
</style>
</head>
<body>
  <div class="header">
    <h1>[ TMASK TRANSPORTER — TRANSFER DONE ]</h1>
  </div>
  <p>Job #{{ job.pk }} zakończony sukcesem.</p>
  <table>
    <tr><td>FROM</td><td>{{ job.source_path }}</td></tr>
    <tr><td>TO</td><td>{{ job.destination_path }}</td></tr>
    <tr><td>START</td><td>{% if job.started_at %}{{ job.started_at|date:"Y-m-d H:i" }}{% else %}—{% endif %}</td></tr>
    <tr><td>END</td><td>{% if job.finished_at %}{{ job.finished_at|date:"Y-m-d H:i" }}{% else %}—{% endif %}</td></tr>
    <tr><td>HOST</td><td>{% if job.connection %}{{ job.connection.name }} ({{ job.connection.protocol|upper }}){% elif job.flow %}RELAY: {{ job.flow.name }}{% else %}—{% endif %}</td></tr>
  </table>
  <div class="footer">TMask Transporter &mdash; ustawienia powiadomień: /accounts/profile/</div>
</body>
</html>
```

- [ ] **Krok 6: Utwórz `services/web/templates/notifications/transfer_failed.html`**

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { background:#0a0a0a; color:#33ff33; font-family:monospace; padding:20px; }
  .header { border:1px solid #ff3333; padding:10px 20px; margin-bottom:20px; }
  .header h1 { color:#ff3333; font-size:16px; margin:0; letter-spacing:2px; }
  table { border-collapse:collapse; width:100%; }
  td { padding:4px 12px; color:#33ff33; }
  td:first-child { color:#aaffaa; width:80px; }
  .error-row td { color:#ff3333; }
  .footer { margin-top:20px; border-top:1px solid #33ff33; padding-top:10px; font-size:11px; color:#557755; }
</style>
</head>
<body>
  <div class="header">
    <h1>[ TMASK TRANSPORTER — TRANSFER FAILED ]</h1>
  </div>
  <p>Job #{{ job.pk }} zakończony błędem.</p>
  <table>
    <tr><td>FROM</td><td>{{ job.source_path }}</td></tr>
    <tr><td>TO</td><td>{{ job.destination_path }}</td></tr>
    <tr><td>START</td><td>{% if job.started_at %}{{ job.started_at|date:"Y-m-d H:i" }}{% else %}—{% endif %}</td></tr>
    <tr class="error-row"><td>ERROR</td><td>{{ job.error_message|default:"UNKNOWN ERROR" }}</td></tr>
    <tr><td>HOST</td><td>{% if job.connection %}{{ job.connection.name }} ({{ job.connection.protocol|upper }}){% elif job.flow %}RELAY: {{ job.flow.name }}{% else %}—{% endif %}</td></tr>
  </table>
  <div class="footer">TMask Transporter &mdash; ustawienia powiadomień: /accounts/profile/</div>
</body>
</html>
```

- [ ] **Krok 7: Uruchom testy — muszą być PASS**

```bash
cd services/web && python -m pytest apps/accounts/tests/test_views.py -v -k "NotificationTemplates"
```

Oczekiwany wynik: `4 passed`

- [ ] **Krok 8: Commit**

```bash
git add services/web/templates/notifications/
git commit -m "feat: add email notification templates (plain text + HTML CRT style)"
```

---

### Task 7: notifications.py helper + Dockerfile

**Files:**
- Create: `services/worker/notifications.py`
- Modify: `services/worker/Dockerfile`
- Modify: `services/worker/tests/conftest.py`
- Create: `services/worker/tests/test_notifications.py`

- [ ] **Krok 1: Napisz testy dla send_email_notification**

Utwórz `services/worker/tests/test_notifications.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


class TestSendEmailNotification:
    def _make_job(self, status, email='', notify_on_done=False, notify_on_failed=True, error_message=None):
        job = MagicMock()
        job.pk = 42
        job.status = status
        job.source_path = '/data/file.tar'
        job.destination_path = '/backup/file.tar'
        job.error_message = error_message or ''
        job.started_at = None
        job.finished_at = None
        job.connection = MagicMock()
        job.connection.name = 'TestSrv'
        job.connection.protocol = 'sftp'
        job.flow = None
        job.owner = MagicMock()
        job.owner.email = email
        job.owner.notify_on_done = notify_on_done
        job.owner.notify_on_failed = notify_on_failed
        return job

    def test_skips_if_no_email(self):
        from notifications import send_email_notification
        job = self._make_job('failed', email='')
        with patch('notifications.send_mail') as mock_mail:
            result = send_email_notification(job)
        assert result is False
        mock_mail.assert_not_called()

    def test_skips_done_if_notify_on_done_false(self):
        from notifications import send_email_notification
        job = self._make_job('done', email='u@example.com', notify_on_done=False)
        with patch('notifications.send_mail') as mock_mail:
            result = send_email_notification(job)
        assert result is False
        mock_mail.assert_not_called()

    def test_skips_failed_if_notify_on_failed_false(self):
        from notifications import send_email_notification
        job = self._make_job('failed', email='u@example.com', notify_on_failed=False)
        with patch('notifications.send_mail') as mock_mail:
            result = send_email_notification(job)
        assert result is False
        mock_mail.assert_not_called()

    def test_sends_email_on_done_when_enabled(self):
        from notifications import send_email_notification
        job = self._make_job('done', email='u@example.com', notify_on_done=True)
        with patch('notifications.send_mail') as mock_mail, \
             patch('notifications._render_notification', return_value=('subj', 'plain', '<html>')):
            result = send_email_notification(job)
        assert result is True
        mock_mail.assert_called_once()
        call_kwargs = mock_mail.call_args
        assert 'u@example.com' in call_kwargs[0][3]

    def test_sends_email_on_failed_when_enabled(self):
        from notifications import send_email_notification
        job = self._make_job('failed', email='u@example.com', notify_on_failed=True)
        with patch('notifications.send_mail') as mock_mail, \
             patch('notifications._render_notification', return_value=('subj', 'plain', '<html>')):
            result = send_email_notification(job)
        assert result is True
        mock_mail.assert_called_once()

    def test_render_notification_done_subject(self):
        from notifications import _render_notification
        job = self._make_job('done', email='u@example.com')
        with patch('notifications.render_to_string', return_value='rendered'):
            subject, plain, html = _render_notification(job)
        assert 'DONE' in subject
        assert '42' in subject

    def test_render_notification_failed_subject(self):
        from notifications import _render_notification
        job = self._make_job('failed', email='u@example.com')
        with patch('notifications.render_to_string', return_value='rendered'):
            subject, plain, html = _render_notification(job)
        assert 'FAILED' in subject
        assert '42' in subject
```

- [ ] **Krok 2: Uruchom testy — muszą być FAIL**

```bash
cd services/worker && python -m pytest tests/test_notifications.py -v
```

Oczekiwany wynik: `ModuleNotFoundError: No module named 'notifications'`

- [ ] **Krok 3: Utwórz `services/worker/notifications.py`**

```python
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings


def _render_notification(job):
    status = job.status
    context = {'job': job}
    subject = f'[TMask] Transfer #{job.pk} — {"DONE" if status == "done" else "FAILED"}'
    plain = render_to_string(f'notifications/transfer_{status}.txt', context)
    html  = render_to_string(f'notifications/transfer_{status}.html', context)
    return subject, plain, html


def send_email_notification(job) -> bool:
    user = job.owner
    if not user.email:
        return False
    if job.status == 'done' and not user.notify_on_done:
        return False
    if job.status == 'failed' and not user.notify_on_failed:
        return False
    subject, plain, html = _render_notification(job)
    send_mail(
        subject,
        plain,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html,
        fail_silently=False,
    )
    return True
```

- [ ] **Krok 4: Uruchom testy — muszą być PASS**

```bash
cd services/worker && python -m pytest tests/test_notifications.py -v
```

Oczekiwany wynik: `7 passed`

- [ ] **Krok 5: Dodaj COPY templates do `services/worker/Dockerfile`**

Po linii `COPY services/web/apps ./apps` dodaj:

```dockerfile
COPY services/web/templates ./templates
```

- [ ] **Krok 6: Commit**

```bash
git add services/worker/notifications.py services/worker/tests/test_notifications.py services/worker/Dockerfile
git commit -m "feat: add send_email_notification helper and email templates to worker"
```

---

### Task 8: Celery task send_notification + integracja w tasks.py

**Files:**
- Modify: `services/worker/tasks.py`
- Modify: `services/worker/tests/conftest.py`
- Modify: `services/worker/tests/test_tasks.py`

- [ ] **Krok 1: Dodaj stub notifications do conftest**

W `services/worker/tests/conftest.py`, dodaj na końcu bloku `sys.modules.setdefault`:

```python
sys.modules.setdefault('notifications', MagicMock())
```

- [ ] **Krok 2: Napisz testy**

Dodaj do `services/worker/tests/test_tasks.py`:

```python
class TestSendNotificationTask:
    def test_calls_send_email_notification(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.send_email_notification') as mock_notif:
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            from tasks import send_notification
            send_notification(job_id=42)
            mock_notif.assert_called_once_with(mock_job)

    def test_logs_and_skips_when_job_not_found(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.logger') as mock_logger:
            # Symuluj brak joba przez ogólny wyjątek (DoesNotExist jest MagicMockiem)
            MockJob.objects.select_related.return_value.get.side_effect = Exception('not found')
            from tasks import send_notification
            # Nie powinien rzucić — task łapie i loguje
            send_notification(job_id=999)
            mock_logger.error.assert_called()


class TestExecuteTransferDispatchesNotification:
    def test_dispatches_notification_on_done(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'), \
             patch('tasks.send_notification') as mock_notif:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 99
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=99)
            mock_notif.delay.assert_called_once_with(99)

    def test_dispatches_notification_on_failed(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'), \
             patch('tasks.send_notification') as mock_notif:
            from modules.sftp.handler import SFTPTransferError
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 99
            MockSFTP.return_value.execute.side_effect = SFTPTransferError('TIMEOUT')
            from tasks import execute_transfer
            execute_transfer(job_id=99)
            mock_notif.delay.assert_called_once_with(99)
```

- [ ] **Krok 3: Uruchom testy — muszą być FAIL**

```bash
cd services/worker && python -m pytest tests/test_tasks.py -v -k "Notification"
```

Oczekiwany wynik: `ImportError` lub `AssertionError — mock_notif.delay not called`

- [ ] **Krok 4: Dodaj task i wywołania do `services/worker/tasks.py`**

Po istniejących importach dodaj:

```python
from notifications import send_email_notification
```

Dodaj task `send_notification` przed `execute_transfer`:

```python
@app.task(bind=True, name='transfers.send_notification', max_retries=3, default_retry_delay=60)
def send_notification(self, job_id: int):
    try:
        job = TransferJob.objects.select_related('owner', 'connection', 'flow').get(pk=job_id)
    except Exception:
        logger.error(f'TransferJob {job_id} not found — notification skipped')
        return
    try:
        send_email_notification(job)
    except Exception as exc:
        raise self.retry(exc=exc)
```

W `execute_transfer`, po `job.mark_done()` dodaj:

```python
job.mark_done()
send_notification.delay(job.pk)
```

W obu blokach `except` po `job.mark_failed(...)` dodaj:

```python
job.mark_failed(str(e))
send_notification.delay(job.pk)
log_callback('error', str(e))
```

(Uwaga: oba bloki — `SFTPTransferError/RsyncTransferError/RelayTransferError` i `Exception` — muszą mieć wywołanie `send_notification.delay`.)

- [ ] **Krok 5: Uruchom wszystkie testy workera**

```bash
cd services/worker && python -m pytest tests/ -v
```

Oczekiwany wynik: wszystkie testy PASS (w tym nowe i istniejące)

- [ ] **Krok 6: Commit**

```bash
git add services/worker/tasks.py services/worker/tests/conftest.py services/worker/tests/test_tasks.py
git commit -m "feat: add send_notification Celery task, dispatch after transfer done/failed"
```

---

## Weryfikacja końcowa

Po wszystkich taskach:

- [ ] **Uruchom wszystkie testy web**

```bash
cd services/web && python -m pytest apps/ -v
```

Oczekiwany wynik: wszystkie testy PASS (minimum: poprzednie 38 + nowe ~10)

- [ ] **Uruchom wszystkie testy worker**

```bash
cd services/worker && python -m pytest tests/ -v
```

Oczekiwany wynik: wszystkie testy PASS (minimum: poprzednie 21 + nowe ~10)

- [ ] **Rebuild i smoke test Docker**

```bash
docker compose build web worker
docker compose up -d
docker compose ps
# Wszystkie serwisy: healthy
curl -s -o /dev/null -w "%{http_code}" http://localhost/accounts/profile/
# Oczekiwane: 302 (redirect do login — URL działa)
```

- [ ] **Test powiadomień (console backend)**

W `.env` upewnij się że `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`.

Uruchom transfer, po jego zakończeniu sprawdź logi kontenera worker:

```bash
docker compose logs worker --tail=30
```

Oczekiwany wynik: mail w formacie ASCII w logach workera (console backend drukuje do stdout).

- [ ] **Commit końcowy jeśli potrzeba**

```bash
git add -A && git commit -m "feat: complete email notifications implementation"
```
