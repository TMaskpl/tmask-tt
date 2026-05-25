# Webhook Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodaj generyczny webhook per-user — po transferze worker wysyła `POST JSON` na skonfigurowany URL (Slack, Telegram, n8n, Discord itp.).

**Architecture:** Trzy nowe pola na `User` (migracja). Funkcja `send_webhook_notification()` w `notifications.py` (obok istniejącej `send_email_notification`). Nowy Celery task `send_webhook` wywołuje ją asynchronicznie z retry. Endpoint `test_webhook` w web service pozwala zweryfikować URL przez HTMX przed zapisem.

**Tech Stack:** Django 5.x, Celery 5.x, `requests`, pytest, HTMX

---

## Struktura plików

| Akcja | Ścieżka |
|-------|---------|
| Modify | `services/web/apps/accounts/models.py` |
| Create | `services/web/apps/accounts/migrations/0003_webhook_fields.py` |
| Modify | `services/worker/notifications.py` |
| Modify | `services/worker/tests/test_notifications.py` |
| Modify | `services/worker/tasks.py` |
| Modify | `services/worker/tests/test_tasks.py` |
| Modify | `services/web/requirements.txt` |
| Modify | `services/web/apps/accounts/views.py` |
| Modify | `services/web/apps/accounts/urls.py` |
| Modify | `services/web/apps/accounts/tests/test_views.py` |
| Modify | `services/web/apps/accounts/forms.py` |
| Modify | `services/web/templates/accounts/profile.html` |

---

## Task 1: Migracja — pola webhook na User

**Files:**
- Modify: `services/web/apps/accounts/models.py`
- Create: `services/web/apps/accounts/migrations/0003_webhook_fields.py`

- [ ] **Krok 1: Dodaj pola do modelu**

W `services/web/apps/accounts/models.py` dodaj 3 pola po `notify_on_failed`:

```python
class User(AbstractUser):
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_USER)
    notify_on_done   = models.BooleanField(default=False)
    notify_on_failed = models.BooleanField(default=True)
    webhook_url      = models.URLField(blank=True, default='')
    webhook_on_done  = models.BooleanField(default=False)
    webhook_on_failed = models.BooleanField(default=True)

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    class Meta:
        verbose_name = 'Użytkownik'
        verbose_name_plural = 'Użytkownicy'
```

- [ ] **Krok 2: Utwórz migrację ręcznie**

Utwórz `services/web/apps/accounts/migrations/0003_webhook_fields.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_notify_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="webhook_url",
            field=models.URLField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name="user",
            name="webhook_on_done",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="user",
            name="webhook_on_failed",
            field=models.BooleanField(default=True),
        ),
    ]
```

- [ ] **Krok 3: Zastosuj migrację**

```bash
docker compose run --rm web python manage.py migrate
```

Oczekiwany output: `Applying accounts.0003_webhook_fields... OK`

- [ ] **Krok 4: Zweryfikuj że testy web nadal przechodzą**

```bash
docker compose run --rm web pytest apps/accounts/tests/ -v
```

Oczekiwany output: wszystkie testy PASS (bez nowych).

- [ ] **Krok 5: Commit**

```bash
git add services/web/apps/accounts/models.py \
        services/web/apps/accounts/migrations/0003_webhook_fields.py
git commit -m "feat: add webhook_url, webhook_on_done, webhook_on_failed fields to User"
```

---

## Task 2: `send_webhook_notification` w workerze (TDD)

**Files:**
- Modify: `services/worker/requirements.txt`
- Modify: `services/worker/tests/test_notifications.py`
- Modify: `services/worker/notifications.py`

- [ ] **Krok 1: Dodaj `requests` do wymagań workera**

W `services/worker/requirements.txt` dopisz po `bcrypt==4.*`:

```
requests==2.*
```

- [ ] **Krok 2: Napisz testy — nowa klasa `TestSendWebhookNotification`**

