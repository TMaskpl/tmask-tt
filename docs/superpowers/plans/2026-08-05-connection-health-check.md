# Health-check połączeń w tle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cykliczny (co godzinę) automatyczny test wszystkich zapisanych `Connection` (SSH/Postgres/MySQL/MSSQL), zapisujący wynik na modelu i wysyłający powiadomienie tylko przy zmianie stanu (nowa awaria / odzyskanie).

**Architecture:** Parent task Celery `connections.health_check_all` dispatchuje po jednym child tasku `connections.health_check_one` na każde `Connection` (izolacja — jedno zawieszone połączenie nie blokuje reszty). Child task reużywa istniejące testery (`apps.connections.ssh_tester`/`pg_tester`/`mysql_tester`/`mssql_tester`), zapisuje wynik na 3 nowych polach `Connection`, i przy przejściu stanu dispatchuje `connections.send_health_notification`, który reużywa istniejące flagi `*_on_failed` właściciela i (dla webhooka) istniejący circuit breaker.

**Tech Stack:** Django 5.x, Celery 5.x + django-celery-beat, paramiko/psycopg2/pymysql/pyodbc (już w projekcie), pytest + pytest-django.

## Global Constraints

- Timeout testera: 10s — już ustalone w `ssh_tester`/`pg_tester`/`mysql_tester`/`mssql_tester`, bez zmian.
- Częstotliwość cyklu: co 1 godzinę (`IntervalSchedule(every=1, period='hours')`).
- Health-check obejmuje **wszystkie** `Connection` — brak pola `is_active`, brak filtrowania.
- Powiadomienia bramkowane wyłącznie istniejącymi flagami `notify_on_failed`/`webhook_on_failed`/`telegram_on_failed` na `User` — zero nowych pól na `User`.
- Powiadomienie wysyłane wyłącznie przy zmianie stanu: `→failed` z dowolnego stanu ≠ `failed` (w tym pierwsze sprawdzenie `unknown→failed`), oraz `failed→ok`. Nigdy przy powtórnym potwierdzeniu tego samego stanu, nigdy przy pierwszym `unknown→ok`.
- `ConfigAuditLog` pozostaje nietknięty — health-check nie pisze tam wpisów.
- Kind połączenia i status health-check porównywane przez literały stringowe (`'postgres'`, `'mysql'`, `'mssql'`, `'ok'`, `'failed'`, `'unknown'`) — nie przez importowane stałe z `apps.connections.models`, bo `services/worker/tests/conftest.py` stubuje `apps.connections.models` jako `MagicMock()` (patrz Task 2) — dokładnie ten sam wzorzec co istniejące porównanie `job.connection.protocol == 'sftp'` w `services/worker/tasks.py`.
- Worker i web budują obraz przez `COPY` (nie live-mount) — po każdej zmianie kodu w `services/worker/` lub `services/web/apps/connections/` trzeba jawnie `docker compose build <serwis>` przed `docker compose run`, inaczej testy uruchomią się na starym obrazie.

---

## Task 1: Model — pola health-check + migracje

**Files:**
- Modify: `services/web/apps/connections/models.py`
- Create: `services/web/apps/connections/migrations/0010_connection_health_fields.py`
- Create: `services/web/apps/connections/migrations/0011_connection_health_check_periodic_task.py`
- Test: `services/web/apps/connections/tests/test_models.py`

**Interfaces:**
- Produces: `Connection.health_status` (str, `'unknown'|'ok'|'failed'`, default `'unknown'`), `Connection.health_checked_at` (datetime|None), `Connection.health_error` (str, default `''`). Task 2 i Task 3 czytają/zapisują te pola bezpośrednio po nazwie — literały stringowe dla wartości, nie importowane stałe (patrz Global Constraints).

- [ ] **Step 1: Napisz failing testy dla nowych pól**

Dopisz na końcu `services/web/apps/connections/tests/test_models.py` (przed ostatnią klasą `TestConnectionDbKinds`, jako nowa klasa na końcu pliku):

```python
@pytest.mark.django_db
class TestConnectionHealthFields:
    def test_health_status_defaults_to_unknown(self, regular_user):
        conn = Connection.objects.create(
            owner=regular_user, name='X', host='h', port=22,
            username='u', password='p', protocol='sftp',
        )
        assert conn.health_status == 'unknown'

    def test_health_checked_at_defaults_to_none(self, regular_user):
        conn = Connection.objects.create(
            owner=regular_user, name='X', host='h', port=22,
            username='u', password='p', protocol='sftp',
        )
        assert conn.health_checked_at is None

    def test_health_error_defaults_to_empty_string(self, regular_user):
        conn = Connection.objects.create(
            owner=regular_user, name='X', host='h', port=22,
            username='u', password='p', protocol='sftp',
        )
        assert conn.health_error == ''

    def test_health_status_accepts_ok_and_failed(self, regular_user):
        conn = Connection.objects.create(
            owner=regular_user, name='X', host='h', port=22,
            username='u', password='p', protocol='sftp',
            health_status='failed', health_error='CONNECTION FAILED — timeout',
        )
        conn.refresh_from_db()
        assert conn.health_status == 'failed'
        assert conn.health_error == 'CONNECTION FAILED — timeout'
```

- [ ] **Step 2: Uruchom testy, potwierdź failure**

Run: `docker compose build web-test && docker compose --profile test run --rm web-test python -m pytest apps/connections/tests/test_models.py -q`
Expected: `FAIL` — `TypeError: 'health_status' is an invalid keyword argument` (pole jeszcze nie istnieje).

- [ ] **Step 3: Dodaj pola na modelu**

W `services/web/apps/connections/models.py` dodaj po istniejącym polu `db_name` (przed `created_at`):

```python
    health_status = models.CharField(
        max_length=10,
        choices=[('unknown', 'Unknown'), ('ok', 'OK'), ('failed', 'Failed')],
        default='unknown',
    )
    health_checked_at = models.DateTimeField(null=True, blank=True)
    health_error = models.TextField(blank=True, default='')
```

