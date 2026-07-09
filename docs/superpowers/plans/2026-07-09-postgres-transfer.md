# Postgres → Postgres Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fourth transfer module — manual, on-demand Postgres → Postgres transfer of a whole database or a single table — reusing `Connection` (extended with a `kind` field) and a new `pg_dump | psql` worker module.

**Architecture:** `Connection.kind` (`ssh`/`postgres`) lets Postgres connections live in the existing connections list/form. A new app `apps/db_transfers` owns `PgTransferJob`/`PgTransferLog` (deliberately separate from `TransferJob`, per design decision). The worker gets a new `modules/postgres/` module that pipes `pg_dump` into `psql` via subprocess — the same mechanism handles whole-database and single-table transfers via `pg_dump --table`.

**Tech Stack:** Django 5.x, psycopg2 (already in both `web` and `worker` requirements), Celery, `pg_dump`/`psql` CLI (new: `postgresql-client` apt package in worker image).

**Reference:** Design spec `docs/superpowers/specs/2026-07-09-postgres-transfer-design.md`.

## Global Constraints

- `pg_dump` base flags (exact, both scopes): `--clean --if-exists --no-owner --no-privileges --verbose`
- `PGPASSWORD` passed via subprocess `env=`, **never** as a CLI argument (must be provable by a test asserting it's absent from `Popen` argv)
- Both `source_connection` and `dest_connection` on `PgTransferJob` must have `kind='postgres'`; `source_connection == dest_connection` is always rejected, regardless of scope
- `verify_row_count` mismatch → log level `warn`, job status stays `done` (data is already transferred, nothing to roll back)
- `PgTransferJob`/`PgTransferLog` are a **separate** model/app from `TransferJob`/`TransferLog` — no shared table, no shared list view
- `[ EXECUTE TRANSFER ]` requires a client-side `confirm()` before submit, wording depends on scope (whole DB vs table)
- No Scheduler integration, no REST API trigger, no exact progress percentage — out of scope for this plan

---

### Task 1: `Connection` model — `kind` + `db_name` fields

**Files:**
- Modify: `services/web/apps/connections/models.py`
- Create: `services/web/apps/connections/migrations/0003_connection_kind_and_db_name.py`
- Modify: `services/web/apps/connections/tests/test_models.py`

**Interfaces:**
- Produces: `apps.connections.models.KIND_SSH = 'ssh'`, `KIND_POSTGRES = 'postgres'`, `KIND_CHOICES`, `Connection.kind` (default `KIND_SSH`), `Connection.db_name` (`CharField`, blank=True). `Connection.clean()` raises `ValidationError` when `kind == KIND_POSTGRES` and `db_name` is empty.

- [ ] **Step 1: Write the failing tests**

Append to `services/web/apps/connections/tests/test_models.py`:

```python
    def test_kind_defaults_to_ssh(self, regular_user):
        conn = Connection(owner=regular_user, name='X', host='h', username='u', protocol='sftp')
        assert conn.kind == 'ssh'

    def test_can_create_postgres_kind_connection(self, regular_user):
        conn = Connection.objects.create(
            owner=regular_user, name='PG', host='10.0.0.5', port=5432,
            username='postgres', password='pass', db_name='proddb', kind='postgres',
        )
        assert conn.pk is not None
        assert conn.kind == 'postgres'
        assert conn.db_name == 'proddb'

    def test_clean_requires_db_name_for_postgres_kind(self, regular_user):
        from django.core.exceptions import ValidationError
        conn = Connection(owner=regular_user, name='PG', host='h', username='u', kind='postgres', db_name='')
        with pytest.raises(ValidationError):
            conn.clean()

    def test_clean_does_not_require_db_name_for_ssh_kind(self, regular_user):
        conn = Connection(owner=regular_user, name='X', host='h', username='u', kind='ssh', protocol='sftp')
        conn.clean()  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/web && pytest apps/connections/tests/test_models.py -v -k "kind or postgres_kind or db_name"`
Expected: FAIL — `Connection() got unexpected keyword argument 'kind'` / `'db_name'`

- [ ] **Step 3: Add the fields and validation**

In `services/web/apps/connections/models.py`, add after the existing `PROTOCOL_CHOICES` line:

```python
KIND_SSH = 'ssh'
KIND_POSTGRES = 'postgres'
KIND_CHOICES = [(KIND_SSH, 'SSH'), (KIND_POSTGRES, 'Postgres')]
```

Add fields to `Connection` (after `password = ...` line) and a `clean()` method:

```python
    kind     = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_SSH)
    db_name  = models.CharField(max_length=255, blank=True)
```

```python
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.kind == KIND_POSTGRES and not self.db_name:
            raise ValidationError('DB NAME jest wymagane dla połączeń typu Postgres.')
```

- [ ] **Step 4: Create the migration**

Create `services/web/apps/connections/migrations/0003_connection_kind_and_db_name.py`:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('connections', '0002_dry_run_and_checksum'),
    ]

    operations = [
        migrations.AddField(
            model_name='connection',
            name='kind',
            field=models.CharField(choices=[('ssh', 'SSH'), ('postgres', 'Postgres')], default='ssh', max_length=10),
        ),
        migrations.AddField(
            model_name='connection',
            name='db_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/web && pytest apps/connections/tests/ -v`
Expected: PASS — all connections tests green, including the 4 new ones

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/connections/models.py services/web/apps/connections/migrations/0003_connection_kind_and_db_name.py services/web/apps/connections/tests/test_models.py
git commit -m "feat(connections): add kind + db_name fields for Postgres connections"
```

---

### Task 2: `ConnectionForm` — kind-aware validation + form/list template

**Files:**
- Modify: `services/web/apps/connections/forms.py`
- Modify: `services/web/templates/connections/form.html`
- Modify: `services/web/templates/connections/list.html`
- Modify: `services/web/apps/connections/tests/test_views.py`

**Interfaces:**
- Consumes: `Connection.KIND_POSTGRES` (Task 1)
- Produces: `ConnectionForm` accepts `kind`/`db_name` in `Meta.fields`; `clean()` requires `password`+`db_name` when `kind='postgres'`, requires `password` or `ssh_key` otherwise.

- [ ] **Step 1: Write the failing tests**

Append to `services/web/apps/connections/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestConnectionCreatePostgresKind:
    def test_create_postgres_connection_requires_db_name(self, admin_client):
        response = admin_client.post(reverse('connections:create'), {
            'name': 'PG', 'kind': 'postgres', 'host': '10.0.0.5', 'port': 5432,
            'username': 'postgres', 'password': 'pass',
            'protocol': 'sftp', 'compress': False, 'encrypt': False,
            'strict_host_key_checking': True,
        })
        assert response.status_code == 200
        assert response.context['form'].errors

    def test_create_postgres_connection_success(self, admin_client):
        response = admin_client.post(reverse('connections:create'), {
            'name': 'PG', 'kind': 'postgres', 'host': '10.0.0.5', 'port': 5432,
            'username': 'postgres', 'password': 'pass', 'db_name': 'proddb',
            'protocol': 'sftp', 'compress': False, 'encrypt': False,
            'strict_host_key_checking': True,
        })
        assert response.status_code == 302
        conn = Connection.objects.get(name='PG')
        assert conn.kind == 'postgres'
        assert conn.db_name == 'proddb'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/web && pytest apps/connections/tests/test_views.py -v -k PostgresKind`
Expected: FAIL — form rejects unknown field `kind`/`db_name` (not in `Meta.fields` yet), first test fails because no error is raised, second because `Connection.objects.get(name='PG')` — `kind` stays default.

- [ ] **Step 3: Update the form**

In `services/web/apps/connections/forms.py`, replace the whole file:

```python
from django import forms
from .models import Connection, KIND_POSTGRES


class ConnectionForm(forms.ModelForm):
    class Meta:
        model = Connection
        fields = [
            'name', 'kind', 'host', 'port', 'username', 'password', 'db_name', 'ssh_key',
            'protocol', 'compress', 'encrypt', 'strict_host_key_checking',
            'known_host_key', 'dry_run_before_transfer', 'verify_checksum',
        ]
        labels = {
            'dry_run_before_transfer': 'Dry-run przed transferem (tylko rsync)',
            'verify_checksum':         'Weryfikuj integralność SHA-256 po transferze',
            'db_name':                 'DB NAME (tylko Postgres)',
        }
        widgets = {
            'password': forms.PasswordInput(render_value=True),
            'ssh_key': forms.Textarea(attrs={'rows': 6}),
            'known_host_key': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'hostname ssh-rsa AAAA... — kliknij [SCAN] aby pobrać automatycznie',
            }),
        }

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get('kind')
        if kind == KIND_POSTGRES:
            if not cleaned.get('password'):
                raise forms.ValidationError('Podaj hasło do bazy Postgres.')
            if not cleaned.get('db_name'):
                raise forms.ValidationError('Podaj nazwę bazy danych (DB NAME).')
        else:
            if not cleaned.get('password') and not cleaned.get('ssh_key'):
                raise forms.ValidationError('Podaj hasło lub klucz SSH.')
        return cleaned

    def clean_dry_run_before_transfer(self):
        value = self.cleaned_data.get('dry_run_before_transfer')
        protocol = self.cleaned_data.get('protocol')
        if value and protocol != 'rsync':
            raise forms.ValidationError('Dry-run jest dostępny tylko dla protokołu rsync.')
        return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/web && pytest apps/connections/tests/test_views.py -v -k PostgresKind`
Expected: PASS

- [ ] **Step 5: Update `form.html`** — add `kind`/`db_name` handling and JS toggle

Replace `services/web/templates/connections/form.html` with:

```html
{% extends "base.html" %}
{% block title %}{{ action }} CONNECTION{% endblock %}
{% block content %}
<div class="box" style="max-width:600px;">
  <span class="box-title">{{ action }} CONNECTION</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error">{% for e in form.non_field_errors %}> {{ e }}{% endfor %}</div>
    {% endif %}
    {% for field in form %}
    {% if field.name == 'db_name' %}
    <div class="field postgres-only-field">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      {% if field.errors %}
      <div style="color:var(--red);font-size:0.8rem;">{% for e in field.errors %}{{ e }}{% endfor %}</div>
      {% endif %}
    </div>
    {% elif field.name == 'ssh_key' or field.name == 'protocol' or field.name == 'compress' or field.name == 'strict_host_key_checking' %}
    <div class="field ssh-only-field">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      {% if field.errors %}
      <div style="color:var(--red);font-size:0.8rem;">{% for e in field.errors %}{{ e }}{% endfor %}</div>
      {% endif %}
    </div>
    {% elif field.name == 'known_host_key' %}
    <div class="field ssh-only-field" id="known-host-section" style="display:none">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      {% if conn %}
      <div style="margin-top:0.4rem;">
        <button type="button" class="btn btn-warn" id="scan-btn"
                onclick="scanHostKey({{ conn.pk }})">[ SCAN HOST KEY ]</button>
        <span id="scan-result" style="font-size:0.8rem; margin-left:0.5rem;"></span>
      </div>
      {% endif %}
      {% if field.errors %}
      <div style="color:var(--red);font-size:0.8rem;">{% for e in field.errors %}{{ e }}{% endfor %}</div>
      {% endif %}
    </div>
    {% elif field.name == 'dry_run_before_transfer' %}
    <div class="box-title ssh-only-field" style="margin-top:1.2rem;font-size:0.85rem;">[ OPCJE ZAAWANSOWANE ]</div>
    <div class="field ssh-only-field">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      <span style="font-size:0.75rem;color:var(--dim);">Sprawdza listę plików bez kopiowania. Transfer anulowany jeśli dry-run zakończy się błędem.</span>
      {% if field.errors %}
      <div style="color:var(--red);font-size:0.8rem;">{% for e in field.errors %}{{ e }}{% endfor %}</div>
      {% endif %}
    </div>
    {% elif field.name == 'verify_checksum' %}
    <div class="field">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      <span style="font-size:0.75rem;color:var(--dim);">Wymaga sha256sum na zdalnym hoście. Ignorowane gdy GPG włączone.</span>
      {% if field.errors %}
      <div style="color:var(--red);font-size:0.8rem;">{% for e in field.errors %}{{ e }}{% endfor %}</div>
      {% endif %}
    </div>
    {% else %}
    <div class="field">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      {% if field.errors %}
      <div style="color:var(--red);font-size:0.8rem;">{% for e in field.errors %}{{ e }}{% endfor %}</div>
      {% endif %}
    </div>
    {% endif %}
    {% endfor %}
    <div style="display:flex;gap:1rem;margin-top:1.5rem;">
      <button type="submit" class="btn">[ SAVE ]</button>
      <a href="{% url 'connections:list' %}" class="btn btn-danger">[ CANCEL ]</a>
    </div>
  </form>