Dopisz na końcu `services/worker/tests/test_notifications.py`:

```python
class TestSendWebhookNotification:
    def _make_job(self, status, webhook_url='', webhook_on_done=False,
                  webhook_on_failed=True, error_message=None, use_flow=False):
        job = MagicMock()
        job.pk = 42
        job.status = status
        job.source_path = '/data/file.tar'
        job.destination_path = '/backup/file.tar'
        job.error_message = error_message or ''
        job.started_at = None
        job.finished_at = None
        if use_flow:
            job.connection = None
            job.flow = MagicMock()
            job.flow.name = 'MyFlow'
        else:
            job.connection = MagicMock()
            job.connection.name = 'TestSrv'
            job.connection.protocol = 'sftp'
            job.flow = None
        job.owner = MagicMock()
        job.owner.webhook_url = webhook_url
        job.owner.webhook_on_done = webhook_on_done
        job.owner.webhook_on_failed = webhook_on_failed
        return job

    def test_skips_if_no_url(self):
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='')
        with patch('notifications.requests.post') as mock_post:
            result = send_webhook_notification(job)
        assert result is False
        mock_post.assert_not_called()

    def test_skips_done_if_webhook_on_done_false(self):
        from notifications import send_webhook_notification
        job = self._make_job('done', webhook_url='http://hooks.example.com/',
                             webhook_on_done=False)
        with patch('notifications.requests.post') as mock_post:
            result = send_webhook_notification(job)
        assert result is False
        mock_post.assert_not_called()

    def test_skips_failed_if_webhook_on_failed_false(self):
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://hooks.example.com/',
                             webhook_on_failed=False)
        with patch('notifications.requests.post') as mock_post:
            result = send_webhook_notification(job)
        assert result is False
        mock_post.assert_not_called()

    def test_sends_on_done_when_enabled(self):
        from notifications import send_webhook_notification
        job = self._make_job('done', webhook_url='http://hooks.example.com/',
                             webhook_on_done=True)
        mock_resp = MagicMock()
        with patch('notifications.requests.post', return_value=mock_resp) as mock_post:
            result = send_webhook_notification(job)
        assert result is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == 'http://hooks.example.com/'
        assert kwargs['timeout'] == 10
        mock_resp.raise_for_status.assert_called_once()

    def test_sends_on_failed_when_enabled(self):
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://hooks.example.com/',
                             webhook_on_failed=True)
        mock_resp = MagicMock()
        with patch('notifications.requests.post', return_value=mock_resp) as mock_post:
            result = send_webhook_notification(job)
        assert result is True
        mock_post.assert_called_once()
        mock_resp.raise_for_status.assert_called_once()

    def test_raises_on_non_2xx(self):
        import requests as req
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://hooks.example.com/',
                             webhook_on_failed=True)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = req.HTTPError('403')
        with patch('notifications.requests.post', return_value=mock_resp):
            with pytest.raises(req.HTTPError):
                send_webhook_notification(job)

    def test_raises_on_timeout(self):
        import requests as req
        from notifications import send_webhook_notification
        job = self._make_job('failed', webhook_url='http://hooks.example.com/',
                             webhook_on_failed=True)
        with patch('notifications.requests.post', side_effect=req.Timeout('timeout')):
            with pytest.raises(req.Timeout):
                send_webhook_notification(job)

    def test_payload_contains_expected_fields(self):
        from notifications import send_webhook_notification
        job = self._make_job('done', webhook_url='http://hooks.example.com/',
                             webhook_on_done=True)
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured['payload'] = json
            return MagicMock()

        with patch('notifications.requests.post', side_effect=capture_post):
            send_webhook_notification(job)

        p = captured['payload']
        assert p['job_id'] == 42
        assert p['status'] == 'done'
        assert p['source_path'] == '/data/file.tar'
        assert p['destination_path'] == '/backup/file.tar'
        assert 'TestSrv' in p['connection']
        assert 'SFTP' in p['connection']
        assert p['error'] is None

    def test_payload_connection_label_for_relay_flow(self):
        from notifications import send_webhook_notification
        job = self._make_job('done', webhook_url='http://hooks.example.com/',
                             webhook_on_done=True, use_flow=True)
        captured = {}

        def capture_post(url, json=None, timeout=None):
            captured['payload'] = json
            return MagicMock()

        with patch('notifications.requests.post', side_effect=capture_post):
            send_webhook_notification(job)

        assert captured['payload']['connection'] == 'RELAY: MyFlow'
```