Plik po zmianie (fragment, dla orientacji — pełny model, kolejność pól):

```python
class Connection(models.Model):
    owner    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='connections')
    name     = models.CharField(max_length=100)
    host     = models.CharField(max_length=255)
    port     = models.IntegerField(default=22)
    username = models.CharField(max_length=100)
    password = EncryptedCharField(max_length=500, null=True, blank=True)
    ssh_key  = EncryptedTextField(null=True, blank=True)
    ssh_key_passphrase = EncryptedCharField(max_length=500, blank=True, default='')
    protocol = models.CharField(max_length=10, choices=PROTOCOL_CHOICES, default=PROTOCOL_SFTP)
    compress = models.BooleanField(default=False)
    encrypt  = models.BooleanField(default=False)
    strict_host_key_checking = models.BooleanField(default=True)
    known_host_key = models.TextField(blank=True, default='')
    dry_run_before_transfer = models.BooleanField(default=False)
    verify_checksum = models.BooleanField(default=False)
    kind     = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_SSH)
    db_name  = models.CharField(max_length=255, blank=True)
    health_status = models.CharField(
        max_length=10,
        choices=[('unknown', 'Unknown'), ('ok', 'OK'), ('failed', 'Failed')],
        default='unknown',
    )
    health_checked_at = models.DateTimeField(null=True, blank=True)
    health_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
```

- [ ] **Step 4: Wygeneruj i skoryguj migrację schematu**

Run: `docker compose build web-test && docker compose --profile test run --rm web-test python manage.py makemigrations connections`

Powinno to wygenerować `services/web/apps/connections/migrations/0010_connection_health_fields.py`. Sprawdź, że wygenerowany plik odpowiada (jeśli nazwa/treść się różni, dostosuj ręcznie do dokładnie tej postaci — kolejność `AddField` w porządku alfabetycznym pól jest tym, co Django wygeneruje domyślnie):

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('connections', '0009_connection_kind_mysql_mssql'),
    ]

    operations = [
        migrations.AddField(
            model_name='connection',
            name='health_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='connection',
            name='health_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='connection',
            name='health_status',
            field=models.CharField(choices=[('unknown', 'Unknown'), ('ok', 'OK'), ('failed', 'Failed')], default='unknown', max_length=10),
        ),
    ]
```

- [ ] **Step 5: Uruchom testy, potwierdź pass**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/connections/tests/test_models.py -q`
Expected: `PASS` (wszystkie testy z Step 1 + istniejące testy modelu).

- [ ] **Step 6: Dodaj migrację rejestrującą `PeriodicTask`**

Utwórz `services/web/apps/connections/migrations/0011_connection_health_check_periodic_task.py` — wzorem `services/web/apps/transfers/migrations/0005_transfers_retention_periodic_task.py`:

```python
from django.db import migrations


def create_health_check_task(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=1, period='hours'
        )
        PeriodicTask.objects.get_or_create(
            name='connection-health-check',
            defaults={
                'interval': schedule,
                'task': 'connections.health_check_all',
                'enabled': True,
            }
        )
    except Exception:  # nosec B110 — django_celery_beat tables may not exist yet on first migrate
        pass


def remove_health_check_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='connection-health-check').delete()
    except Exception:  # nosec B110 — safe: only deletes if table exists
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('connections', '0010_connection_health_fields'),
        ('django_celery_beat', '0001_initial'),
    ]
    operations = [migrations.RunPython(create_health_check_task, remove_health_check_task)]
```

Ta migracja nie ma dedykowanego testu — zgodnie z istniejącą praktyką w projekcie (`cleanup-orphan-jobs`/`cleanup-old-transfers` też nie mają testów migracji).

- [ ] **Step 7: Zastosuj migracje i uruchom pełen zestaw testów apki**

Run: `docker compose --profile test run --rm web-test python manage.py migrate connections`
Expected: `Applying connections.0010_connection_health_fields... OK` i `Applying connections.0011_connection_health_check_periodic_task... OK`.

Run: `docker compose --profile test run --rm web-test python -m pytest apps/connections/ -q`
Expected: `PASS`, 0 failed.

- [ ] **Step 8: Commit**

```bash
git add services/web/apps/connections/models.py \
        services/web/apps/connections/migrations/0010_connection_health_fields.py \
        services/web/apps/connections/migrations/0011_connection_health_check_periodic_task.py \
        services/web/apps/connections/tests/test_models.py
git commit -m "feat(connections): add health-check fields + hourly PeriodicTask registration"
```

---

## Task 2: Worker — cykliczne taski Celery + powiadomienia

**Files:**
- Modify: `services/worker/tasks.py`
- Modify: `services/worker/notifications.py`
- Modify: `services/worker/tests/conftest.py`
- Create: `services/web/templates/notifications/connection_health_failed.txt`
- Create: `services/web/templates/notifications/connection_health_failed.html`
- Create: `services/web/templates/notifications/connection_health_recovered.txt`
- Create: `services/web/templates/notifications/connection_health_recovered.html`
- Test: `services/worker/tests/test_tasks.py`
- Test: `services/worker/tests/test_notifications.py`

**Interfaces:**
- Consumes: `Connection.health_status`/`health_checked_at`/`health_error` (Task 1). Testery `apps.connections.ssh_tester.test_connection(connection) -> {success: bool, message: str}` (i analogiczne `pg_tester`/`mysql_tester`/`mssql_tester`, ta sama sygnatura) — już istnieją, tylko importowane.
- Produces: Celery tasks `connections.health_check_all()`, `connections.health_check_one(connection_id: int)`, `connections.send_health_notification(connection_id: int, status: str)` w `tasks.py`. Funkcje `send_connection_health_email(connection, status: str) -> bool`, `send_connection_health_telegram(connection, status: str) -> bool`, `send_connection_health_webhook(connection, status: str) -> bool` w `notifications.py` — Task 3 (UI) ich nie używa, ale muszą istnieć z dokładnie tymi nazwami/sygnaturami bo `tasks.py` je importuje.