</div>
<script>
  function toggleKnownHost() {
    var strict = document.getElementById('id_strict_host_key_checking');
    var section = document.getElementById('known-host-section');
    var kind = document.getElementById('id_kind');
    if (strict && section && kind && kind.value === 'ssh') {
      section.style.display = strict.checked ? 'block' : 'none';
    }
  }

  function toggleKind() {
    var kind = document.getElementById('id_kind');
    if (!kind) return;
    var sshFields = document.querySelectorAll('.ssh-only-field');
    var pgFields = document.querySelectorAll('.postgres-only-field');
    sshFields.forEach(function (el) { el.style.display = (kind.value === 'ssh') ? '' : 'none'; });
    pgFields.forEach(function (el) { el.style.display = (kind.value === 'postgres') ? '' : 'none'; });
    if (kind.value === 'ssh') {
      toggleKnownHost();
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var strict = document.getElementById('id_strict_host_key_checking');
    var kind = document.getElementById('id_kind');
    if (strict) {
      strict.addEventListener('change', toggleKnownHost);
    }
    if (kind) {
      kind.addEventListener('change', toggleKind);
      toggleKind();
    }
  });

  function scanHostKey(pk) {
    var btn = document.getElementById('scan-btn');
    var result = document.getElementById('scan-result');
    btn.disabled = true;
    result.textContent = 'SCANNING...';
    result.style.color = '';
    fetch('/connections/' + pk + '/scan-hostkey/')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.success) {
          document.getElementById('id_known_host_key').value = data.known_host_key;
          result.textContent = 'KEY SCANNED — VERIFY AND SAVE';
          result.style.color = 'var(--green)';
        } else {
          result.textContent = data.message;
          result.style.color = 'var(--red)';
        }
      })
      .catch(function () {
        result.textContent = 'SCAN ERROR';
        result.style.color = 'var(--red)';
      })
      .finally(function () { btn.disabled = false; });
  }
</script>
{% endblock %}
```

- [ ] **Step 6: Add KIND column to `list.html`**

In `services/web/templates/connections/list.html`, change the header row:

```html
      <tr>
        <th>NAME</th><th>KIND</th><th>HOST</th><th>PORT</th><th>PROTO</th>
        <th>COMPRESS</th><th>ENCRYPT</th><th>UTWORZYŁ</th><th class="col-actions">ACTIONS</th>
      </tr>
```

And the row cells (add right after `<td class="glow">{{ conn.name }}</td>`):

```html
        <td class="glow">{{ conn.name }}</td>
        <td>{{ conn.kind|upper }}</td>
```

- [ ] **Step 7: Manual template smoke check**

Run: `cd services/web && pytest apps/connections/tests/ -v`
Expected: PASS — templates render without `TemplateSyntaxError` (view tests above already render `form.html` and `list.html`)

- [ ] **Step 8: Commit**

```bash
git add services/web/apps/connections/forms.py services/web/templates/connections/form.html services/web/templates/connections/list.html services/web/apps/connections/tests/test_views.py
git commit -m "feat(connections): kind-aware form validation + UI toggle for Postgres connections"
```

---

### Task 3: `pg_tester.py` + `connection_test` view branch

**Files:**
- Create: `services/web/apps/connections/pg_tester.py`
- Modify: `services/web/apps/connections/views.py`
- Create: `services/web/apps/connections/tests/test_pg_tester.py`
- Modify: `services/web/apps/connections/tests/test_views.py`

**Interfaces:**
- Consumes: `Connection.kind`, `Connection.KIND_POSTGRES` (Task 1)
- Produces: `apps.connections.pg_tester.test_connection(connection) -> PgTestResult` (fields `success: bool`, `message: str` — same shape as `SSHTestResult`, reused by `connections/_test_result.html` unchanged)

- [ ] **Step 1: Write the failing tests**

Create `services/web/apps/connections/tests/test_pg_tester.py`:

```python
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from apps.connections.pg_tester import test_connection as _test_pg_connection