- [ ] **Krok 3: Uruchom testy — powinny FAIL**

```bash
cd services/worker && pytest tests/test_notifications.py::TestSendWebhookNotification -v
```

Oczekiwany output: `ImportError` lub `AttributeError` — `send_webhook_notification` nie istnieje.

- [ ] **Krok 4: Zaimplementuj funkcje w `notifications.py`**

Zastąp całą zawartość `services/worker/notifications.py`:

```python
import requests
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


def _build_webhook_payload(job) -> dict:
    if job.connection:
        connection_label = f'{job.connection.name} ({job.connection.protocol.upper()})'
    elif job.flow:
        connection_label = f'RELAY: {job.flow.name}'
    else:
        connection_label = '—'

    def fmt_dt(dt):
        return dt.strftime('%Y-%m-%d %H:%M') if dt else None

    return {
        'job_id': job.pk,
        'status': job.status,
        'source_path': job.source_path,
        'destination_path': job.destination_path,
        'connection': connection_label,
        'started_at': fmt_dt(job.started_at),
        'finished_at': fmt_dt(job.finished_at),
        'error': job.error_message or None,
    }


def send_webhook_notification(job) -> bool:
    user = job.owner
    if not user.webhook_url:
        return False
    if job.status == 'done' and not user.webhook_on_done:
        return False
    if job.status == 'failed' and not user.webhook_on_failed:
        return False
    payload = _build_webhook_payload(job)
    resp = requests.post(user.webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    return True
```

- [ ] **Krok 5: Uruchom testy — powinny PASS**

```bash
cd services/worker && pytest tests/test_notifications.py -v
```

Oczekiwany output: wszystkie testy PASS (poprzednie 7 + nowe 8 = 15 łącznie).

- [ ] **Krok 6: Commit**

```bash
git add services/worker/requirements.txt \
        services/worker/notifications.py \
        services/worker/tests/test_notifications.py
git commit -m "feat: add send_webhook_notification with payload builder and tests"
```

---

## Task 3: Celery task `send_webhook` (TDD)

**Files:**
- Modify: `services/worker/tests/test_tasks.py`
- Modify: `services/worker/tasks.py`

- [ ] **Krok 1: Napisz testy — nowe klasy w `test_tasks.py`**

Dopisz na końcu `services/worker/tests/test_tasks.py`:

```python
class TestSendWebhookTask:
    def test_calls_send_webhook_notification(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.send_webhook_notification') as mock_notif:
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            from tasks import send_webhook
            send_webhook(job_id=42)
            mock_notif.assert_called_once_with(mock_job)

    def test_logs_and_skips_when_job_not_found(self):
        with patch('tasks.TransferJob') as MockJob, \
             patch('tasks.logger') as mock_logger:
            MockJob.objects.select_related.return_value.get.side_effect = Exception('not found')
            from tasks import send_webhook
            send_webhook(job_id=999)
            mock_logger.error.assert_called()


class TestExecuteTransferDispatchesWebhook:
    def test_dispatches_webhook_on_done(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'), \
             patch('tasks.send_notification'), \
             patch('tasks.send_webhook') as mock_webhook:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 99
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=99)
            mock_webhook.delay.assert_called_once_with(99)

    def test_dispatches_webhook_on_failed(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'), \
             patch('tasks.send_notification'), \
             patch('tasks.send_webhook') as mock_webhook:
            from modules.sftp.handler import SFTPTransferError
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.pk = 99
            MockSFTP.return_value.execute.side_effect = SFTPTransferError('TIMEOUT')
            from tasks import execute_transfer
            execute_transfer(job_id=99)
            mock_webhook.delay.assert_called_once_with(99)
```