- [ ] **Step 1: Odblokuj importy testerów w środowisku testowym workera**

`services/worker/tests/conftest.py` stubuje `apps.connections`/`apps.connections.models` jako `MagicMock()`, żeby `tasks.py` mógł się zaimportować bez pełnej apki Django. Task 2 dodaje do `tasks.py` importy z `apps.connections.ssh_tester`/`pg_tester`/`mysql_tester`/`mssql_tester` — te submoduły też muszą być stubowane, inaczej import padnie z `ModuleNotFoundError` (MagicMock nie jest prawdziwym pakietem z `__path__`).

W `services/worker/tests/conftest.py` dodaj cztery linie zaraz po istniejącej `sys.modules.setdefault('apps.connections.models', MagicMock())`:

```python
sys.modules.setdefault('apps.connections.ssh_tester', MagicMock())
sys.modules.setdefault('apps.connections.pg_tester', MagicMock())
sys.modules.setdefault('apps.connections.mysql_tester', MagicMock())
sys.modules.setdefault('apps.connections.mssql_tester', MagicMock())
```

Plik po zmianie, fragment (blok stubów, kolejność zachowana, cztery nowe linie na końcu):

```python
sys.modules.setdefault('apps.transfers', MagicMock())
sys.modules.setdefault('apps.transfers.models', MagicMock())
sys.modules.setdefault('apps.connections', MagicMock())
sys.modules.setdefault('apps.connections.models', MagicMock())
sys.modules.setdefault('apps.connections.ssh_tester', MagicMock())
sys.modules.setdefault('apps.connections.pg_tester', MagicMock())
sys.modules.setdefault('apps.connections.mysql_tester', MagicMock())
sys.modules.setdefault('apps.connections.mssql_tester', MagicMock())
sys.modules.setdefault('apps.db_transfers', MagicMock())
sys.modules.setdefault('apps.db_transfers.models', MagicMock())
sys.modules.setdefault('apps.webhook_deliveries', MagicMock())
sys.modules.setdefault('apps.webhook_deliveries.models', MagicMock())
sys.modules.setdefault('apps.webhook_deliveries.services', MagicMock())
```

Ten krok sam w sobie nic nie testuje (żadne nowe importy jeszcze nie istnieją w `tasks.py`) — commit dopiero na końcu taska razem z resztą.

- [ ] **Step 2: Napisz failing testy dla funkcji powiadomień w `notifications.py`**

Dopisz na końcu `services/worker/tests/test_notifications.py`:

```python
class TestSendConnectionHealthEmail:
    def _make_connection(self, status='failed', email='u@example.com', notify_on_failed=True, error='CONNECTION FAILED — timeout'):
        conn = MagicMock()
        conn.pk = 7
        conn.name = 'ProdSSH'
        conn.host = '10.0.0.5'
        conn.port = 22
        conn.health_error = error
        conn.owner = MagicMock()
        conn.owner.email = email
        conn.owner.notify_on_failed = notify_on_failed
        return conn

    def test_skips_if_no_email(self):
        from notifications import send_connection_health_email
        conn = self._make_connection(email='')
        with patch('notifications.send_mail') as mock_mail:
            result = send_connection_health_email(conn, 'failed')
        assert result is False
        mock_mail.assert_not_called()

    def test_skips_if_notify_on_failed_false(self):
        from notifications import send_connection_health_email
        conn = self._make_connection(notify_on_failed=False)
        with patch('notifications.send_mail') as mock_mail:
            result = send_connection_health_email(conn, 'failed')
        assert result is False
        mock_mail.assert_not_called()

    def test_sends_email_on_failed(self):
        from notifications import send_connection_health_email
        conn = self._make_connection()
        with patch('notifications.send_mail') as mock_mail, \
             patch('notifications._render_connection_health_notification', return_value=('subj', 'plain', '<html>')):
            result = send_connection_health_email(conn, 'failed')
        assert result is True
        mock_mail.assert_called_once()
        assert 'u@example.com' in mock_mail.call_args[0][3]

    def test_sends_email_on_recovered(self):
        from notifications import send_connection_health_email
        conn = self._make_connection()
        with patch('notifications.send_mail') as mock_mail, \
             patch('notifications._render_connection_health_notification', return_value=('subj', 'plain', '<html>')):
            result = send_connection_health_email(conn, 'ok')
        assert result is True
        mock_mail.assert_called_once()


class TestSendConnectionHealthTelegram:
    def _make_connection(self, chat_id='123', telegram_on_failed=True):
        conn = MagicMock()
        conn.name = 'ProdSSH'
        conn.host = '10.0.0.5'
        conn.port = 22
        conn.health_error = 'CONNECTION FAILED — timeout'
        conn.owner = MagicMock()
        conn.owner.telegram_chat_id = chat_id
        conn.owner.telegram_on_failed = telegram_on_failed
        return conn

    def test_skips_if_no_chat_id(self):
        from notifications import send_connection_health_telegram
        conn = self._make_connection(chat_id='')
        with patch('notifications.requests') as mock_requests:
            result = send_connection_health_telegram(conn, 'failed')
        assert result is False
        mock_requests.post.assert_not_called()

    def test_skips_if_telegram_on_failed_false(self):
        from notifications import send_connection_health_telegram
        conn = self._make_connection(telegram_on_failed=False)
        with patch('notifications.requests') as mock_requests:
            result = send_connection_health_telegram(conn, 'failed')
        assert result is False
        mock_requests.post.assert_not_called()

    def test_skips_if_no_bot_token(self):
        from notifications import send_connection_health_telegram
        conn = self._make_connection()
        with patch('notifications.settings') as mock_settings, patch('notifications.requests') as mock_requests:
            mock_settings.TELEGRAM_BOT_TOKEN = ''
            result = send_connection_health_telegram(conn, 'failed')
        assert result is False
        mock_requests.post.assert_not_called()

    def test_sends_telegram_on_failed(self):
        from notifications import send_connection_health_telegram
        conn = self._make_connection()
        with patch('notifications.settings') as mock_settings, patch('notifications.requests') as mock_requests:
            mock_settings.TELEGRAM_BOT_TOKEN = 'tok'
            mock_requests.post.return_value.raise_for_status.return_value = None
            result = send_connection_health_telegram(conn, 'failed')
        assert result is True
        mock_requests.post.assert_called_once()
        payload = mock_requests.post.call_args[1]['json']
        assert payload['chat_id'] == '123'
        assert 'FAILED' in payload['text']

    def test_sends_telegram_on_recovered(self):
        from notifications import send_connection_health_telegram
        conn = self._make_connection()
        with patch('notifications.settings') as mock_settings, patch('notifications.requests') as mock_requests:
            mock_settings.TELEGRAM_BOT_TOKEN = 'tok'
            mock_requests.post.return_value.raise_for_status.return_value = None
            result = send_connection_health_telegram(conn, 'ok')
        assert result is True
        payload = mock_requests.post.call_args[1]['json']
        assert 'RECOVERED' in payload['text']


class TestSendConnectionHealthWebhook:
    def _make_connection(self, webhook_url='http://hooks.example.com/', webhook_on_failed=True):
        conn = MagicMock()
        conn.pk = 7
        conn.name = 'ProdSSH'
        conn.host = '10.0.0.5'
        conn.port = 22
        conn.health_error = 'CONNECTION FAILED — timeout'
        conn.owner = MagicMock()
        conn.owner.webhook_url = webhook_url
        conn.owner.webhook_on_failed = webhook_on_failed
        return conn

    def test_skips_if_no_webhook_url(self):
        from notifications import send_connection_health_webhook
        conn = self._make_connection(webhook_url='')
        with patch('notifications.requests') as mock_requests:
            result = send_connection_health_webhook(conn, 'failed')
        assert result is False
        mock_requests.post.assert_not_called()

    def test_skips_if_webhook_on_failed_false(self):
        from notifications import send_connection_health_webhook
        conn = self._make_connection(webhook_on_failed=False)
        with patch('notifications.requests') as mock_requests:
            result = send_connection_health_webhook(conn, 'failed')
        assert result is False
        mock_requests.post.assert_not_called()

    def test_skips_if_url_targets_private_address(self):
        from notifications import send_connection_health_webhook
        conn = self._make_connection(webhook_url='http://127.0.0.1/hook')
        result = send_connection_health_webhook(conn, 'failed')
        assert result is False

    def test_sends_generic_payload_for_non_slack_url(self):
        from notifications import send_connection_health_webhook
        conn = self._make_connection()
        with patch('notifications.requests') as mock_requests, \
             patch('notifications.block_private_url'):
            mock_requests.post.return_value.raise_for_status.return_value = None
            result = send_connection_health_webhook(conn, 'failed')
        assert result is True
        payload = mock_requests.post.call_args[1]['json']
        assert payload['connection_id'] == 7
        assert payload['status'] == 'failed'

    def test_sends_slack_payload_for_slack_url(self):
        from notifications import send_connection_health_webhook
        conn = self._make_connection(webhook_url='https://hooks.slack.com/services/x')
        with patch('notifications.requests') as mock_requests, \
             patch('notifications.block_private_url'):
            mock_requests.post.return_value.raise_for_status.return_value = None
            result = send_connection_health_webhook(conn, 'ok')
        assert result is True
        payload = mock_requests.post.call_args[1]['json']
        assert 'text' in payload
        assert 'RECOVERED' in payload['text']
```