@pytest.mark.django_db
class TestPgTesterMessages:
    def test_success_message(self, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb', host='10.0.0.5', port=5432)
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        with patch('apps.connections.pg_tester.psycopg2.connect', return_value=mock_conn):
            result = _test_pg_connection(conn)
        assert result.success is True
        assert result.message == 'CONNECTION OK'

    def test_failure_message_on_operational_error(self, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb', host='10.0.0.5', port=5432)
        with patch('apps.connections.pg_tester.psycopg2.connect', side_effect=psycopg2.OperationalError('connection refused')):
            result = _test_pg_connection(conn)
        assert result.success is False
        assert 'CONNECTION FAILED' in result.message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/web && pytest apps/connections/tests/test_pg_tester.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.connections.pg_tester'`

- [ ] **Step 3: Implement `pg_tester.py`**

Create `services/web/apps/connections/pg_tester.py`:

```python
from dataclasses import dataclass

import psycopg2


@dataclass
class PgTestResult:
    success: bool
    message: str


def test_connection(connection) -> PgTestResult:
    try:
        conn = psycopg2.connect(
            host=connection.host,
            port=connection.port,
            user=connection.username,
            password=connection.password,
            dbname=connection.db_name,
            connect_timeout=10,
        )
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT 1')
                cur.fetchone()
        finally:
            conn.close()
        return PgTestResult(True, 'CONNECTION OK')
    except psycopg2.OperationalError as e:
        return PgTestResult(False, f'CONNECTION FAILED — {e}'.strip())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/web && pytest apps/connections/tests/test_pg_tester.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing view-branching tests**

Append to `services/web/apps/connections/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestConnectionTestBranchesByKind:
    def test_uses_pg_tester_for_postgres_kind(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        with patch('apps.connections.pg_tester.psycopg2.connect', return_value=mock_conn):
            response = auth_client.get(reverse('connections:test', args=[conn.pk]))
        assert response.status_code == 200
        assert b'CONNECTION OK' in response.content

    def test_uses_ssh_tester_for_ssh_kind(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user)
        mock_client = MagicMock()
        with patch('apps.connections.ssh_tester.paramiko.SSHClient', return_value=mock_client):
            response = auth_client.get(reverse('connections:test', args=[conn.pk]))
        assert response.status_code == 200
        assert b'CONNECTION OK' in response.content
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd services/web && pytest apps/connections/tests/test_views.py -v -k BranchesByKind`
Expected: FAIL on `test_uses_pg_tester_for_postgres_kind` — SSH tester is used for every connection today, so `mock_conn`/psycopg2 patch is never hit, and the real `ssh_tester` will error attempting an actual SSH connection.

- [ ] **Step 7: Wire the branch into `connection_test`**

In `services/web/apps/connections/views.py`, add the import near the other local imports:

```python
from .models import Connection, KIND_POSTGRES
from .pg_tester import test_connection as _test_pg_connection
```

(the existing `from .models import Connection` line — replace it with the one above, adding `KIND_POSTGRES`)

Replace `connection_test`:

```python
@require_role(ROLE_READONLY)
def connection_test(request, pk):
    conn = get_object_or_404(Connection, pk=pk)
    if conn.kind == KIND_POSTGRES:
        result = _test_pg_connection(conn)
    else:
        result = _test_connection(conn)
    return render(request, 'connections/_test_result.html', {'result': result})
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd services/web && pytest apps/connections/tests/ -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add services/web/apps/connections/pg_tester.py services/web/apps/connections/views.py services/web/apps/connections/tests/test_pg_tester.py services/web/apps/connections/tests/test_views.py
git commit -m "feat(connections): psycopg2-based TEST for Postgres-kind connections"
```

---

### Task 4: `pg_utils.list_tables` + introspection endpoint

**Files:**
- Create: `services/web/apps/connections/pg_utils.py`
- Modify: `services/web/apps/connections/views.py`
- Modify: `services/web/apps/connections/urls.py`
- Create: `services/web/templates/connections/_pg_tables_options.html`
- Create: `services/web/apps/connections/tests/test_pg_utils.py`
- Modify: `services/web/apps/connections/tests/test_views.py`

**Interfaces:**
- Produces: `apps.connections.pg_utils.list_tables(connection) -> list[str]`; endpoint `GET /connections/pg-tables/?source_connection=<pk>` → `connections:pg_tables`, returns an HTML `<select id="id_table_name" name="table_name">` fragment.

- [ ] **Step 1: Write the failing test for `list_tables`**

Create `services/web/apps/connections/tests/test_pg_utils.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from apps.connections.pg_utils import list_tables


@pytest.mark.django_db
class TestListTables:
    def test_returns_table_names_sorted(self, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('orders',), ('users',)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        with patch('apps.connections.pg_utils.psycopg2.connect', return_value=mock_conn):
            tables = list_tables(conn)
        assert tables == ['orders', 'users']
        mock_conn.close.assert_called_once()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/web && pytest apps/connections/tests/test_pg_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.connections.pg_utils'`

- [ ] **Step 3: Implement `pg_utils.py`**

Create `services/web/apps/connections/pg_utils.py`:

```python
import psycopg2


def list_tables(connection) -> list:
    conn = psycopg2.connect(
        host=connection.host,
        port=connection.port,
        user=connection.username,
        password=connection.password,
        dbname=connection.db_name,
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd services/web && pytest apps/connections/tests/test_pg_utils.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing endpoint tests**

Append to `services/web/apps/connections/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestConnectionPgTables:
    def test_returns_options_fragment(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        with patch('apps.connections.views._list_pg_tables', return_value=['users', 'orders']):
            response = auth_client.get(reverse('connections:pg_tables'), {'source_connection': conn.pk})
        assert response.status_code == 200
        assert b'<option value="users">users</option>' in response.content
        assert b'<option value="orders">orders</option>' in response.content

    def test_empty_when_no_connection_id(self, auth_client):
        response = auth_client.get(reverse('connections:pg_tables'))
        assert response.status_code == 200
        assert b'wybierz' in response.content.lower()
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd services/web && pytest apps/connections/tests/test_views.py -v -k PgTables`
Expected: FAIL — `NoReverseMatch: 'pg_tables' is not a registered namespace/URL`

- [ ] **Step 7: Add the view, URL, and template**

In `services/web/apps/connections/views.py`, add the import:

```python
from .pg_utils import list_tables as _list_pg_tables
```

Add the view (near `browse_directory`):

```python
@require_role(ROLE_READONLY)
def connection_pg_tables(request):
    conn_id = request.GET.get('source_connection')
    tables = []
    if conn_id:
        conn = Connection.objects.filter(pk=conn_id, kind=KIND_POSTGRES).first()
        if conn:
            tables = _list_pg_tables(conn)
    return render(request, 'connections/_pg_tables_options.html', {'tables': tables})
```

In `services/web/apps/connections/urls.py`, add before the `export/` line:

```python
    path('pg-tables/', views.connection_pg_tables, name='pg_tables'),
```

Create `services/web/templates/connections/_pg_tables_options.html`:

```html
<select id="id_table_name" name="table_name">
  {% if tables %}
  <option value="">— wybierz tabelę —</option>
  {% for t in tables %}
  <option value="{{ t }}">{{ t }}</option>
  {% endfor %}
  {% else %}
  <option value="">— wybierz najpierw SOURCE CONNECTION —</option>
  {% endif %}
</select>
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd services/web && pytest apps/connections/tests/ -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add services/web/apps/connections/pg_utils.py services/web/apps/connections/views.py services/web/apps/connections/urls.py services/web/templates/connections/_pg_tables_options.html services/web/apps/connections/tests/test_pg_utils.py services/web/apps/connections/tests/test_views.py
git commit -m "feat(connections): live table introspection endpoint for Postgres connections"
```

---

### Task 5: `PgTransferJob` + `PgTransferLog` models (new app `apps/db_transfers`)

**Files:**
- Create: `services/web/apps/db_transfers/__init__.py`
- Create: `services/web/apps/db_transfers/models.py`
- Create: `services/web/apps/db_transfers/admin.py`
- Create: `services/web/apps/db_transfers/migrations/__init__.py`
- Create: `services/web/apps/db_transfers/migrations/0001_initial.py`
- Create: `services/web/apps/db_transfers/tests/__init__.py`
- Create: `services/web/apps/db_transfers/tests/test_models.py`
- Modify: `services/web/config/settings/base.py`

**Interfaces:**
- Consumes: `connections.Connection` (Task 1)
- Produces: `apps.db_transfers.models.PgTransferJob` (fields: `owner`, `source_connection`, `dest_connection`, `table_name`, `verify_row_count`, `status`, `celery_task_id`, `created_at`, `started_at`, `finished_at`, `error_message`, `cancelled_by`; methods `mark_running(task_id)`, `mark_done()`, `mark_failed(message)`, `mark_cancelled(by)`); `STATUS_PENDING`/`STATUS_RUNNING`/`STATUS_DONE`/`STATUS_FAILED`/`STATUS_CANCELLED`; `apps.db_transfers.models.PgTransferLog` (fields: `job`, `timestamp`, `level`, `message`)

- [ ] **Step 1: Write the failing tests**

Create `services/web/apps/db_transfers/tests/__init__.py` (empty file).

Create `services/web/apps/db_transfers/tests/test_models.py`:

```python
import pytest
from django.core.exceptions import ValidationError

from apps.db_transfers.models import PgTransferJob


@pytest.mark.django_db
class TestPgTransferJob:
    def test_clean_rejects_same_source_and_dest_connection(self, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        job = PgTransferJob(owner=regular_user, source_connection=conn, dest_connection=conn)
        with pytest.raises(ValidationError):
            job.clean()

    def test_clean_allows_different_connections(self, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob(owner=regular_user, source_connection=src, dest_connection=dst)
        job.clean()  # should not raise

    def test_mark_done_sets_status_and_finished_at(self, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst)
        job.mark_done()
        assert job.status == 'done'
        assert job.finished_at is not None

    def test_mark_failed_sets_error_message(self, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst)
        job.mark_failed('AUTH FAILED')
        assert job.status == 'failed'
        assert job.error_message == 'AUTH FAILED'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/web && pytest apps/db_transfers/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.db_transfers'`

- [ ] **Step 3: Create the app package**

Create `services/web/apps/db_transfers/__init__.py` (empty file).
Create `services/web/apps/db_transfers/migrations/__init__.py` (empty file).

- [ ] **Step 4: Implement the models**

Create `services/web/apps/db_transfers/models.py`:

```python
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

STATUS_PENDING = 'pending'
STATUS_RUNNING = 'running'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'
STATUS_CANCELLED = 'cancelled'
STATUS_CHOICES = [
    (STATUS_PENDING, 'PENDING'),
    (STATUS_RUNNING, 'RUNNING'),
    (STATUS_DONE, 'DONE'),
    (STATUS_FAILED, 'FAILED'),
    (STATUS_CANCELLED, 'CANCELLED'),
]

LOG_INFO = 'info'
LOG_WARN = 'warn'
LOG_ERROR = 'error'
LOG_CHOICES = [(LOG_INFO, 'INFO'), (LOG_WARN, 'WARN'), (LOG_ERROR, 'ERROR')]


class PgTransferJob(models.Model):
    owner             = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pg_jobs'
    )
    source_connection = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='pg_source_jobs'
    )
    dest_connection   = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='pg_dest_jobs'
    )
    table_name        = models.CharField(max_length=255, blank=True)
    verify_row_count  = models.BooleanField(default=False)
    status            = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    celery_task_id    = models.CharField(max_length=255, null=True, blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)
    started_at        = models.DateTimeField(null=True, blank=True)
    finished_at       = models.DateTimeField(null=True, blank=True)
    error_message     = models.TextField(null=True, blank=True)
    cancelled_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cancelled_pg_jobs',
    )

    def clean(self):
        if self.source_connection_id and self.dest_connection_id and self.source_connection_id == self.dest_connection_id:
            raise ValidationError('Source and destination connection cannot be the same.')

    def mark_running(self, task_id: str) -> None:
        self.status = STATUS_RUNNING
        self.celery_task_id = task_id
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'celery_task_id', 'started_at'])

    def mark_done(self) -> None:
        self.status = STATUS_DONE
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'finished_at'])

    def mark_failed(self, message: str) -> None:
        self.status = STATUS_FAILED
        self.error_message = message
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'error_message', 'finished_at'])

    def mark_cancelled(self, by) -> None:
        self.status = STATUS_CANCELLED
        self.cancelled_by = by
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'cancelled_by', 'finished_at'])

    def __str__(self) -> str:
        scope = self.table_name or 'WHOLE DB'
        return f'PgJob #{self.pk} [{self.status}] {scope}'

    class Meta:
        ordering = ['-created_at']


class PgTransferLog(models.Model):
    job       = models.ForeignKey(PgTransferJob, on_delete=models.CASCADE, related_name='logs')
    timestamp = models.DateTimeField(auto_now_add=True)
    level     = models.CharField(max_length=5, choices=LOG_CHOICES, default=LOG_INFO)
    message   = models.TextField()

    class Meta:
        ordering = ['timestamp']
```

- [ ] **Step 5: Register the app + create the migration**

In `services/web/config/settings/base.py`, add `'apps.db_transfers',` to `INSTALLED_APPS` (after `'apps.organization',`).

Create `services/web/apps/db_transfers/migrations/0001_initial.py`:

```python
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('connections', '0003_connection_kind_and_db_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PgTransferJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('table_name', models.CharField(blank=True, max_length=255)),
                ('verify_row_count', models.BooleanField(default=False)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'PENDING'), ('running', 'RUNNING'), ('done', 'DONE'),
                        ('failed', 'FAILED'), ('cancelled', 'CANCELLED'),
                    ],
                    default='pending', max_length=10,
                )),
                ('celery_task_id', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pg_jobs', to=settings.AUTH_USER_MODEL)),
                ('source_connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pg_source_jobs', to='connections.connection')),
                ('dest_connection', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pg_dest_jobs', to='connections.connection')),
                ('cancelled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cancelled_pg_jobs', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='PgTransferLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('level', models.CharField(choices=[('info', 'INFO'), ('warn', 'WARN'), ('error', 'ERROR')], default='info', max_length=5)),
                ('message', models.TextField()),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='db_transfers.pgtransferjob')),
            ],
            options={'ordering': ['timestamp']},
        ),
    ]
```

- [ ] **Step 6: Add admin registration**

Create `services/web/apps/db_transfers/admin.py`:

```python
from django.contrib import admin
from .models import PgTransferJob, PgTransferLog


class PgTransferLogInline(admin.TabularInline):
    model = PgTransferLog
    readonly_fields = ['timestamp', 'level', 'message']
    extra = 0
    can_delete = False


@admin.register(PgTransferJob)
class PgTransferJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'source_connection', 'dest_connection', 'table_name', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['owner__username', 'table_name', 'source_connection__name', 'dest_connection__name']
    readonly_fields = ['created_at', 'started_at', 'finished_at', 'celery_task_id']
    inlines = [PgTransferLogInline]
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd services/web && pytest apps/db_transfers/tests/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add services/web/apps/db_transfers/ services/web/config/settings/base.py
git commit -m "feat(db_transfers): PgTransferJob/PgTransferLog models + admin"
```

---

### Task 6: Worker module `modules/postgres/` — command building + retry + Dockerfile

**Files:**
- Create: `services/worker/modules/postgres/__init__.py`
- Create: `services/worker/modules/postgres/config.py`
- Create: `services/worker/modules/postgres/handler.py`
- Create: `services/worker/tests/test_postgres_handler.py`
- Modify: `services/worker/Dockerfile`

**Interfaces:**
- Produces: `modules.postgres.handler.PgTransferHandler(params: dict)` where `params` has keys `source_host`, `source_port`, `source_username`, `source_password`, `source_db_name`, `dest_host`, `dest_port`, `dest_username`, `dest_password`, `dest_db_name`, `table_name` (`str | None`), `verify_row_count` (`bool`). Method `execute(log_callback: Callable[[str, str], None]) -> None`, raises `PgTransferError`. `PG_DUMP_MAX_RETRIES`, `PG_DUMP_RETRY_DELAY` from `modules.postgres.config`.

- [ ] **Step 1: Write the failing command-building tests**

Create `services/worker/tests/test_postgres_handler.py`:

```python
import pytest
from unittest.mock import patch, MagicMock

from modules.postgres.handler import PgTransferHandler, PgTransferError
from modules.postgres.config import PG_DUMP_MAX_RETRIES, PG_DUMP_RETRY_DELAY


class TestPgTransferHandler:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': '10.0.0.1', 'source_port': 5432, 'source_username': 'postgres',
            'source_password': 'srcpass', 'source_db_name': 'proddb',
            'dest_host': '10.0.0.2', 'dest_port': 5432, 'dest_username': 'postgres',
            'dest_password': 'dstpass', 'dest_db_name': 'testdb',
            'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_builds_whole_db_pg_dump_command(self):
        handler = PgTransferHandler(self._make_params())
        cmd = handler._build_pg_dump_cmd()
        assert cmd[0] == 'pg_dump'
        assert '-h' in cmd and '10.0.0.1' in cmd
        assert '--clean' in cmd and '--if-exists' in cmd and '--no-owner' in cmd and '--no-privileges' in cmd
        assert '--table' not in cmd
        assert cmd[-1] == 'proddb'

    def test_builds_single_table_pg_dump_command(self):
        handler = PgTransferHandler(self._make_params(table_name='users'))
        cmd = handler._build_pg_dump_cmd()
        assert '--table' in cmd
        assert cmd[cmd.index('--table') + 1] == 'users'

    def test_builds_psql_command(self):
        handler = PgTransferHandler(self._make_params())
        cmd = handler._build_psql_cmd()
        assert cmd[0] == 'psql'
        assert '10.0.0.2' in cmd
        assert 'testdb' in cmd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/worker && pytest tests/test_postgres_handler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.postgres'`

- [ ] **Step 3: Implement config + command building**

Create `services/worker/modules/postgres/__init__.py` (empty file).

Create `services/worker/modules/postgres/config.py`:

```python
PG_DUMP_BASE_FLAGS = ['--clean', '--if-exists', '--no-owner', '--no-privileges', '--verbose']
PG_DUMP_MAX_RETRIES = 3
PG_DUMP_RETRY_DELAY = 5
```

Create `services/worker/modules/postgres/handler.py`:

```python
import os
import subprocess  # nosec B404
import time
from typing import Callable

from .config import PG_DUMP_BASE_FLAGS, PG_DUMP_MAX_RETRIES, PG_DUMP_RETRY_DELAY


class PgTransferError(Exception):
    pass


class PgTransferHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_pg_dump_cmd(self) -> list:
        p = self.params
        cmd = ['pg_dump', '-h', p['source_host'], '-p', str(p['source_port']), '-U', p['source_username']]
        cmd += list(PG_DUMP_BASE_FLAGS)
        if p.get('table_name'):
            cmd += ['--table', p['table_name']]
        cmd.append(p['source_db_name'])
        return cmd

    def _build_psql_cmd(self) -> list:
        p = self.params
        return [
            'psql', '-h', p['dest_host'], '-p', str(p['dest_port']), '-U', p['dest_username'],
            '-v', 'ON_ERROR_STOP=1', p['dest_db_name'],
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/worker && pytest tests/test_postgres_handler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit command-building**

```bash
git add services/worker/modules/postgres/__init__.py services/worker/modules/postgres/config.py services/worker/modules/postgres/handler.py services/worker/tests/test_postgres_handler.py
git commit -m "feat(worker): pg_dump/psql command building for Postgres transfer module"
```

- [ ] **Step 6: Write the failing execute/retry/PGPASSWORD tests**

Append to `services/worker/tests/test_postgres_handler.py`, **inside** the existing `TestPgTransferHandler` class (same class, not a new one — it already has `_make_params`):

```python
    def _mock_proc(self, stderr_lines, exit_code):
        proc = MagicMock()
        proc.stderr = iter(stderr_lines)
        proc.wait.return_value = exit_code
        return proc

    def test_successful_transfer_returns_without_error(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler = PgTransferHandler(self._make_params())
            handler.execute(log_callback=lambda lvl, msg: None)  # should not raise

    def test_pgpassword_passed_via_env_not_argv(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler = PgTransferHandler(self._make_params())
            handler.execute(log_callback=lambda lvl, msg: None)

            dump_call = MockPopen.call_args_list[0]
            psql_call = MockPopen.call_args_list[1]
            dump_argv = dump_call.args[0]
            psql_argv = psql_call.args[0]
            assert not any('srcpass' in str(a) for a in dump_argv)
            assert not any('dstpass' in str(a) for a in psql_argv)
            assert dump_call.kwargs['env']['PGPASSWORD'] == 'srcpass'
            assert psql_call.kwargs['env']['PGPASSWORD'] == 'dstpass'

    def test_auth_failure_raises_without_retry(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.time.sleep') as mock_sleep:
            dump_proc = self._mock_proc(['pg_dump: error: connection to server failed'], 1)
            psql_proc = self._mock_proc(['psql: error: password authentication failed for user "postgres"'], 1)
            MockPopen.side_effect = [dump_proc, psql_proc]
            handler = PgTransferHandler(self._make_params())
            with pytest.raises(PgTransferError, match='AUTH FAILED'):
                handler.execute(log_callback=lambda lvl, msg: None)
            mock_sleep.assert_not_called()

    def test_transient_failure_retries_then_succeeds(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.time.sleep'):
            fail_dump = self._mock_proc(['pg_dump: error: server closed the connection unexpectedly'], 1)
            fail_psql = self._mock_proc([], 1)
            ok_dump = self._mock_proc([], 0)
            ok_psql = self._mock_proc([], 0)
            MockPopen.side_effect = [fail_dump, fail_psql, ok_dump, ok_psql]
            handler = PgTransferHandler(self._make_params())
            handler.execute(log_callback=lambda lvl, msg: None)  # should not raise
            assert MockPopen.call_count == 4

    def test_exhausted_retries_raises(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.time.sleep'):
            MockPopen.side_effect = [
                self._mock_proc(['server closed the connection unexpectedly'], 1),
                self._mock_proc([], 1),
            ] * PG_DUMP_MAX_RETRIES
            handler = PgTransferHandler(self._make_params())
            with pytest.raises(PgTransferError, match='TRANSFER FAILED'):
                handler.execute(log_callback=lambda lvl, msg: None)
            assert MockPopen.call_count == PG_DUMP_MAX_RETRIES * 2
```

- [ ] **Step 7: Run to verify it fails**

Run: `cd services/worker && pytest tests/test_postgres_handler.py -v -k "execute or transfer or retry or pgpassword"`
Expected: FAIL — `AttributeError: 'PgTransferHandler' object has no attribute 'execute'`

- [ ] **Step 8: Implement `execute`, `_run_pipe`, `_check_output`**

In `services/worker/modules/postgres/handler.py`, append to the `PgTransferHandler` class:

```python
    def _run_pipe(self, log_callback: Callable[[str, str], None]) -> tuple:
        dump_cmd = self._build_pg_dump_cmd()
        psql_cmd = self._build_psql_cmd()
        dump_env = {**os.environ, 'PGPASSWORD': self.params['source_password']}
        psql_env = {**os.environ, 'PGPASSWORD': self.params['dest_password']}

        dump_proc = subprocess.Popen(  # nosec B603 — cmd built from validated connection params, no shell=True
            dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dump_env,
        )
        psql_proc = subprocess.Popen(  # nosec B603
            psql_cmd, stdin=dump_proc.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=psql_env,
        )
        dump_proc.stdout.close()

        output_lines = []
        for line in psql_proc.stderr:
            line = line.rstrip()
            if line:
                output_lines.append(line)
                log_callback('info', line)
        for line in dump_proc.stderr:
            line = line.rstrip()
            if line:
                output_lines.append(line)
                log_callback('info', line)

        psql_exit = psql_proc.wait()
        dump_exit = dump_proc.wait()
        return dump_exit, psql_exit, '\n'.join(output_lines)

    def _check_output(self, output: str) -> None:
        lowered = output.lower()
        if 'authentication failed' in lowered:
            raise PgTransferError('AUTH FAILED — sprawdź dane uwierzytelniania')
        if self.params.get('table_name') and 'does not exist' in lowered:
            raise PgTransferError(f'TABLE NOT FOUND: {self.params["table_name"]}')
        if 'could not connect' in lowered or 'connection refused' in lowered:
            raise PgTransferError(
                f'CONNECTION FAILED — sprawdź host/port ({self.params["source_host"]} / {self.params["dest_host"]})'
            )

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        last_dump_exit = last_psql_exit = None
        for attempt in range(1, PG_DUMP_MAX_RETRIES + 1):
            log_callback('info', f'Starting pg_dump|psql (attempt {attempt})')
            last_dump_exit, last_psql_exit, output = self._run_pipe(log_callback)
            self._check_output(output)
            if last_dump_exit == 0 and last_psql_exit == 0:
                log_callback('info', 'Transfer complete')
                return
            if attempt < PG_DUMP_MAX_RETRIES:
                log_callback('warn', f'pg_dump/psql failed (dump={last_dump_exit}, psql={last_psql_exit}), retrying in {PG_DUMP_RETRY_DELAY}s...')
                time.sleep(PG_DUMP_RETRY_DELAY)

        raise PgTransferError(
            f'TRANSFER FAILED — pg_dump/psql failed after {PG_DUMP_MAX_RETRIES} attempts '
            f'(pg_dump exit={last_dump_exit}, psql exit={last_psql_exit})'
        )
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd services/worker && pytest tests/test_postgres_handler.py -v`
Expected: PASS (all tests)

- [ ] **Step 10: Add `postgresql-client` to the worker image**

In `services/worker/Dockerfile`, change:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    rsync openssh-client libpq-dev gcc gnupg \
    && rm -rf /var/lib/apt/lists/*
```

to:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    rsync openssh-client libpq-dev gcc gnupg postgresql-client \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 11: Commit**

```bash
git add services/worker/modules/postgres/handler.py services/worker/tests/test_postgres_handler.py services/worker/Dockerfile
git commit -m "feat(worker): pg_dump|psql execute with retry + error detection, add postgresql-client to image"
```

---

### Task 7: Worker `verify_row_count` — COUNT(*) comparison

**Files:**
- Modify: `services/worker/modules/postgres/handler.py`
- Modify: `services/worker/tests/test_postgres_handler.py`

**Interfaces:**
- Consumes: `PgTransferHandler` (Task 6)
- Produces: `PgTransferHandler._verify_row_counts(log_callback)` — logs `info` "ROW COUNT OK" per matching table, `warn` "ROW COUNT MISMATCH" per mismatching table; called from `execute()` only when `params['verify_row_count']` is true and the transfer succeeded.

- [ ] **Step 1: Write the failing tests**

Append to `services/worker/tests/test_postgres_handler.py`, **inside** the existing `TestPgTransferHandler` class (reuses `_make_params` and `_mock_proc` already defined there):

```python
    def test_verify_row_count_logs_ok_on_match(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.psycopg2.connect') as mock_connect:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]

            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (5,)
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
            mock_connect.return_value = mock_conn

            logs = []
            handler = PgTransferHandler(self._make_params(table_name='users', verify_row_count=True))
            handler.execute(log_callback=lambda lvl, msg: logs.append((lvl, msg)))

            assert any(lvl == 'info' and 'ROW COUNT OK' in msg for lvl, msg in logs)

    def test_verify_row_count_logs_warning_on_mismatch(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.psycopg2.connect') as mock_connect:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]

            src_cursor = MagicMock()
            src_cursor.fetchone.return_value = (10,)
            dst_cursor = MagicMock()
            dst_cursor.fetchone.return_value = (7,)
            src_conn = MagicMock()
            src_conn.cursor.return_value.__enter__.return_value = src_cursor
            dst_conn = MagicMock()
            dst_conn.cursor.return_value.__enter__.return_value = dst_cursor
            mock_connect.side_effect = [src_conn, dst_conn]

            logs = []
            handler = PgTransferHandler(self._make_params(table_name='users', verify_row_count=True))
            handler.execute(log_callback=lambda lvl, msg: logs.append((lvl, msg)))

            assert any(lvl == 'warn' and 'MISMATCH' in msg for lvl, msg in logs)

    def test_verify_row_count_skipped_when_disabled(self):
        with patch('modules.postgres.handler.subprocess.Popen') as MockPopen, \
             patch('modules.postgres.handler.psycopg2.connect') as mock_connect:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler = PgTransferHandler(self._make_params(verify_row_count=False))
            handler.execute(log_callback=lambda lvl, msg: None)
            mock_connect.assert_not_called()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/worker && pytest tests/test_postgres_handler.py -v -k verify_row_count`
Expected: FAIL — `test_verify_row_count_skipped_when_disabled` passes trivially (no verify code exists yet), but `test_verify_row_count_logs_ok_on_match`/`_mismatch` FAIL (no "ROW COUNT" log lines produced)

- [ ] **Step 3: Implement `_verify_row_counts` and wire it into `execute`**

In `services/worker/modules/postgres/handler.py`, add the import at the top:

```python
import psycopg2
```

Add the method to `PgTransferHandler`:

```python
    def _verify_row_counts(self, log_callback: Callable[[str, str], None]) -> None:
        p = self.params
        src_conn = psycopg2.connect(host=p['source_host'], port=p['source_port'], user=p['source_username'],
                                     password=p['source_password'], dbname=p['source_db_name'])
        dst_conn = psycopg2.connect(host=p['dest_host'], port=p['dest_port'], user=p['dest_username'],
                                     password=p['dest_password'], dbname=p['dest_db_name'])
        try:
            if p.get('table_name'):
                tables = [p['table_name']]
            else:
                with src_conn.cursor() as cur:
                    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                    tables = [row[0] for row in cur.fetchall()]
            for table in tables:
                with src_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                    src_count = cur.fetchone()[0]
                with dst_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                    dst_count = cur.fetchone()[0]
                if src_count != dst_count:
                    log_callback('warn', f'ROW COUNT MISMATCH w "{table}": source={src_count} dest={dst_count}')
                else:
                    log_callback('info', f'ROW COUNT OK w "{table}": {src_count}')
        finally:
            src_conn.close()
            dst_conn.close()
```

In the same file, replace the success branch inside `execute`:

```python
            if last_dump_exit == 0 and last_psql_exit == 0:
                log_callback('info', 'Transfer complete')
                return
```

with:

```python
            if last_dump_exit == 0 and last_psql_exit == 0:
                log_callback('info', 'Transfer complete')
                if self.params.get('verify_row_count'):
                    self._verify_row_counts(log_callback)
                return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/worker && pytest tests/test_postgres_handler.py -v`
Expected: PASS (all tests, including Task 6's)

- [ ] **Step 5: Commit**

```bash
git add services/worker/modules/postgres/handler.py services/worker/tests/test_postgres_handler.py
git commit -m "feat(worker): verify_row_count COUNT(*) comparison after successful transfer"
```

---

### Task 8: Worker `tasks.py` wiring — `execute_pg_transfer`

**Files:**
- Modify: `services/worker/tasks.py`
- Modify: `services/worker/tests/test_tasks.py`

**Interfaces:**
- Consumes: `PgTransferJob`/`PgTransferLog` (Task 5), `PgTransferHandler`/`PgTransferError` (Tasks 6-7)
- Produces: Celery task `db_transfers.execute` (function `execute_pg_transfer(self, job_id: int)`), dispatched via `current_app.send_task('db_transfers.execute', kwargs={'job_id': job.pk})`

- [ ] **Step 1: Write the failing tests**

Append to `services/worker/tests/test_tasks.py`:

```python
class TestExecutePgTransferTask:
    def test_dispatches_to_postgres_handler_and_marks_done(self):
        with patch('tasks.PgTransferHandler') as MockHandler, \
             patch('tasks.PgTransferJob') as MockJob, \
             patch('tasks.PgTransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            mock_job.pk = 1
            mock_job.table_name = ''
            mock_job.source_connection.host = '10.0.0.1'
            mock_job.dest_connection.host = '10.0.0.2'
            MockHandler.return_value.execute.return_value = None
            from tasks import execute_pg_transfer
            execute_pg_transfer(job_id=1)
            MockHandler.assert_called_once()
            MockHandler.return_value.execute.assert_called_once()
            mock_job.mark_done.assert_called_once()

    def test_marks_job_failed_on_pg_transfer_error(self):
        with patch('tasks.PgTransferHandler') as MockHandler, \
             patch('tasks.PgTransferJob') as MockJob, \
             patch('tasks.PgTransferLog') as _:
            mock_job = MagicMock()
            MockJob.objects.select_related.return_value.get.return_value = mock_job
            mock_job.pk = 1
            mock_job.table_name = ''
            from modules.postgres.handler import PgTransferError
            MockHandler.return_value.execute.side_effect = PgTransferError('AUTH FAILED')
            from tasks import execute_pg_transfer
            execute_pg_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('AUTH FAILED')

    def test_job_not_found_returns_without_error(self):
        with patch('tasks.PgTransferJob') as MockJob, \
             patch('tasks.PgTransferLog') as _:
            MockJob.DoesNotExist = Exception
            MockJob.objects.select_related.return_value.get.side_effect = MockJob.DoesNotExist
            from tasks import execute_pg_transfer
            execute_pg_transfer(job_id=999)  # should not raise
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/worker && pytest tests/test_tasks.py -v -k ExecutePgTransfer`
Expected: FAIL — `ImportError: cannot import name 'execute_pg_transfer' from 'tasks'`

- [ ] **Step 3: Wire the task into `tasks.py`**

In `services/worker/tasks.py`, add imports near the other model/module imports:

```python
from apps.db_transfers.models import PgTransferJob, PgTransferLog  # noqa: E402
from modules.postgres.handler import PgTransferHandler, PgTransferError  # noqa: E402
```

Add near the bottom of the file (after `dry_run_preview`):

```python
def _build_pg_params(job) -> dict:
    return {
        'source_host': job.source_connection.host,
        'source_port': job.source_connection.port,
        'source_username': job.source_connection.username,
        'source_password': job.source_connection.password,
        'source_db_name': job.source_connection.db_name,
        'dest_host': job.dest_connection.host,
        'dest_port': job.dest_connection.port,
        'dest_username': job.dest_connection.username,
        'dest_password': job.dest_connection.password,
        'dest_db_name': job.dest_connection.db_name,
        'table_name': job.table_name or None,
        'verify_row_count': job.verify_row_count,
    }


@app.task(bind=True, name='db_transfers.execute')
def execute_pg_transfer(self, job_id: int):
    try:
        job = PgTransferJob.objects.select_related('source_connection', 'dest_connection').get(pk=job_id)
    except PgTransferJob.DoesNotExist:
        logger.error(f'PgTransferJob {job_id} not found — task aborted')
        return

    job.mark_running(self.request.id)

    def log_callback(level: str, message: str):
        PgTransferLog.objects.create(job=job, level=level, message=message)

    try:
        params = _build_pg_params(job)
        PgTransferHandler(params).execute(log_callback=log_callback)
        job.mark_done()
    except PgTransferError as e:
        job.mark_failed(str(e))
        log_callback('error', str(e))
        logger.error(f'PgTransferJob {job.pk} failed: {e}')
    except Exception as e:
        job.mark_failed(f'UNEXPECTED ERROR — {e}')
        log_callback('error', f'UNEXPECTED ERROR — {e}')
        logger.error(f'PgTransferJob {job.pk} unexpected error: {e}')
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/worker && pytest tests/test_tasks.py -v -k ExecutePgTransfer`
Expected: PASS

- [ ] **Step 5: Run the full worker suite**

Run: `cd services/worker && pytest -v`
Expected: PASS — all existing + new tests green

- [ ] **Step 6: Commit**

```bash
git add services/worker/tasks.py services/worker/tests/test_tasks.py
git commit -m "feat(worker): wire db_transfers.execute Celery task"
```

---

### Task 9: Web — `PgTransferForm` + views + urls + templates + navbar

**Files:**
- Create: `services/web/apps/db_transfers/forms.py`
- Create: `services/web/apps/db_transfers/views.py`
- Create: `services/web/apps/db_transfers/urls.py`
- Create: `services/web/templates/db_transfers/create.html`
- Create: `services/web/templates/db_transfers/detail.html`
- Create: `services/web/templates/db_transfers/log_fragment.html`
- Create: `services/web/templates/db_transfers/list.html`
- Modify: `services/web/config/urls.py`
- Modify: `services/web/templates/base.html`
- Create: `services/web/apps/db_transfers/tests/test_views.py`

**Interfaces:**
- Consumes: `PgTransferJob` (Task 5), `Connection`/`KIND_POSTGRES` (Task 1), Celery task name `db_transfers.execute` (Task 8)
- Produces: URLs `db_transfers:list`, `db_transfers:create`, `db_transfers:detail`, `db_transfers:log_fragment`, `db_transfers:stop`

- [ ] **Step 1: Write the failing view tests**

Create `services/web/apps/db_transfers/tests/test_views.py`:

```python
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.db_transfers.models import PgTransferJob


@pytest.mark.django_db
class TestDbTransferCreate:
    def test_requires_login(self, client):
        response = client.get(reverse('db_transfers:create'))
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_readonly_cannot_create(self, readonly_client):
        response = readonly_client.get(reverse('db_transfers:create'))
        assert response.status_code == 403

    def test_create_whole_db_transfer_dispatches_task(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        with patch('apps.db_transfers.views.current_app') as mock_app:
            mock_app.send_task.return_value.id = 'task-123'
            response = auth_client.post(reverse('db_transfers:create'), {
                'source_connection': src.pk, 'dest_connection': dst.pk,
                'scope': 'whole_db', 'table_name': '', 'verify_row_count': False,
            })
        assert response.status_code == 302
        job = PgTransferJob.objects.get()
        assert job.table_name == ''
        assert job.owner == regular_user

    def test_table_scope_requires_table_name(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        response = auth_client.post(reverse('db_transfers:create'), {
            'source_connection': src.pk, 'dest_connection': dst.pk,
            'scope': 'table', 'table_name': '', 'verify_row_count': False,
        })
        assert response.status_code == 200
        assert response.context['form'].errors

    def test_rejects_same_source_and_dest(self, auth_client, regular_user, make_connection):
        conn = make_connection(regular_user, kind='postgres', db_name='proddb')
        response = auth_client.post(reverse('db_transfers:create'), {
            'source_connection': conn.pk, 'dest_connection': conn.pk,
            'scope': 'whole_db', 'table_name': '', 'verify_row_count': False,
        })
        assert response.status_code == 200
        assert response.context['form'].errors


@pytest.mark.django_db
class TestDbTransferStop:
    def test_operator_can_stop_running_job(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        job = PgTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst, status='running')
        with patch('apps.db_transfers.views.current_app'):
            response = auth_client.post(reverse('db_transfers:stop', args=[job.pk]))
        assert response.status_code == 302
        job.refresh_from_db()
        assert job.status == 'cancelled'


@pytest.mark.django_db
class TestDbTransferList:
    def test_shows_jobs(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, kind='postgres', db_name='proddb', name='src')
        dst = make_connection(regular_user, kind='postgres', db_name='testdb', name='dst')
        PgTransferJob.objects.create(owner=regular_user, source_connection=src, dest_connection=dst)
        response = auth_client.get(reverse('db_transfers:list'))
        assert response.status_code == 200
        assert len(response.context['jobs']) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd services/web && pytest apps/db_transfers/tests/test_views.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.db_transfers.forms'` (and `NoReverseMatch` once forms import succeeds)

- [ ] **Step 3: Implement the form**

Create `services/web/apps/db_transfers/forms.py`:

```python
from django import forms
from apps.connections.models import Connection, KIND_POSTGRES
from .models import PgTransferJob


class PgTransferForm(forms.ModelForm):
    SCOPE_WHOLE_DB = 'whole_db'
    SCOPE_TABLE = 'table'
    SCOPE_CHOICES = [(SCOPE_WHOLE_DB, 'CAŁA BAZA'), (SCOPE_TABLE, 'POJEDYNCZA TABELA')]

    scope = forms.ChoiceField(choices=SCOPE_CHOICES, widget=forms.RadioSelect, initial=SCOPE_WHOLE_DB)

    class Meta:
        model = PgTransferJob
        fields = ['source_connection', 'table_name', 'dest_connection', 'verify_row_count']
        labels = {'verify_row_count': 'Weryfikuj liczbę wierszy po transferze (COUNT)'}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Connection.objects.filter(kind=KIND_POSTGRES)
        self.fields['source_connection'].queryset = qs
        self.fields['dest_connection'].queryset = qs

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get('scope')
        table_name = (cleaned.get('table_name') or '').strip()
        if scope == self.SCOPE_TABLE and not table_name:
            raise forms.ValidationError('Wybierz tabelę dla trybu POJEDYNCZA TABELA.')
        if scope == self.SCOPE_WHOLE_DB:
            cleaned['table_name'] = ''
        return cleaned
```

- [ ] **Step 4: Implement views + urls**

Create `services/web/apps/db_transfers/views.py`:

```python
from celery import current_app
from django.contrib import messages
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_OPERATOR, ROLE_READONLY
from .models import PgTransferJob, STATUS_RUNNING, STATUS_PENDING
from .forms import PgTransferForm


@require_role(ROLE_READONLY)
def db_transfer_list(request):
    jobs = PgTransferJob.objects.all().select_related('source_connection', 'dest_connection')
    return render(request, 'db_transfers/list.html', {'jobs': jobs})


@require_role(ROLE_OPERATOR)
def db_transfer_create(request):
    form = PgTransferForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            job = form.save(commit=False)
            job.owner = request.user
            job.save()

            def _dispatch():
                result = current_app.send_task('db_transfers.execute', kwargs={'job_id': job.pk})
                PgTransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)
            transaction.on_commit(_dispatch)
        return redirect('db_transfers:detail', pk=job.pk)
    return render(request, 'db_transfers/create.html', {'form': form})


@require_role(ROLE_READONLY)
def db_transfer_detail(request, pk):
    job = get_object_or_404(
        PgTransferJob.objects.select_related('source_connection', 'dest_connection'), pk=pk
    )
    return render(request, 'db_transfers/detail.html', {'job': job})


@require_role(ROLE_READONLY)
def log_fragment(request, pk):
    job = get_object_or_404(PgTransferJob, pk=pk)
    logs = job.logs.all()
    still_running = job.status == STATUS_RUNNING
    return render(request, 'db_transfers/log_fragment.html', {
        'job': job, 'logs': logs, 'still_running': still_running,
    })


@require_role(ROLE_OPERATOR)
@require_POST
def db_transfer_stop(request, pk):
    with transaction.atomic():
        job = get_object_or_404(PgTransferJob.objects.select_for_update(), pk=pk)
        if job.status not in (STATUS_PENDING, STATUS_RUNNING):
            messages.error(request, 'Transfer nie jest aktywny.')
            return redirect('db_transfers:detail', pk=job.pk)
        if job.celery_task_id:
            current_app.control.revoke(job.celery_task_id, terminate=True, signal='SIGTERM')
        job.mark_cancelled(by=request.user)
    messages.success(request, 'Transfer zatrzymany.')
    return redirect('db_transfers:detail', pk=job.pk)
```

Create `services/web/apps/db_transfers/urls.py`:

```python
from django.urls import path
from . import views

app_name = 'db_transfers'

urlpatterns = [
    path('', views.db_transfer_list, name='list'),
    path('new/', views.db_transfer_create, name='create'),
    path('<int:pk>/', views.db_transfer_detail, name='detail'),
    path('<int:pk>/logs/', views.log_fragment, name='log_fragment'),
    path('<int:pk>/stop/', views.db_transfer_stop, name='stop'),
]
```

In `services/web/config/urls.py`, add before the final `path('', ...)`:

```python
    path('db-transfers/', include('apps.db_transfers.urls')),
```

- [ ] **Step 5: Create the templates**

Create `services/web/templates/db_transfers/log_fragment.html`:

```html
{% for log in logs %}
<div class="log-line log-{{ log.level }}">
  [{{ log.timestamp|date:"H:i:s" }}] {{ log.message }}
</div>
{% endfor %}
{% if still_running %}
<div class="log-line log-info" style="animation: pulse 1s infinite;">&#9607; RUNNING...</div>
{% endif %}
```

Create `services/web/templates/db_transfers/list.html`:

```html
{% extends "base.html" %}
{% block title %}DB TRANSFERS — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">DB TRANSFERS</span>
  <div class="toolbar">
    {% if user.can_operate %}
    <a href="{% url 'db_transfers:create' %}" class="btn">[ + NEW DB TRANSFER ]</a>
    {% endif %}
  </div>
  {% if jobs %}
  <table>
    <thead>
      <tr>
        <th>#</th><th>SOURCE</th><th>DEST</th><th>SCOPE</th>
        <th>STATUS</th><th>STARTED</th><th>FINISHED</th><th>ACTIONS</th>
      </tr>
    </thead>
    <tbody>
      {% for job in jobs %}
      <tr>
        <td>{{ job.pk }}</td>
        <td>{{ job.source_connection.name }}</td>
        <td>{{ job.dest_connection.name }}</td>
        <td>{% if job.table_name %}{{ job.table_name }}{% else %}CAŁA BAZA{% endif %}</td>
        <td><span class="status status-{{ job.status }}">{{ job.status|upper }}</span></td>
        <td>{{ job.started_at|date:"Y-m-d H:i"|default:"—" }}</td>
        <td>{{ job.finished_at|date:"Y-m-d H:i"|default:"—" }}</td>
        <td><a href="{% url 'db_transfers:detail' job.pk %}" class="btn">[VIEW]</a></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color:#555;">NO DB TRANSFERS YET</p>
  {% endif %}
</div>
{% endblock %}
```

Create `services/web/templates/db_transfers/detail.html`:

```html
{% extends "base.html" %}
{% block title %}DB TRANSFER #{{ job.pk }} — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">DB TRANSFER LOG — #{{ job.pk }}</span>
  <div style="margin-bottom:0.5rem;">
    STATUS: <span class="status status-{{ job.status }}">{{ job.status|upper }}</span>
    {% if job.status == 'running' or job.status == 'pending' %}
    {% if user.can_operate %}
    <form method="post" action="{% url 'db_transfers:stop' job.pk %}" style="display:inline"
      onsubmit="return confirm('Zatrzymać transfer #{{ job.pk }}?')">
      {% csrf_token %}
      <button type="submit" class="btn btn-small btn-danger">[ STOP ]</button>
    </form>
    {% endif %}
    {% endif %}
  </div>
  <div style="margin-bottom:0.5rem;font-size:0.85rem;">
    SOURCE: <span class="glow">{{ job.source_connection.name }}</span> ({{ job.source_connection.db_name }})<br>
    DEST: <span class="glow">{{ job.dest_connection.name }}</span> ({{ job.dest_connection.db_name }})<br>
    SCOPE: {% if job.table_name %}TABLE — {{ job.table_name }}{% else %}CAŁA BAZA{% endif %}
  </div>
  <div
    id="log-output"
    class="log-terminal"
    {% if job.status == 'running' or job.status == 'pending' %}
      hx-get="{% url 'db_transfers:log_fragment' job.pk %}"
      hx-trigger="every 2s"
      hx-swap="innerHTML"
    {% endif %}
  >
    {% include "db_transfers/log_fragment.html" with logs=job.logs.all %}
  </div>
</div>
{% endblock %}
```

Create `services/web/templates/db_transfers/create.html`:

```html
{% extends "base.html" %}
{% block title %}NEW DB TRANSFER — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="box" style="max-width:600px;">
  <span class="box-title">NEW DB TRANSFER</span>
  <form method="post" id="pg-transfer-form">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error" style="margin-bottom:1rem;">
      {% for error in form.non_field_errors %}&gt; {{ error }}<br>{% endfor %}
    </div>
    {% endif %}
    {% for field in form %}
    {% if field.name == 'table_name' %}
    <div class="field">
      <label>{{ field.label|upper }}:</label>
      <select id="id_table_name" name="table_name">
        <option value="">— wybierz najpierw SOURCE CONNECTION —</option>
      </select>
      {% if field.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ field.errors }}</div>{% endif %}
    </div>
    {% else %}
    <div class="field">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      {% if field.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ field.errors }}</div>{% endif %}
    </div>
    {% endif %}
    {% endfor %}
    <button type="submit" class="btn" id="execute-btn">[ EXECUTE TRANSFER ]</button>
  </form>
</div>
<script>
(function () {
  var sourceSel = document.getElementById('id_source_connection');
  var tableField = document.getElementById('id_table_name');

  function loadTables() {
    if (!sourceSel.value) return;
    fetch('{% url "connections:pg_tables" %}?source_connection=' + encodeURIComponent(sourceSel.value))
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var wrapper = document.createElement('div');
        wrapper.innerHTML = html.trim();
        var newSelect = wrapper.firstChild;
        tableField.parentNode.replaceChild(newSelect, tableField);
        tableField = newSelect;
      });
  }
  if (sourceSel) {
    sourceSel.addEventListener('change', loadTables);
  }

  var form = document.getElementById('pg-transfer-form');
  form.addEventListener('submit', function (e) {
    var destSel = document.getElementById('id_dest_connection');
    var scopeInput = document.querySelector('input[name="scope"]:checked');
    var sourceName = sourceSel.options[sourceSel.selectedIndex] ? sourceSel.options[sourceSel.selectedIndex].text : '';
    var destName = destSel.options[destSel.selectedIndex] ? destSel.options[destSel.selectedIndex].text : '';
    var msg;
    if (scopeInput && scopeInput.value === 'table') {
      var tableName = tableField ? tableField.value : '';
      msg = 'Czy na pewno? Nadpisze tabelę "' + tableName + '" w "' + destName + '" danymi z "' + sourceName + '".';
    } else {
      msg = 'Czy na pewno? Nadpisze WSZYSTKIE tabele w bazie docelowej ("' + destName + '") danymi z "' + sourceName + '".';
    }
    if (!confirm(msg)) {
      e.preventDefault();
    }
  });
})();
</script>
{% endblock %}
```

- [ ] **Step 6: Add navbar link**

In `services/web/templates/base.html`, add after the SCHEDULER link:

```html
    <a href="{% url 'db_transfers:list' %}" class="{% if request.resolver_match.app_name == 'db_transfers' %}active{% endif %}">DB TRANSFERS</a>
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd services/web && pytest apps/db_transfers/tests/ -v`
Expected: PASS

- [ ] **Step 8: Run the full web suite**

Run: `cd services/web && pytest -v`
Expected: PASS — all existing + new tests green

- [ ] **Step 9: Commit**

```bash
git add services/web/apps/db_transfers/forms.py services/web/apps/db_transfers/views.py services/web/apps/db_transfers/urls.py services/web/templates/db_transfers/ services/web/config/urls.py services/web/templates/base.html services/web/apps/db_transfers/tests/test_views.py
git commit -m "feat(db_transfers): PgTransferForm + views + templates + navbar link"
```

---

### Task 10: End-to-end verification on rebuilt stack

**Files:** none (verification only)

**Interfaces:** none — this task validates Tasks 1-9 together against real Postgres containers.

- [ ] **Step 1: Run the full test suites one more time**

Run: `cd services/web && pytest -v` and `cd services/worker && pytest -v`
Expected: PASS on both (whole-branch sanity check before touching Docker)

- [ ] **Step 2: Rebuild the local stack**

Run: `docker compose build web worker beat` (ask user for confirmation first — production-affecting if run against the shared compose project name per `feedback-worktree-shares-docker-project-name` in project memory)
Expected: build succeeds, `postgresql-client` installs cleanly in the worker image

- [ ] **Step 3: Apply the migrations**

Run: `docker compose run --rm web python manage.py migrate`
Expected: `connections.0003_connection_kind_and_db_name` and `db_transfers.0001_initial` apply cleanly

- [ ] **Step 4: Manual smoke test — whole database**

Via the UI (or `docker compose run --rm web python manage.py shell`), create two `Connection` rows with `kind='postgres'` pointing at two throwaway Postgres databases (e.g. two local `postgres:17-alpine` containers, or two databases on the same server). Create a small test table with a few rows in the source DB. In the UI: `NEW DB TRANSFER` → SOURCE/DEST → SCOPE=CAŁA BAZA → confirm dialog appears and mentions the correct connection names → `[ EXECUTE TRANSFER ]`. Verify the log panel shows `pg_dump`/`psql` output lines and ends in `DONE`, and that the table + data now exist in the destination database (`psql` manual check or via `[TEST]`/introspection).

- [ ] **Step 5: Manual smoke test — single table + verify_row_count**

Repeat with SCOPE=POJEDYNCZA TABELA, selecting a table from the live dropdown (confirms `connections:pg_tables` introspection works end-to-end), and `VERIFY ROW COUNT` checked. Confirm the log shows `ROW COUNT OK` for the transferred table.

- [ ] **Step 6: Manual check — confirm dialog and stop button**

Confirm clicking `[ EXECUTE TRANSFER ]` shows the browser `confirm()` dialog with the expected wording for both scopes, and that cancelling it does not submit the form. Start a whole-DB transfer against a large-enough table to catch it `RUNNING`, click `[ STOP ]`, confirm the job ends in `CANCELLED`.

- [ ] **Step 7: Update project documentation**

Add a new "✅ ZREALIZOWANE" entry (point #17 or later) to `Projekt-tmask-transporter.md`'s implementation history in the vault, following the format of points #13-#16 — summarize what got built, test counts, and any bugs found during this verification pass. Update `Propozycje rozbudowy.md` point #17 status from "Backlog" to done.