- [ ] **Krok 2: Uruchom testy — powinny FAIL**

```bash
cd services/worker && pytest tests/test_tasks.py::TestSendWebhookTask tests/test_tasks.py::TestExecuteTransferDispatchesWebhook -v
```

Oczekiwany output: `ImportError` — `send_webhook` nie istnieje w `tasks`.

- [ ] **Krok 3: Dodaj task `send_webhook` do `tasks.py` i zaktualizuj import**

W `services/worker/tasks.py` zmień import `notifications`:

```python
from notifications import send_email_notification, send_webhook_notification
```

Dodaj nowy task po `send_notification` (przed `execute_transfer`):

```python
@app.task(bind=True, name='transfers.send_webhook', max_retries=3, default_retry_delay=60)
def send_webhook(self, job_id: int):
    try:
        job = TransferJob.objects.select_related('owner', 'connection', 'flow').get(pk=job_id)
    except Exception:
        logger.error(f'TransferJob {job_id} not found — webhook skipped')
        return
    try:
        send_webhook_notification(job)
    except Exception as exc:
        raise self.retry(exc=exc)
```

- [ ] **Krok 4: Zaktualizuj `execute_transfer` — wywołaj oba taski**

W `execute_transfer` w bloku `try` po `job.mark_done()`:

```python
        job.mark_done()
        send_notification.delay(job.pk)
        send_webhook.delay(job.pk)
```

W bloku `except (SFTPTransferError, RsyncTransferError, RelayTransferError)`:

```python
        job.mark_failed(str(e))
        send_notification.delay(job.pk)
        send_webhook.delay(job.pk)
        log_callback('error', str(e))
        logger.error(f'Transfer job {job.pk} failed: {e}')
```

W bloku `except Exception`:

```python
        job.mark_failed(f'UNEXPECTED ERROR — {e}')
        send_notification.delay(job.pk)
        send_webhook.delay(job.pk)
        log_callback('error', f'UNEXPECTED ERROR — {e}')
        logger.error(f'Transfer job {job.pk} unexpected error: {e}')
        raise
```

- [ ] **Krok 5: Uruchom wszystkie testy workera — powinny PASS**

```bash
cd services/worker && pytest -v
```

Oczekiwany output: wszystkie testy PASS. Sprawdź że `TestExecuteTransferDispatchesNotification` nadal przechodzi.

- [ ] **Krok 6: Commit**

```bash
git add services/worker/tasks.py \
        services/worker/tests/test_tasks.py
git commit -m "feat: add send_webhook Celery task, dispatch after transfer done/failed"
```

---

## Task 4: Endpoint `test_webhook` w web service (TDD)

**Files:**
- Modify: `services/web/requirements.txt`
- Modify: `services/web/apps/accounts/tests/test_views.py`
- Modify: `services/web/apps/accounts/views.py`
- Modify: `services/web/apps/accounts/urls.py`

- [ ] **Krok 1: Dodaj `requests` do wymagań web service**

W `services/web/requirements.txt` dopisz po `bcrypt==4.*`:

```
requests==2.*
```

- [ ] **Krok 2: Napisz testy — nowa klasa `TestTestWebhookView`**