- [ ] **Step 3: Uruchom testy, potwierdź failure**

Run: `docker compose build worker && docker compose run --rm worker python -m pytest tests/test_notifications.py -q`
Expected: `FAIL` — `ImportError: cannot import name 'send_connection_health_email'` (funkcje jeszcze nie istnieją).

- [ ] **Step 4: Zaimplementuj funkcje powiadomień w `notifications.py`**

Dopisz na końcu `services/worker/notifications.py`:

```python
def _render_connection_health_notification(connection, status: str):
    template_name = 'connection_health_recovered' if status == 'ok' else 'connection_health_failed'
    label = 'RECOVERED' if status == 'ok' else 'FAILED'
    context = {'connection': connection, 'error': connection.health_error}
    subject = f'[TMask] Connection {connection.name} — HEALTH {label}'
    plain = render_to_string(f'notifications/{template_name}.txt', context)
    html  = render_to_string(f'notifications/{template_name}.html', context)
    return subject, plain, html


def send_connection_health_email(connection, status: str) -> bool:
    user = connection.owner
    if not user.email or not user.notify_on_failed:
        return False
    subject, plain, html = _render_connection_health_notification(connection, status)
    send_mail(
        subject,
        plain,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html,
        fail_silently=False,
    )
    return True


def send_connection_health_telegram(connection, status: str) -> bool:
    user = connection.owner
    if not user.telegram_chat_id or not user.telegram_on_failed:
        return False
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        return False

    icon = '✅' if status == 'ok' else '🔴'
    label = 'RECOVERED' if status == 'ok' else 'FAILED'
    lines = [
        f'{icon} <b>Connection {connection.name} — HEALTH {label}</b>',
        f'Host: <code>{connection.host}:{connection.port}</code>',
    ]
    if status == 'failed' and connection.health_error:
        lines.append(f'Błąd: {connection.health_error}')

    resp = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': user.telegram_chat_id, 'text': '\n'.join(lines), 'parse_mode': 'HTML'},
        timeout=10,
    )
    resp.raise_for_status()
    return True


def _build_connection_health_payload(connection, status: str) -> dict:
    return {
        'connection_id': connection.pk,
        'connection_name': connection.name,
        'status': status,
        'host': connection.host,
        'port': connection.port,
        'error': connection.health_error or None,
    }


def _build_connection_health_slack_payload(connection, status: str) -> dict:
    icon = ':white_check_mark:' if status == 'ok' else ':x:'
    label = 'RECOVERED' if status == 'ok' else 'FAILED'
    text = (
        f'{icon} *Connection {connection.name} — HEALTH {label}*\n'
        f'Host: `{connection.host}:{connection.port}`'
    )
    if status == 'failed' and connection.health_error:
        text += f'\nBłąd: {connection.health_error}'
    return {'text': text}


def send_connection_health_webhook(connection, status: str) -> bool:
    user = connection.owner
    if not user.webhook_url or not user.webhook_on_failed:
        return False
    try:
        block_private_url(user.webhook_url)
    except ValueError:
        return False

    if 'hooks.slack.com' in user.webhook_url:
        payload = _build_connection_health_slack_payload(connection, status)
    else:
        payload = _build_connection_health_payload(connection, status)

    resp = requests.post(user.webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    return True
```