Dopisz na końcu `services/web/apps/accounts/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestTestWebhookView:
    def test_requires_login(self, client):
        url = reverse('accounts:test_webhook')
        response = client.post(url, {'webhook_url': 'http://hooks.example.com/'})
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_returns_ok_on_success(self, auth_client):
        url = reverse('accounts:test_webhook')
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch('apps.accounts.views.requests.post', return_value=mock_resp):
            response = auth_client.post(url, {'webhook_url': 'http://hooks.example.com/'})
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True
        assert data['code'] == 200

    def test_returns_error_on_connection_refused(self, auth_client):
        import requests as req
        url = reverse('accounts:test_webhook')
        with patch('apps.accounts.views.requests.post',
                   side_effect=req.ConnectionError('Connection refused')):
            response = auth_client.post(url, {'webhook_url': 'http://hooks.example.com/'})
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is False
        assert 'Connection refused' in data['error']

    def test_returns_error_on_missing_url(self, auth_client):
        url = reverse('accounts:test_webhook')
        response = auth_client.post(url, {'webhook_url': ''})
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is False
        assert 'URL' in data['error']
```

- [ ] **Krok 3: Uruchom testy — powinny FAIL**

```bash
docker compose run --rm web pytest apps/accounts/tests/test_views.py::TestTestWebhookView -v
```

Oczekiwany output: `NoReverseMatch` — URL `test_webhook` nie istnieje.

- [ ] **Krok 4: Zaimplementuj widok `test_webhook` w `views.py`**

W `services/web/apps/accounts/views.py` dodaj import na górze:

```python
import requests
from django.http import JsonResponse
```

Dodaj widok na końcu pliku:

```python
@login_required
@require_POST
def test_webhook(request):
    url = request.POST.get('webhook_url', '').strip()
    if not url:
        return JsonResponse({'ok': False, 'error': 'Brak URL'})
    payload = {
        'job_id': 0,
        'status': 'test',
        'source_path': '/test/source',
        'destination_path': '/test/destination',
        'connection': 'TEST',
        'started_at': None,
        'finished_at': None,
        'error': None,
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        return JsonResponse({'ok': True, 'code': resp.status_code})
    except requests.RequestException as e:
        return JsonResponse({'ok': False, 'error': str(e)})
```

- [ ] **Krok 5: Dodaj URL w `urls.py`**

W `services/web/apps/accounts/urls.py` dodaj wpis:

```python
urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.users_list, name='users'),
    path('profile/', views.profile_view, name='profile'),
    path('test-webhook/', views.test_webhook, name='test_webhook'),
]
```

- [ ] **Krok 6: Uruchom testy — powinny PASS**

```bash
docker compose run --rm web pytest apps/accounts/tests/test_views.py::TestTestWebhookView -v
```

Oczekiwany output: 4 testy PASS.

- [ ] **Krok 7: Zbuduj web image z nową zależnością i uruchom wszystkie testy web**

```bash
docker compose build web
docker compose run --rm web pytest apps/ -v
```

Oczekiwany output: wszystkie testy PASS.

- [ ] **Krok 8: Commit**

```bash
git add services/web/requirements.txt \
        services/web/apps/accounts/views.py \
        services/web/apps/accounts/urls.py \
        services/web/apps/accounts/tests/test_views.py
git commit -m "feat: add test_webhook endpoint with HTMX-ready JSON response"
```

---

## Task 5: ProfileForm — pola webhook + sekcja w szablonie

**Files:**
- Modify: `services/web/apps/accounts/forms.py`
- Modify: `services/web/apps/accounts/tests/test_views.py`
- Modify: `services/web/templates/accounts/profile.html`

- [ ] **Krok 1: Zaktualizuj istniejący test profilu**

W `services/web/apps/accounts/tests/test_views.py` w klasie `TestProfileView` zmień `test_post_saves_prefs_and_redirects` — dodaj pola webhook:

```python
    def test_post_saves_prefs_and_redirects(self, auth_client, regular_user):
        url = reverse('accounts:profile')
        response = auth_client.post(url, {
            'email': 'updated@example.com',
            'notify_on_done': True,
            'notify_on_failed': False,
            'webhook_url': 'http://hooks.slack.com/test',
            'webhook_on_done': True,
            'webhook_on_failed': False,
        })
        assert response.status_code == 302
        regular_user.refresh_from_db()
        assert regular_user.email == 'updated@example.com'
        assert regular_user.notify_on_done is True
        assert regular_user.notify_on_failed is False
        assert regular_user.webhook_url == 'http://hooks.slack.com/test'
        assert regular_user.webhook_on_done is True
        assert regular_user.webhook_on_failed is False
```

- [ ] **Krok 2: Uruchom test — powinien FAIL**

```bash
docker compose run --rm web pytest apps/accounts/tests/test_views.py::TestProfileView::test_post_saves_prefs_and_redirects -v
```

Oczekiwany output: FAIL — `webhook_url` nie zapisuje się (brakuje w formularzu).

- [ ] **Krok 3: Zaktualizuj `ProfileForm`**

Zastąp zawartość `services/web/apps/accounts/forms.py`:

```python
from django import forms
from django.contrib.auth import get_user_model


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)


class ProfileForm(forms.ModelForm):
    class Meta:
        model  = get_user_model()
        fields = [
            'email',
            'notify_on_done',
            'notify_on_failed',
            'webhook_url',
            'webhook_on_done',
            'webhook_on_failed',
        ]
        labels = {
            'email':             'Adres email',
            'notify_on_done':    'Powiadamiaj o sukcesach transferu',
            'notify_on_failed':  'Powiadamiaj o błędach transferu',
            'webhook_url':       'Webhook URL',
            'webhook_on_done':   'Webhook przy sukcesie transferu',
            'webhook_on_failed': 'Webhook przy błędzie transferu',
        }
```

- [ ] **Krok 4: Uruchom test — powinien PASS**

```bash
docker compose run --rm web pytest apps/accounts/tests/test_views.py::TestProfileView -v
```

Oczekiwany output: wszystkie testy klasy PASS.

- [ ] **Krok 5: Dodaj sekcję webhook do szablonu profilu**

W `services/web/templates/accounts/profile.html` dodaj nową sekcję między zamknięciem sekcji email (`</div>`) a ostatnim `</div>{% endblock %}`:

```html
  <div class="panel-section">
    <div class="panel-subheader">[ WEBHOOK ]</div>
    <div class="field-row">
      <label class="label" for="{{ form.webhook_url.id_for_label }}">WEBHOOK URL:</label>
      {{ form.webhook_url }}
      {% if form.webhook_url.errors %}
        <span class="error">{{ form.webhook_url.errors|join:", " }}</span>
      {% endif %}
      <button type="button" class="btn btn-sm"
              hx-post="{% url 'accounts:test_webhook' %}"
              hx-include="[name='webhook_url']"
              hx-target="#webhook-test-result"
              hx-swap="innerHTML">[ TEST ]</button>
    </div>
    <div id="webhook-test-result" class="field-row"></div>
    <script>
      document.body.addEventListener('htmx:afterRequest', function(evt) {
        if (!evt.detail.successful) return;
        var el = document.getElementById('webhook-test-result');
        if (!el) return;
        try {
          var data = JSON.parse(evt.detail.xhr.responseText);
          if (data.ok) {
            el.innerHTML = '<span class="msg-success">&gt; OK &mdash; ' + data.code + '</span>';
          } else {
            el.innerHTML = '<span class="error">&gt; ERROR &mdash; ' + data.error + '</span>';
          }
        } catch(e) {}
      });
    </script>
    <div class="field-row checkbox-row">
      {{ form.webhook_on_failed }}
      <label for="{{ form.webhook_on_failed.id_for_label }}">
        {{ form.webhook_on_failed.label|upper }}
      </label>
    </div>
    <div class="field-row checkbox-row">
      {{ form.webhook_on_done }}
      <label for="{{ form.webhook_on_done.id_for_label }}">
        {{ form.webhook_on_done.label|upper }}
      </label>
    </div>
    {% if user.webhook_url %}
    <div class="field-row">
      <span class="label">STATUS:</span>
      <span class="value">&gt; AKTYWNY</span>
    </div>
    {% endif %}
  </div>
```