- [ ] **Step 5: Utwórz szablony powiadomień**

`services/web/templates/notifications/connection_health_failed.txt`:

```
╔══════════════════════════════════════════════════╗
║  TMASK TRANSPORTER — CONNECTION HEALTH FAILED    ║
╚══════════════════════════════════════════════════╝

Połączenie "{{ connection.name }}" nie odpowiada na cykliczny health-check.

  HOST  : {{ connection.host }}:{{ connection.port }}
  KIND  : {{ connection.kind|upper }}
  ERROR : {{ error|default:"UNKNOWN ERROR" }}

--
TMask Transporter | ustawienia powiadomień: /accounts/profile/
```

`services/web/templates/notifications/connection_health_failed.html`:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { background:#0f172a; color:#f8fafc; font-family:sans-serif; padding:20px; }
  .header { border:1px solid #ef4444; border-radius:8px; padding:10px 20px; margin-bottom:20px; }
  .header h1 { color:#ef4444; font-size:16px; margin:0; letter-spacing:0.02em; }
  table { border-collapse:collapse; width:100%; }
  td { padding:4px 12px; color:#f8fafc; }
  td:first-child { color:#94a3b8; width:80px; }
  .error-row td { color:#ef4444; }
  .footer { margin-top:20px; border-top:1px solid #334155; padding-top:10px; font-size:11px; color:#64748b; }
</style>
</head>
<body>
  <div class="header">
    <h1>TMask Transporter — Connection Health Failed</h1>
  </div>
  <p>Połączenie "{{ connection.name }}" nie odpowiada na cykliczny health-check.</p>
  <table>
    <tr><td>HOST</td><td>{{ connection.host }}:{{ connection.port }}</td></tr>
    <tr><td>KIND</td><td>{{ connection.kind|upper }}</td></tr>
    <tr class="error-row"><td>ERROR</td><td>{{ error|default:"UNKNOWN ERROR" }}</td></tr>
  </table>
  <div class="footer">TMask Transporter &mdash; ustawienia powiadomień: /accounts/profile/</div>
</body>
</html>
```

`services/web/templates/notifications/connection_health_recovered.txt`:

```
╔══════════════════════════════════════════════════╗
║  TMASK TRANSPORTER — CONNECTION HEALTH RECOVERED ║
╚══════════════════════════════════════════════════╝

Połączenie "{{ connection.name }}" znów odpowiada poprawnie.

  HOST : {{ connection.host }}:{{ connection.port }}
  KIND : {{ connection.kind|upper }}

--
TMask Transporter | ustawienia powiadomień: /accounts/profile/
```

`services/web/templates/notifications/connection_health_recovered.html`:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { background:#0f172a; color:#f8fafc; font-family:sans-serif; padding:20px; }
  .header { border:1px solid #22c55e; border-radius:8px; padding:10px 20px; margin-bottom:20px; }
  .header h1 { color:#22c55e; font-size:16px; margin:0; letter-spacing:0.02em; }
  table { border-collapse:collapse; width:100%; }
  td { padding:4px 12px; color:#f8fafc; }
  td:first-child { color:#94a3b8; width:80px; }
  .footer { margin-top:20px; border-top:1px solid #334155; padding-top:10px; font-size:11px; color:#64748b; }
</style>
</head>
<body>
  <div class="header">
    <h1>TMask Transporter — Connection Health Recovered</h1>
  </div>
  <p>Połączenie "{{ connection.name }}" znów odpowiada poprawnie.</p>
  <table>
    <tr><td>HOST</td><td>{{ connection.host }}:{{ connection.port }}</td></tr>
    <tr><td>KIND</td><td>{{ connection.kind|upper }}</td></tr>
  </table>
  <div class="footer">TMask Transporter &mdash; ustawienia powiadomień: /accounts/profile/</div>
</body>
</html>
```

- [ ] **Step 6: Uruchom testy powiadomień, potwierdź pass**

Run: `docker compose build worker && docker compose run --rm worker python -m pytest tests/test_notifications.py -q`
Expected: `PASS`, w tym wszystkie testy z Step 2.

- [ ] **Step 7: Napisz failing testy dla tasków Celery**

Dopisz na końcu `services/worker/tests/test_tasks.py`:

```python
class TestHealthCheckAllTask:
    def test_dispatches_one_child_task_per_connection(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.health_check_one') as mock_health_check_one:
            MockConnection.objects.values_list.return_value = [1, 2, 3]
            from tasks import health_check_all
            health_check_all()
            assert mock_health_check_one.delay.call_count == 3
            mock_health_check_one.delay.assert_any_call(1)
            mock_health_check_one.delay.assert_any_call(2)
            mock_health_check_one.delay.assert_any_call(3)

    def test_no_connections_dispatches_nothing(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.health_check_one') as mock_health_check_one:
            MockConnection.objects.values_list.return_value = []
            from tasks import health_check_all
            health_check_all()
            mock_health_check_one.delay.assert_not_called()


class TestHealthCheckOneTask:
    def _mock_connection(self, MockConnection, kind='ssh', old_status='unknown'):
        mock_conn = MagicMock()
        mock_conn.pk = 5
        mock_conn.kind = kind
        mock_conn.health_status = old_status
        MockConnection.objects.select_related.return_value.get.return_value = mock_conn
        return mock_conn

    def test_logs_and_skips_when_connection_not_found(self):
        with patch('tasks.Connection') as MockConnection:
            MockConnection.objects.select_related.return_value.get.side_effect = Exception('not found')
            from tasks import health_check_one
            health_check_one(999)  # should not raise

    def test_dispatches_to_ssh_tester_for_ssh_kind(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='ssh')
            mock_ssh_test.return_value.success = True
            mock_ssh_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_ssh_test.assert_called_once_with(mock_conn)

    def test_dispatches_to_pg_tester_for_postgres_kind(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.pg_test_connection') as mock_pg_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='postgres')
            mock_pg_test.return_value.success = True
            mock_pg_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_pg_test.assert_called_once_with(mock_conn)

    def test_dispatches_to_mysql_tester_for_mysql_kind(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.mysql_test_connection') as mock_mysql_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='mysql')
            mock_mysql_test.return_value.success = True
            mock_mysql_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_mysql_test.assert_called_once_with(mock_conn)

    def test_dispatches_to_mssql_tester_for_mssql_kind(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.mssql_test_connection') as mock_mssql_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='mssql')
            mock_mssql_test.return_value.success = True
            mock_mssql_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_mssql_test.assert_called_once_with(mock_conn)

    def test_saves_ok_status_and_clears_error(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='ssh', old_status='failed')
            mock_ssh_test.return_value.success = True
            mock_ssh_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            assert mock_conn.health_status == 'ok'
            assert mock_conn.health_error == ''
            mock_conn.save.assert_called_once()

    def test_saves_failed_status_and_error_message(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification'):
            mock_conn = self._mock_connection(MockConnection, kind='ssh', old_status='unknown')
            mock_ssh_test.return_value.success = False
            mock_ssh_test.return_value.message = 'CONNECTION FAILED — timeout'
            from tasks import health_check_one
            health_check_one(5)
            assert mock_conn.health_status == 'failed'
            assert mock_conn.health_error == 'CONNECTION FAILED — timeout'

    def test_notifies_on_first_failure(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification') as mock_notify:
            self._mock_connection(MockConnection, kind='ssh', old_status='unknown')
            mock_ssh_test.return_value.success = False
            mock_ssh_test.return_value.message = 'CONNECTION FAILED — timeout'
            from tasks import health_check_one
            health_check_one(5)
            mock_notify.delay.assert_called_once_with(5, 'failed')

    def test_no_notification_on_first_ok(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification') as mock_notify:
            self._mock_connection(MockConnection, kind='ssh', old_status='unknown')
            mock_ssh_test.return_value.success = True
            mock_ssh_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_notify.delay.assert_not_called()

    def test_no_notification_when_still_failed(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification') as mock_notify:
            self._mock_connection(MockConnection, kind='ssh', old_status='failed')
            mock_ssh_test.return_value.success = False
            mock_ssh_test.return_value.message = 'CONNECTION FAILED — timeout'
            from tasks import health_check_one
            health_check_one(5)
            mock_notify.delay.assert_not_called()

    def test_notifies_on_recovery(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification') as mock_notify:
            self._mock_connection(MockConnection, kind='ssh', old_status='failed')
            mock_ssh_test.return_value.success = True
            mock_ssh_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_notify.delay.assert_called_once_with(5, 'ok')

    def test_no_notification_when_still_ok(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.ssh_test_connection') as mock_ssh_test, \
             patch('tasks.send_health_notification') as mock_notify:
            self._mock_connection(MockConnection, kind='ssh', old_status='ok')
            mock_ssh_test.return_value.success = True
            mock_ssh_test.return_value.message = 'CONNECTION OK'
            from tasks import health_check_one
            health_check_one(5)
            mock_notify.delay.assert_not_called()


class TestSendHealthNotificationTask:
    def _mock_connection(self, MockConnection, webhook_url='http://hooks.example.com/'):
        mock_conn = MagicMock()
        mock_conn.pk = 5
        mock_conn.owner.webhook_url = webhook_url
        mock_conn.owner.webhook_circuit_open_until = None
        MockConnection.objects.select_related.return_value.get.return_value = mock_conn
        return mock_conn

    def test_logs_and_skips_when_connection_not_found(self):
        with patch('tasks.Connection') as MockConnection:
            MockConnection.objects.select_related.return_value.get.side_effect = Exception('not found')
            from tasks import send_health_notification
            send_health_notification(999, 'failed')  # should not raise

    def test_calls_email_and_telegram(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.send_connection_health_email') as mock_email, \
             patch('tasks.send_connection_health_telegram') as mock_telegram, \
             patch('tasks.send_connection_health_webhook'), \
             patch('tasks.WebhookDeliveryLog'), \
             patch('tasks.circuit_is_open', return_value=False), \
             patch('tasks.record_success'):
            mock_conn = self._mock_connection(MockConnection)
            from tasks import send_health_notification
            send_health_notification(5, 'failed')
            mock_email.assert_called_once_with(mock_conn, 'failed')
            mock_telegram.assert_called_once_with(mock_conn, 'failed')

    def test_skips_webhook_when_no_url_configured(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.send_connection_health_email'), \
             patch('tasks.send_connection_health_telegram'), \
             patch('tasks.send_connection_health_webhook') as mock_webhook, \
             patch('tasks.WebhookDeliveryLog') as MockLog:
            self._mock_connection(MockConnection, webhook_url='')
            from tasks import send_health_notification
            send_health_notification(5, 'failed')
            mock_webhook.assert_not_called()
            MockLog.objects.create.assert_not_called()

    def test_skips_and_logs_when_circuit_open(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.send_connection_health_email'), \
             patch('tasks.send_connection_health_telegram'), \
             patch('tasks.send_connection_health_webhook') as mock_webhook, \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.circuit_is_open', return_value=True):
            self._mock_connection(MockConnection)
            from tasks import send_health_notification
            send_health_notification(5, 'failed')
            mock_webhook.assert_not_called()
            MockLog.objects.create.assert_called_once()
            assert MockLog.objects.create.call_args[1]['skipped'] is True

    def test_records_success_and_logs_delivery_on_success(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.send_connection_health_email'), \
             patch('tasks.send_connection_health_telegram'), \
             patch('tasks.send_connection_health_webhook', return_value=True), \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.circuit_is_open', return_value=False), \
             patch('tasks.record_success') as mock_record_success:
            mock_conn = self._mock_connection(MockConnection)
            from tasks import send_health_notification
            send_health_notification(5, 'ok')
            mock_record_success.assert_called_once()
            MockLog.objects.create.assert_called_once_with(
                user=mock_conn.owner, job=None, url='http://hooks.example.com/', success=True,
            )

    def test_records_failure_and_logs_delivery_on_exception(self):
        with patch('tasks.Connection') as MockConnection, \
             patch('tasks.send_connection_health_email'), \
             patch('tasks.send_connection_health_telegram'), \
             patch('tasks.send_connection_health_webhook', side_effect=Exception('boom')), \
             patch('tasks.WebhookDeliveryLog') as MockLog, \
             patch('tasks.circuit_is_open', return_value=False), \
             patch('tasks.record_failure') as mock_record_failure:
            mock_conn = self._mock_connection(MockConnection)
            from tasks import send_health_notification
            send_health_notification(5, 'failed')  # should not raise
            mock_record_failure.assert_called_once_with(mock_conn.owner)
```

- [ ] **Step 8: Uruchom testy, potwierdź failure**

Run: `docker compose build worker && docker compose run --rm worker python -m pytest tests/test_tasks.py -q`
Expected: `FAIL` — `AttributeError`/`ImportError` (`health_check_all`, `health_check_one`, `send_health_notification` jeszcze nie istnieją w `tasks.py`).

- [ ] **Step 9: Zaimplementuj taski w `tasks.py`**

W bloku importów na górze `services/worker/tasks.py`, zaraz po istniejącej linii `from apps.connections.models import Connection  # noqa: E402`, dodaj:

```python
from apps.connections.ssh_tester import test_connection as ssh_test_connection  # noqa: E402
from apps.connections.pg_tester import test_connection as pg_test_connection  # noqa: E402
from apps.connections.mysql_tester import test_connection as mysql_test_connection  # noqa: E402
from apps.connections.mssql_tester import test_connection as mssql_test_connection  # noqa: E402
```

Zamień istniejącą linię importu z `notifications`:

```python
from notifications import send_email_notification, send_webhook_notification, send_telegram_notification  # noqa: E402
```

na:

```python
from notifications import (  # noqa: E402
    send_email_notification, send_webhook_notification, send_telegram_notification,
    send_connection_health_email, send_connection_health_telegram, send_connection_health_webhook,
)
```

Na końcu `services/worker/tasks.py` (po istniejącym `cleanup_old_transfers`) dodaj:

```python
@app.task(name='connections.health_check_all')
def health_check_all():
    for connection_id in Connection.objects.values_list('pk', flat=True):
        health_check_one.delay(connection_id)


@app.task(name='connections.health_check_one')
def health_check_one(connection_id: int):
    try:
        connection = Connection.objects.select_related('owner').get(pk=connection_id)
    except Exception:
        logger.error(f'Connection {connection_id} not found — health check skipped')
        return

    if connection.kind == 'postgres':
        result = pg_test_connection(connection)
    elif connection.kind == 'mysql':
        result = mysql_test_connection(connection)
    elif connection.kind == 'mssql':
        result = mssql_test_connection(connection)
    else:
        result = ssh_test_connection(connection)

    from django.utils import timezone

    old_status = connection.health_status
    new_status = 'ok' if result.success else 'failed'

    connection.health_status = new_status
    connection.health_checked_at = timezone.now()
    connection.health_error = '' if result.success else result.message
    connection.save(update_fields=['health_status', 'health_checked_at', 'health_error'])

    became_failed = old_status != 'failed' and new_status == 'failed'
    recovered = old_status == 'failed' and new_status == 'ok'
    if became_failed or recovered:
        send_health_notification.delay(connection.pk, new_status)


@app.task(name='connections.send_health_notification')
def send_health_notification(connection_id: int, status: str):
    try:
        connection = Connection.objects.select_related('owner').get(pk=connection_id)
    except Exception:
        logger.error(f'Connection {connection_id} not found — health notification skipped')
        return

    send_connection_health_email(connection, status)
    send_connection_health_telegram(connection, status)

    user = connection.owner
    if not user.webhook_url:
        return
    if circuit_is_open(user):
        WebhookDeliveryLog.objects.create(
            user=user, job=None, url=user.webhook_url,
            success=False, skipped=True, error_message=CIRCUIT_SKIPPED_MESSAGE,
        )
        return
    try:
        sent = send_connection_health_webhook(connection, status)
    except Exception as exc:
        record_failure(user)
        WebhookDeliveryLog.objects.create(
            user=user, job=None, url=user.webhook_url, success=False, error_message=str(exc),
        )
        return
    if sent:
        record_success(user)
        WebhookDeliveryLog.objects.create(user=user, job=None, url=user.webhook_url, success=True)
```

- [ ] **Step 10: Uruchom testy, potwierdź pass**

Run: `docker compose run --rm worker python -m pytest tests/test_tasks.py tests/test_notifications.py -q`
Expected: `PASS`, 0 failed (wszystkie nowe testy z Step 7 + istniejące testy workera).

- [ ] **Step 11: Uruchom pełen zestaw testów workera**

Run: `docker compose run --rm worker python -m pytest tests/ -q`
Expected: `PASS`, 0 failed.

- [ ] **Step 12: Commit**

```bash
git add services/worker/tasks.py services/worker/notifications.py services/worker/tests/conftest.py \
        services/worker/tests/test_tasks.py services/worker/tests/test_notifications.py \
        services/web/templates/notifications/connection_health_failed.txt \
        services/web/templates/notifications/connection_health_failed.html \
        services/web/templates/notifications/connection_health_recovered.txt \
        services/web/templates/notifications/connection_health_recovered.html
git commit -m "feat(worker): connection health-check tasks + edge-triggered notifications"
```

---

## Task 3: UI — badge statusu w liście Connections

**Files:**
- Modify: `services/web/templates/connections/list.html`
- Test: `services/web/apps/connections/tests/test_views.py`

**Interfaces:**
- Consumes: `Connection.health_status` (`'unknown'|'ok'|'failed'`), `Connection.health_checked_at` (Task 1). Reużywa istniejące CSS klasy `status`/`status-done`/`status-failed`/`status-pending` z `services/web/static/css/crt.css` (już zdefiniowane dla statusów transferów — `status-done` zielony, `status-failed` czerwony, `status-pending` szary) — zero nowego CSS.

- [ ] **Step 1: Napisz failing test widoku**

Dopisz na końcu `services/web/apps/connections/tests/test_views.py`, jako nową klasę:

```python
@pytest.mark.django_db
class TestConnectionListHealthBadge:
    def test_shows_unknown_badge_by_default(self, auth_client, regular_user, make_connection):
        make_connection(regular_user, name='Fresh')
        response = auth_client.get(reverse('connections:list'))
        assert response.status_code == 200
        content = response.content.decode()
        assert 'status-pending' in content

    def test_shows_ok_badge_when_healthy(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, name='Healthy')
        conn.health_status = 'ok'
        conn.save(update_fields=['health_status'])
        response = auth_client.get(reverse('connections:list'))
        content = response.content.decode()
        assert 'status-done' in content

    def test_shows_failed_badge_with_error_tooltip(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, name='Broken')
        conn.health_status = 'failed'
        conn.health_error = 'CONNECTION FAILED — timeout'
        conn.save(update_fields=['health_status', 'health_error'])
        response = auth_client.get(reverse('connections:list'))
        content = response.content.decode()
        assert 'status-failed' in content
        assert 'CONNECTION FAILED — timeout' in content
```

- [ ] **Step 2: Uruchom testy, potwierdź failure**

Run: `docker compose build web-test && docker compose --profile test run --rm web-test python -m pytest apps/connections/tests/test_views.py::TestConnectionListHealthBadge -q`
Expected: `FAIL` — `assert 'status-pending' in content` nieprawda (badge jeszcze nie renderuje się w szablonie).

- [ ] **Step 3: Dodaj badge do `list.html`**

W `services/web/templates/connections/list.html` dodaj nagłówek kolumny `<th>Health</th>` zaraz po `<th>Utworzył</th>`:

```html
        <th>Compress</th><th>Encrypt</th><th>Utworzył</th><th>Health</th><th class="col-actions">Actions</th>
```

(zamienia istniejącą linię nagłówka tabeli — jedyna zmiana to dodanie `<th>Health</th>` przed `<th class="col-actions">`).

I dodaj odpowiadającą komórkę w `<tbody>`, zaraz po `<td>{{ conn.owner.username }}</td>`:

```html
        <td>
          {% if conn.health_status == 'ok' %}
          <span class="status status-done" title="Ostatnio sprawdzono: {{ conn.health_checked_at|date:'Y-m-d H:i' }}">OK</span>
          {% elif conn.health_status == 'failed' %}
          <span class="status status-failed" title="{{ conn.health_error }}">FAILED</span>
          {% else %}
          <span class="status status-pending" title="Jeszcze nie sprawdzono">—</span>
          {% endif %}
        </td>
```

Pełna zawartość `<tbody>` po zmianie (fragment, dla orientacji):

```html
      {% for conn in connections %}
      <tr>
        <td>{{ conn.name }}</td>
        <td>{{ conn.kind|upper }}</td>
        <td>{{ conn.host }}</td>
        <td>{{ conn.port }}</td>
        <td>{{ conn.protocol|upper }}</td>
        <td>{% if conn.compress %}Yes{% else %}—{% endif %}</td>
        <td>{% if conn.encrypt %}Yes{% else %}—{% endif %}</td>
        <td>{{ conn.owner.username }}</td>
        <td>
          {% if conn.health_status == 'ok' %}
          <span class="status status-done" title="Ostatnio sprawdzono: {{ conn.health_checked_at|date:'Y-m-d H:i' }}">OK</span>
          {% elif conn.health_status == 'failed' %}
          <span class="status status-failed" title="{{ conn.health_error }}">FAILED</span>
          {% else %}
          <span class="status status-pending" title="Jeszcze nie sprawdzono">—</span>
          {% endif %}
        </td>
        <td class="col-actions">
          <div class="row-actions">
            <button class="btn btn-small btn-warn"
              hx-get="{% url 'connections:test' conn.pk %}"
              hx-target="#test-result-{{ conn.pk }}"
              hx-swap="innerHTML">Test</button>
            {% if user.is_admin %}
            <a href="{% url 'connections:edit' conn.pk %}" class="btn btn-small">Edit</a>
            <form method="post" action="{% url 'connections:delete' conn.pk %}" class="inline-form"
              data-confirm="DELETE {{ conn.name }}?">
              {% csrf_token %}
              <button type="submit" class="btn btn-small btn-danger">Del</button>
            </form>
            {% endif %}
            <span id="test-result-{{ conn.pk }}" class="test-result"></span>
          </div>
        </td>
      </tr>
      {% endfor %}
```

- [ ] **Step 4: Uruchom testy, potwierdź pass**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/connections/tests/test_views.py::TestConnectionListHealthBadge -q`
Expected: `PASS`.

- [ ] **Step 5: Uruchom pełen zestaw testów apki connections**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/connections/ -q`
Expected: `PASS`, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add services/web/templates/connections/list.html services/web/apps/connections/tests/test_views.py
git commit -m "feat(connections): health-check status badge in connections list"
```

---

## Po zakończeniu wszystkich tasków

Uruchom pełen zestaw testów obu serwisów, żeby potwierdzić brak regresji poza zakresem tego planu:

Run: `docker compose --profile test run --rm web-test python -m pytest apps/ -q`
Run: `docker compose run --rm worker python -m pytest tests/ -q`

Expected: oba `PASS`, 0 failed.