Pełny szablon po zmianach (`services/web/templates/accounts/profile.html`):

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

      <div class="panel-subheader">[ WEBHOOK ]</div>
      <div class="field-row">
        <label class="label" for="{{ form.webhook_url.id_for_label }}">WEBHOOK URL:</label>
        {{ form.webhook_url }}
        {% if form.webhook_url.errors %}
          <span class="error">{{ form.webhook_url.errors|join:", " }}</span>
        {% endif %}
        <button type="button" class="btn btn-sm"
                hx-post="{% url 'accounts:test_webhook' %}"
                hx-include="[name='webhook_url']"
                hx-target="#webhook-test-result"
                hx-swap="innerHTML">[ TEST ]</button>
      </div>
      <div id="webhook-test-result" class="field-row"></div>
      <script>
        document.body.addEventListener('htmx:afterRequest', function(evt) {
          if (!evt.detail.successful) return;
          var el = document.getElementById('webhook-test-result');
          if (!el) return;
          try {
            var data = JSON.parse(evt.detail.xhr.responseText);
            if (data.ok) {
              el.innerHTML = '<span class="msg-success">&gt; OK &mdash; ' + data.code + '</span>';
            } else {
              el.innerHTML = '<span class="error">&gt; ERROR &mdash; ' + data.error + '</span>';
            }
          } catch(e) {}
        });
      </script>
      <div class="field-row checkbox-row">
        {{ form.webhook_on_failed }}
        <label for="{{ form.webhook_on_failed.id_for_label }}">
          {{ form.webhook_on_failed.label|upper }}
        </label>
      </div>
      <div class="field-row checkbox-row">
        {{ form.webhook_on_done }}
        <label for="{{ form.webhook_on_done.id_for_label }}">
          {{ form.webhook_on_done.label|upper }}
        </label>
      </div>
      {% if user.webhook_url %}
      <div class="field-row">
        <span class="label">WEBHOOK STATUS:</span>
        <span class="value">&gt; AKTYWNY</span>
      </div>
      {% endif %}

      <div class="form-actions">
        <button type="submit" class="btn">[ ZAPISZ USTAWIENIA ]</button>
      </div>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Krok 6: Uruchom wszystkie testy web i worker**

```bash
docker compose run --rm web pytest apps/ -v
cd services/worker && pytest -v
```

Oczekiwany output:
- Web: wszystkie testy PASS (poprzednie + `TestTestWebhookView` 4 testy + `TestProfileView` zaktualizowany)
- Worker: wszystkie testy PASS (poprzednie + `TestSendWebhookNotification` 8 testów + `TestSendWebhookTask` 2 + `TestExecuteTransferDispatchesWebhook` 2)

- [ ] **Krok 7: Commit**

```bash
git add services/web/apps/accounts/forms.py \
        services/web/apps/accounts/tests/test_views.py \
        services/web/templates/accounts/profile.html
git commit -m "feat: add webhook fields to ProfileForm and profile UI with HTMX test button"
```

---

## Weryfikacja końcowa

- [ ] **Uruchom pełny zestaw testów**

```bash
docker compose run --rm web pytest apps/ -v --tb=short
cd services/worker && pytest -v --tb=short
```

Oczekiwany output:
- Web: min. 97 + 4 (TestTestWebhookView) = ~101 testów PASS
- Worker: min. 56 + 8 + 2 + 2 = ~68 testów PASS, 0 failed

- [ ] **Restart serwisów i sprawdź UI**

```bash
docker compose build web
docker compose up -d
```

Otwórz `http://localhost/accounts/profile/` — powinna być widoczna sekcja `[ WEBHOOK ]` z polem URL i przyciskiem `[ TEST ]`.
