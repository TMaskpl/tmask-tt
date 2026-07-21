# MySQL/MSSQL Database Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Postgres→Postgres database transfer module (`apps/db_transfers`) to also support MySQL→MySQL and MSSQL→MSSQL, with the same-engine constraint enforced, and with explicit mitigations for the known cross-version compatibility traps of each engine.

**Architecture:** Generalize `apps/db_transfers` from Postgres-only to a three-engine app (`DbTransferJob`/`DbTransferLog` with an `engine` field, data-preserving rename from `PgTransferJob`/`PgTransferLog`). Add two new worker modules (`modules/mysql`, `modules/mssql`) mirroring the existing `modules/postgres` handler contract (`execute(log_callback)`), dispatched by `job.engine` in `tasks.py`. Add two new introspection modules on the web side (`mysql_utils.py`, `mssql_utils.py`) mirroring `pg_utils.py`.

**Tech Stack:** `mysqldump`/`mysql` CLI (MySQL, apt `default-mysql-client`), `mssql-scripter` + `sqlcmd` (MSSQL, pip + apt Microsoft repo `mssql-tools18`/`msodbcsql18`), `pymysql` (MySQL introspection), `pyodbc` (MSSQL introspection).

## Global Constraints

- Same-engine only: `source_connection.kind == dest_connection.kind` enforced in `DbTransferJob.clean()` — no MySQL→MSSQL translation in this plan.
- MySQL base flags always include `--single-transaction --set-gtid-purged=OFF --skip-lock-tables` (GTID incompatibility is a certain failure mode across instances/versions, not an edge case).
- MySQL collation compatibility: before transfer, detect destination server version via `pymysql`; if destination major version < 8, strip `COLLATE utf8mb4_0900_ai_ci` from the dump stream via `sed` before it reaches `mysql`.
- MSSQL: detect destination server version via `pyodbc` (`SELECT SERVERPROPERTY('ProductVersion')`) before running `mssql-scripter`, and pass the corresponding `--target-server-version` value explicitly. Passwords go through `-P` CLI args for `mssql-scripter`/`sqlcmd` (no env-var support in these tools) — this is an accepted, documented risk, not silently swept under the rug.
- Passwords for MySQL: `MYSQL_PWD` env var per subprocess, never as a CLI argument (mirrors the existing `PGPASSWORD` pattern).
- Every new/modified Python file gets tests in the same commit as the code (TDD): write failing test → verify fail → implement → verify pass → commit.
- Full regression (web + worker) after every task, not just at the end — this project's established discipline (see `CLAUDE.md`).

---

### Task 1: `Connection` model — mysql/mssql kind, validation, connection testers

**Files:**
- Modify: `services/web/apps/connections/models.py`
- Modify: `services/web/apps/connections/forms.py`
- Modify: `services/web/apps/connections/views.py`
- Modify: `services/web/templates/connections/form.html`
- Modify: `services/web/static/js/connections_form.js`
- Create: `services/web/apps/connections/mysql_tester.py`
- Create: `services/web/apps/connections/mssql_tester.py`
- Create: `services/web/apps/connections/migrations/0009_connection_kind_mysql_mssql.py`
- Test: `services/web/apps/connections/tests/test_models.py`
- Test: `services/web/apps/connections/tests/test_forms.py`
- Test: `services/web/apps/connections/tests/test_mysql_tester.py`
- Test: `services/web/apps/connections/tests/test_mssql_tester.py`
- Test: `services/web/apps/connections/tests/test_views.py`

**Interfaces:**
- Produces: `KIND_MYSQL = 'mysql'`, `KIND_MSSQL = 'mssql'` constants in `apps.connections.models`, added to `KIND_CHOICES`.
- Produces: `mysql_tester.test_connection(connection) -> MysqlTestResult(success: bool, message: str)`, `mssql_tester.test_connection(connection) -> MssqlTestResult(success: bool, message: str)` — same shape as existing `PgTestResult`.

- [ ] **Step 1: Write failing tests for the new `kind` choices and `db_name` validation**

```python
# services/web/apps/connections/tests/test_models.py (add to existing file)
import pytest
from django.core.exceptions import ValidationError
from apps.connections.models import Connection, KIND_MYSQL, KIND_MSSQL


@pytest.mark.django_db
class TestConnectionDbKinds:
    def test_mysql_requires_db_name(self, regular_user):
        conn = Connection(owner=regular_user, name='x', host='h', port=3306,
                           username='u', password='p', kind=KIND_MYSQL, db_name='')
        with pytest.raises(ValidationError):
            conn.clean()

    def test_mssql_requires_db_name(self, regular_user):
        conn = Connection(owner=regular_user, name='x', host='h', port=1433,
                           username='u', password='p', kind=KIND_MSSQL, db_name='')
        with pytest.raises(ValidationError):
            conn.clean()

    def test_mysql_with_db_name_is_valid(self, regular_user):
        conn = Connection(owner=regular_user, name='x', host='h', port=3306,
                           username='u', password='p', kind=KIND_MYSQL, db_name='mydb')
        conn.clean()  # should not raise
```

- [ ] **Step 2: Run to verify failure**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/connections/tests/test_models.py -k TestConnectionDbKinds -q`
Expected: `ImportError: cannot import name 'KIND_MYSQL'`

- [ ] **Step 3: Add `KIND_MYSQL`/`KIND_MSSQL` and extend validation**

```python
# services/web/apps/connections/models.py — edit near existing KIND_* constants
KIND_SSH = 'ssh'
KIND_POSTGRES = 'postgres'
KIND_MYSQL = 'mysql'
KIND_MSSQL = 'mssql'
KIND_CHOICES = [
    (KIND_SSH, 'SSH'), (KIND_POSTGRES, 'Postgres'),
    (KIND_MYSQL, 'MySQL'), (KIND_MSSQL, 'MSSQL'),
]
KIND_DB_KINDS = (KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL)
```

Update `Connection.clean()`:

```python
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.kind in KIND_DB_KINDS and not self.db_name:
            raise ValidationError('DB NAME jest wymagane dla połączeń bazodanowych (Postgres/MySQL/MSSQL).')
```

- [ ] **Step 4: Run to verify pass**

Run: same command as Step 2.
Expected: PASS (3 passed).

- [ ] **Step 5: Migration**

Run: `docker compose run --rm -v "$PWD/services/web:/app" web python manage.py makemigrations connections` — verify it produces only a choices-metadata change (`kind` field `choices=` alteration), no schema/column change, so no data migration is needed. Rename the generated file to `0009_connection_kind_mysql_mssql.py` if the auto-generated name differs.

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/connections/models.py services/web/apps/connections/migrations/0009_connection_kind_mysql_mssql.py services/web/apps/connections/tests/test_models.py
git commit -m "feat(connections): add mysql/mssql kind values + db_name validation"
```

- [ ] **Step 7: Write failing tests for `ConnectionForm` — db_name required/label for all three DB kinds**

```python
# services/web/apps/connections/tests/test_forms.py (add)
import pytest
from apps.connections.forms import ConnectionForm
from apps.connections.models import KIND_MYSQL, KIND_MSSQL


@pytest.mark.django_db
class TestConnectionFormDbKinds:
    def test_mysql_without_db_name_invalid(self):
        form = ConnectionForm({'name': 'x', 'kind': KIND_MYSQL, 'host': 'h', 'port': 3306,
                                'username': 'u', 'password': 'p', 'db_name': ''})
        assert not form.is_valid()

    def test_mssql_without_password_invalid(self):
        form = ConnectionForm({'name': 'x', 'kind': KIND_MSSQL, 'host': 'h', 'port': 1433,
                                'username': 'u', 'db_name': 'db'})
        assert not form.is_valid()
```

- [ ] **Step 8: Run to verify failure**, then generalize `ConnectionForm.clean()`

```python
# services/web/apps/connections/forms.py
from .models import Connection, KIND_DB_KINDS

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get('kind')
        if kind in KIND_DB_KINDS:
            if not cleaned.get('password'):
                raise forms.ValidationError('Podaj hasło do bazy danych.')
            if not cleaned.get('db_name'):
                raise forms.ValidationError('Podaj nazwę bazy danych (DB NAME).')
        else:
            if not cleaned.get('password') and not cleaned.get('ssh_key'):
                raise forms.ValidationError('Podaj hasło lub klucz SSH.')
        return cleaned
```

Update the `db_name` label in `Meta.labels` from `'DB NAME (tylko Postgres)'` to `'DB NAME (Postgres/MySQL/MSSQL)'`.

- [ ] **Step 9: Run to verify pass, commit**

```bash
git add services/web/apps/connections/forms.py services/web/apps/connections/tests/test_forms.py
git commit -m "feat(connections): ConnectionForm validates db_name/password for all DB kinds"
```

- [ ] **Step 10: Write failing tests for `mysql_tester.py`/`mssql_tester.py`**

```python
# services/web/apps/connections/tests/test_mysql_tester.py
from unittest.mock import patch, MagicMock
import pymysql
from apps.connections.mysql_tester import test_connection


class _Conn:
    host = 'h'; port = 3306; username = 'u'; password = 'p'; db_name = 'd'


def test_success():
    with patch('apps.connections.mysql_tester.pymysql.connect') as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        result = test_connection(_Conn())
        assert result.success is True
        mock_conn.close.assert_called_once()


def test_failure():
    with patch('apps.connections.mysql_tester.pymysql.connect', side_effect=pymysql.OperationalError('refused')):
        result = test_connection(_Conn())
        assert result.success is False
        assert 'refused' in result.message
```

```python
# services/web/apps/connections/tests/test_mssql_tester.py
from unittest.mock import patch, MagicMock
import pyodbc
from apps.connections.mssql_tester import test_connection


class _Conn:
    host = 'h'; port = 1433; username = 'u'; password = 'p'; db_name = 'd'


def test_success():
    with patch('apps.connections.mssql_tester.pyodbc.connect') as mock_connect:
        mock_connect.return_value = MagicMock()
        result = test_connection(_Conn())
        assert result.success is True


def test_failure():
    with patch('apps.connections.mssql_tester.pyodbc.connect', side_effect=pyodbc.OperationalError('refused')):
        result = test_connection(_Conn())
        assert result.success is False
```

- [ ] **Step 11: Run to verify failure (ModuleNotFoundError), then implement**

```python
# services/web/apps/connections/mysql_tester.py
from dataclasses import dataclass
import pymysql


@dataclass
class MysqlTestResult:
    success: bool
    message: str


def test_connection(connection) -> MysqlTestResult:
    try:
        conn = pymysql.connect(
            host=connection.host, port=connection.port, user=connection.username,
            password=connection.password, database=connection.db_name, connect_timeout=10,
        )
        conn.close()
        return MysqlTestResult(True, 'CONNECTION OK')
    except pymysql.OperationalError as e:
        return MysqlTestResult(False, f'CONNECTION FAILED — {e}'.strip())
```

```python
# services/web/apps/connections/mssql_tester.py
from dataclasses import dataclass
import pyodbc


@dataclass
class MssqlTestResult:
    success: bool
    message: str


def _conn_string(connection) -> str:
    return (
        f'DRIVER={{ODBC Driver 18 for SQL Server}};'
        f'SERVER={connection.host},{connection.port};DATABASE={connection.db_name};'
        f'UID={connection.username};PWD={connection.password};TrustServerCertificate=yes;'
    )


def test_connection(connection) -> MssqlTestResult:
    try:
        conn = pyodbc.connect(_conn_string(connection), timeout=10)
        conn.close()
        return MssqlTestResult(True, 'CONNECTION OK')
    except pyodbc.OperationalError as e:
        return MssqlTestResult(False, f'CONNECTION FAILED — {e}'.strip())
```

- [ ] **Step 12: Run to verify pass, commit**

```bash
git add services/web/apps/connections/mysql_tester.py services/web/apps/connections/mssql_tester.py services/web/apps/connections/tests/test_mysql_tester.py services/web/apps/connections/tests/test_mssql_tester.py
git commit -m "feat(connections): mysql/mssql connection testers"
```

- [ ] **Step 13: Write failing test for `connection_test` view dispatching to the new testers**

```python
# services/web/apps/connections/tests/test_views.py (add)
from unittest.mock import patch
import pytest
from django.urls import reverse
from apps.connections.models import KIND_MYSQL, KIND_MSSQL


@pytest.mark.django_db
class TestConnectionTestDispatchDbKinds:
    def test_mysql_kind_calls_mysql_tester(self, admin_client, make_connection, admin_user):
        conn = make_connection(admin_user, kind=KIND_MYSQL, db_name='d')
        with patch('apps.connections.views._test_mysql_connection') as mock_test:
            mock_test.return_value = None
            admin_client.get(reverse('connections:test', args=[conn.pk]))
            mock_test.assert_called_once()

    def test_mssql_kind_calls_mssql_tester(self, admin_client, make_connection, admin_user):
        conn = make_connection(admin_user, kind=KIND_MSSQL, db_name='d')
        with patch('apps.connections.views._test_mssql_connection') as mock_test:
            mock_test.return_value = None
            admin_client.get(reverse('connections:test', args=[conn.pk]))
            mock_test.assert_called_once()
```

- [ ] **Step 14: Run to verify failure, then generalize the dispatch in `views.py`**

```python
# services/web/apps/connections/views.py
from .mysql_tester import test_connection as _test_mysql_connection
from .pg_tester import test_connection as _test_pg_connection
from .mssql_tester import test_connection as _test_mssql_connection
from .models import KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL

def connection_test(request, pk):
    conn = get_object_or_404(Connection, pk=pk)
    if conn.kind == KIND_POSTGRES:
        result = _test_pg_connection(conn)
    elif conn.kind == KIND_MYSQL:
        result = _test_mysql_connection(conn)
    elif conn.kind == KIND_MSSQL:
        result = _test_mssql_connection(conn)
    else:
        result = _test_connection(conn)
    return render(request, 'connections/_test_result.html', {'result': result})
```

- [ ] **Step 15: Run to verify pass, commit**

```bash
git add services/web/apps/connections/views.py services/web/apps/connections/tests/test_views.py
git commit -m "feat(connections): dispatch [TEST] button to mysql/mssql testers"
```

- [ ] **Step 16: Template + JS — show DB NAME block for all three DB kinds, default port per kind**

In `services/web/templates/connections/form.html`, change the wrapper class from `postgres-only-field` to `db-kind-field` around the `DB NAME` block, and update the box title to `DATABASE`.

In `services/web/static/js/connections_form.js`, replace the Postgres-only toggle with a generic DB-kind toggle plus a default-port suggestion:

```javascript
  const DB_KINDS = ['postgres', 'mysql', 'mssql'];
  const DEFAULT_PORTS = { postgres: 5432, mysql: 3306, mssql: 1433, ssh: 22 };

  function toggleKind() {
    const kind = document.getElementById('id_kind');
    if (!kind) return;
    const sshFields = document.querySelectorAll('.ssh-only-field');
    const dbFields = document.querySelectorAll('.db-kind-field');
    sshFields.forEach(function (el) { el.style.display = (kind.value === 'ssh') ? '' : 'none'; });
    dbFields.forEach(function (el) { el.style.display = DB_KINDS.includes(kind.value) ? '' : 'none'; });
    if (kind.value === 'ssh') toggleKnownHost();
  }

  function suggestPort() {
    const kind = document.getElementById('id_kind');
    const port = document.getElementById('id_port');
    if (!kind || !port) return;
    // Only overwrite an empty/default-looking port — never clobber a value the user already typed.
    if (!port.dataset.touched) port.value = DEFAULT_PORTS[kind.value] || '';
  }
```

Wire `kind.addEventListener('change', function () { toggleKind(); suggestPort(); })` and mark `port.dataset.touched = 'true'` on the port field's own `input` event, so a manually-entered port is never silently overwritten.

- [ ] **Step 17: Manual smoke test — no automated test for pure CSS/JS toggle (mirrors existing untested `toggleKnownHost`)**

Start the dev stack, open `/connections/new/`, switch `KIND` through all four values, confirm the DB NAME block and port suggestion behave correctly.

- [ ] **Step 18: Commit**

```bash
git add services/web/templates/connections/form.html services/web/static/js/connections_form.js
git commit -m "feat(connections): show DB NAME for mysql/mssql, suggest default port per kind"
```

---

### Task 2: Rename `PgTransferJob`/`PgTransferLog` → `DbTransferJob`/`DbTransferLog` + `engine` field

**Files:**
- Modify: `services/web/apps/db_transfers/models.py`
- Create: `services/web/apps/db_transfers/migrations/0003_rename_pg_to_db_transfer.py`
- Test: `services/web/apps/db_transfers/tests/test_models.py`

**Interfaces:**
- Produces: `DbTransferJob` (was `PgTransferJob`), `DbTransferLog` (was `PgTransferLog`), both with all existing fields unchanged plus new `engine` field (`CharField`, choices `postgres`/`mysql`/`mssql`).
- Consumes: `KIND_POSTGRES`/`KIND_MYSQL`/`KIND_MSSQL` from `apps.connections.models` (Task 1).

- [ ] **Step 1: Write failing test for the rename + `engine` field + cross-kind validation**

```python
# services/web/apps/db_transfers/tests/test_models.py (add)
import pytest
from django.core.exceptions import ValidationError
from apps.db_transfers.models import DbTransferJob
from apps.connections.models import KIND_MYSQL, KIND_MSSQL


@pytest.mark.django_db
class TestDbTransferJobEngine:
    def test_engine_set_from_source_connection_kind_on_save(self, regular_user, make_connection):
        src = make_connection(regular_user, kind=KIND_MYSQL, db_name='a')
        dst = make_connection(regular_user, kind=KIND_MYSQL, db_name='b')
        job = DbTransferJob(owner=regular_user, source_connection=src, dest_connection=dst)
        job.engine = src.kind
        job.save()
        assert job.engine == KIND_MYSQL

    def test_clean_rejects_mismatched_engine_kinds(self, regular_user, make_connection):
        src = make_connection(regular_user, kind=KIND_MYSQL, db_name='a')
        dst = make_connection(regular_user, kind=KIND_MSSQL, db_name='b')
        job = DbTransferJob(owner=regular_user, source_connection=src, dest_connection=dst)
        with pytest.raises(ValidationError):
            job.clean()
```

- [ ] **Step 2: Run to verify failure**

Run: `docker compose --profile test run --rm web-test python -m pytest apps/db_transfers/tests/test_models.py -k TestDbTransferJobEngine -q`
Expected: `ImportError: cannot import name 'DbTransferJob'`

- [ ] **Step 3: Rename models and add `engine` field**

```python
# services/web/apps/db_transfers/models.py — rename class, add field + clean()
class DbTransferJob(models.Model):
    owner             = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='db_jobs'
    )
    source_connection = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='db_source_jobs'
    )
    dest_connection   = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='db_dest_jobs'
    )
    engine            = models.CharField(max_length=10, choices=[
        ('postgres', 'Postgres'), ('mysql', 'MySQL'), ('mssql', 'MSSQL'),
    ])
    table_name        = models.CharField(max_length=255, blank=True)
    verify_row_count  = models.BooleanField(default=False)
    status            = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    celery_task_id    = models.CharField(max_length=255, blank=True, default='')
    created_at        = models.DateTimeField(auto_now_add=True)
    started_at        = models.DateTimeField(null=True, blank=True)
    finished_at       = models.DateTimeField(null=True, blank=True)
    error_message     = models.TextField(blank=True, default='')
    cancelled_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cancelled_db_jobs',
    )

    def clean(self):
        if self.source_connection_id and self.dest_connection_id and self.source_connection_id == self.dest_connection_id:
            raise ValidationError('Source and destination connection cannot be the same.')
        if self.source_connection_id and self.dest_connection_id and self.source_connection.kind != self.dest_connection.kind:
            raise ValidationError('Source and destination must be the same database engine.')
    # mark_running/mark_done/mark_failed/mark_cancelled/__str__/Meta unchanged, just renamed class


class DbTransferLog(models.Model):
    job       = models.ForeignKey(DbTransferJob, on_delete=models.CASCADE, related_name='logs')
    # timestamp/level/message/Meta unchanged
```

- [ ] **Step 4: Generate the rename migration — MUST use `RenameModel`, not drop+recreate**

```bash
docker compose run --rm -v "$PWD/services/web:/app" web python manage.py makemigrations db_transfers
```

Open the generated file and verify it contains `migrations.RenameModel('PgTransferJob', 'DbTransferJob')` and `migrations.RenameModel('PgTransferLog', 'DbTransferLog')` **before** the `AddField` for `engine` — Django's autodetector asks interactively whether a model was renamed; when running non-interactively confirm this by inspecting the diff, and if it instead generated a `DeleteModel`+`CreateModel` pair, discard the file and re-run `makemigrations db_transfers` answering "yes, renamed" at the prompt (run without `-v` piping, i.e. attached, so the prompt is visible). Rename the file to `0003_rename_pg_to_db_transfer.py`. The `engine` field has no default — add a data migration step in the same file (`RunPython`) that backfills `engine` from each existing row's `source_connection.kind` for any pre-existing `PgTransferJob` rows (all of which are Postgres, so this is `engine='postgres'` for all existing rows before the field becomes non-nullable), or alternatively give the field a temporary `default='postgres'` in the `AddField` (simpler, correct because 100% of pre-existing rows are Postgres by construction) — prefer the `default='postgres'` route for simplicity.

- [ ] **Step 5: Run to verify pass**

Run: same command as Step 2.
Expected: PASS (2 passed). Also run the full `db_transfers` suite to catch any other reference to the old class name: `docker compose --profile test run --rm web-test python -m pytest apps/db_transfers/ -q` — expect failures in `test_views.py`/`test_forms.py`/`conftest.py` referencing `PgTransferJob`; these are fixed in Tasks 6 and 8, not this task. Confirm the failures are exactly import/reference errors for the renamed class (not new logic bugs) before moving on.

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/db_transfers/models.py services/web/apps/db_transfers/migrations/0003_rename_pg_to_db_transfer.py services/web/apps/db_transfers/tests/test_models.py
git commit -m "feat(db-transfers): rename PgTransferJob/Log to DbTransferJob/Log, add engine field"
```

---

### Task 3: MySQL worker handler

**Files:**
- Create: `services/worker/modules/mysql/__init__.py`
- Create: `services/worker/modules/mysql/config.py`
- Create: `services/worker/modules/mysql/handler.py`
- Test: `services/worker/tests/test_mysql_handler.py`

**Interfaces:**
- Produces: `MysqlTransferHandler(params).execute(log_callback)` — same contract as `PgTransferHandler`, `params` dict has the same key shape as `_build_pg_params()` in `tasks.py` (`source_host`, `source_port`, `source_username`, `source_password`, `source_db_name`, `dest_host`, `dest_port`, `dest_username`, `dest_password`, `dest_db_name`, `table_name`, `verify_row_count`).
- Consumes: `pymysql` for version detection and row-count verification (new dependency, added in Task 7 — until Task 7 lands, tests must mock `pymysql` entirely, no real import required to pass).

- [ ] **Step 1: Write failing tests for command building**

```python
# services/worker/tests/test_mysql_handler.py
import pytest
from unittest.mock import patch, MagicMock

from modules.mysql.handler import MysqlTransferHandler, MysqlTransferError
from modules.mysql.config import MYSQL_DUMP_MAX_RETRIES, MYSQL_DUMP_RETRY_DELAY


class TestMysqlTransferHandler:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': '10.0.0.1', 'source_port': 3306, 'source_username': 'root',
            'source_password': 'srcpass', 'source_db_name': 'proddb',
            'dest_host': '10.0.0.2', 'dest_port': 3306, 'dest_username': 'root',
            'dest_password': 'dstpass', 'dest_db_name': 'testdb',
            'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_builds_whole_db_mysqldump_command(self):
        handler = MysqlTransferHandler(self._make_params())
        cmd = handler._build_mysqldump_cmd()
        assert cmd[0] == 'mysqldump'
        assert '-h' in cmd and '10.0.0.1' in cmd
        assert '--single-transaction' in cmd
        assert '--set-gtid-purged=OFF' in cmd
        assert '--skip-lock-tables' in cmd
        assert cmd[-1] == 'proddb'

    def test_builds_single_table_mysqldump_command(self):
        handler = MysqlTransferHandler(self._make_params(table_name='users'))
        cmd = handler._build_mysqldump_cmd()
        assert cmd[-2:] == ['proddb', 'users']

    def test_builds_mysql_client_command(self):
        handler = MysqlTransferHandler(self._make_params())
        cmd = handler._build_mysql_cmd()
        assert cmd[0] == 'mysql'
        assert '10.0.0.2' in cmd
        assert 'testdb' in cmd
```

- [ ] **Step 2: Run to verify failure**

Run: `docker compose run --rm -v "$PWD/services/worker:/app" worker python -m pytest tests/test_mysql_handler.py -q`
Expected: `ModuleNotFoundError: No module named 'modules.mysql'`

- [ ] **Step 3: Implement config + command building**

```python
# services/worker/modules/mysql/config.py
MYSQL_DUMP_BASE_FLAGS = ['--single-transaction', '--set-gtid-purged=OFF', '--skip-lock-tables']
MYSQL_DUMP_MAX_RETRIES = 3
MYSQL_DUMP_RETRY_DELAY = 5

# MySQL 8.0 changed the default utf8mb4 collation from utf8mb4_general_ci to
# utf8mb4_0900_ai_ci. A dump taken from an 8.0+ source embeds this collation in
# CREATE TABLE statements; restoring into a pre-8.0 destination (which doesn't
# know this collation) fails with "Unknown collation". Stripped in transit when
# the destination is detected as < 8.0 — see handler._maybe_strip_collation().
SED_STRIP_MYSQL80_COLLATION = r's/ COLLATE utf8mb4_0900_ai_ci//g'
```

```python
# services/worker/modules/mysql/handler.py
import os
import subprocess  # nosec B404
import threading
import time
from typing import Callable

from .config import (
    MYSQL_DUMP_BASE_FLAGS,
    MYSQL_DUMP_MAX_RETRIES,
    MYSQL_DUMP_RETRY_DELAY,
    SED_STRIP_MYSQL80_COLLATION,
)


class MysqlTransferError(Exception):
    pass


class MysqlTransferHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_mysqldump_cmd(self) -> list:
        p = self.params
        cmd = ['mysqldump', '-h', p['source_host'], '-P', str(p['source_port']), '-u', p['source_username']]
        cmd += list(MYSQL_DUMP_BASE_FLAGS)
        cmd.append(p['source_db_name'])
        if p.get('table_name'):
            cmd.append(p['table_name'])
        return cmd

    def _build_mysql_cmd(self) -> list:
        p = self.params
        return ['mysql', '-h', p['dest_host'], '-P', str(p['dest_port']), '-u', p['dest_username'], p['dest_db_name']]
```

- [ ] **Step 4: Run to verify pass**

Run: same command as Step 2.
Expected: PASS (3 passed).

- [ ] **Step 5: Write failing test for destination-version detection + collation stripping**

```python
# services/worker/tests/test_mysql_handler.py (add)
class TestMysqlCollationCompat:
    def _make_params(self):
        return {
            'source_host': 'a', 'source_port': 3306, 'source_username': 'u', 'source_password': 'p',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 3306, 'dest_username': 'u',
            'dest_password': 'p', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }

    def test_dest_version_below_8_strips_collation(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.pymysql.connect') as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = ('5.7.44-log',)
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cursor
            assert handler._dest_needs_collation_strip() is True

    def test_dest_version_8_or_above_does_not_strip(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.pymysql.connect') as mock_connect:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = ('8.0.35',)
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = mock_cursor
            assert handler._dest_needs_collation_strip() is False

    def test_dest_unreachable_defaults_to_no_strip_and_warns(self):
        import pymysql
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.pymysql.connect', side_effect=pymysql.OperationalError('down')):
            logs = []
            assert handler._dest_needs_collation_strip(log_callback=lambda lvl, msg: logs.append((lvl, msg))) is False
            assert any('COLLATION' in msg.upper() or 'VERSION' in msg.upper() for _, msg in logs)
```

- [ ] **Step 6: Run to verify failure, then implement version detection**

```python
# services/worker/modules/mysql/handler.py — add import + method
import pymysql

    def _dest_needs_collation_strip(self, log_callback: Callable[[str, str], None] = None) -> bool:
        p = self.params
        try:
            with pymysql.connect(host=p['dest_host'], port=p['dest_port'], user=p['dest_username'],
                                  password=p['dest_password'], connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT VERSION()')
                    version_str = cur.fetchone()[0]
            major = int(version_str.split('.')[0])
            return major < 8
        except (pymysql.Error, ValueError, IndexError) as e:
            if log_callback:
                log_callback('warn', f'Nie udało się wykryć wersji serwera docelowego dla kompatybilności kolacji — {e}. Zakładam brak konfliktu.')
            return False
```

- [ ] **Step 7: Run to verify pass, commit**

```bash
git add services/worker/modules/mysql/config.py services/worker/modules/mysql/handler.py services/worker/tests/test_mysql_handler.py
git commit -m "feat(mysql-transfer): command building + destination-version collation check"
```

- [ ] **Step 8: Write failing test for the full pipe execution + password-via-env contract**

```python
# services/worker/tests/test_mysql_handler.py (add)
class TestMysqlTransferExecute:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': 'a', 'source_port': 3306, 'source_username': 'u', 'source_password': 'srcpw',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 3306, 'dest_username': 'u',
            'dest_password': 'dstpw', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    def _mock_proc(self, stderr_lines, exit_code):
        proc = MagicMock()
        proc.stderr = iter(stderr_lines)
        proc.stdout = MagicMock()
        proc.wait.return_value = exit_code
        return proc

    def test_successful_transfer(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.MysqlTransferHandler._dest_needs_collation_strip', return_value=False), \
             patch('modules.mysql.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler.execute(log_callback=lambda lvl, msg: None)  # should not raise

    def test_mysql_pwd_env_never_in_argv(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.MysqlTransferHandler._dest_needs_collation_strip', return_value=False), \
             patch('modules.mysql.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler.execute(log_callback=lambda lvl, msg: None)
            for call in MockPopen.call_args_list:
                cmd = call.args[0]
                assert 'srcpw' not in cmd and 'dstpw' not in cmd
                assert 'MYSQL_PWD' in call.kwargs['env']

    def test_collation_stripped_when_dest_below_8(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.MysqlTransferHandler._dest_needs_collation_strip', return_value=True), \
             patch('modules.mysql.handler.subprocess.Popen') as MockPopen:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0), self._mock_proc([], 0)]
            handler.execute(log_callback=lambda lvl, msg: None)
            sed_calls = [c for c in MockPopen.call_args_list if c.args[0][0] == 'sed']
            assert len(sed_calls) == 1

    def test_retries_on_failure_then_raises(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.MysqlTransferHandler._dest_needs_collation_strip', return_value=False), \
             patch('modules.mysql.handler.subprocess.Popen') as MockPopen, \
             patch('modules.mysql.handler.time.sleep'):
            MockPopen.side_effect = [self._mock_proc([], 1), self._mock_proc([], 1)] * MYSQL_DUMP_MAX_RETRIES
            with pytest.raises(MysqlTransferError):
                handler.execute(log_callback=lambda lvl, msg: None)
```

- [ ] **Step 9: Run to verify failure, then implement `_run_pipe`/`execute`** (mirrors `PgTransferHandler._run_pipe`/`execute` exactly, with a conditional `sed` stage inserted when collation stripping is needed)

```python
# services/worker/modules/mysql/handler.py — add methods
    def _run_pipe(self, log_callback: Callable[[str, str], None], strip_collation: bool) -> tuple:
        dump_cmd = self._build_mysqldump_cmd()
        mysql_cmd = self._build_mysql_cmd()
        dump_env = {**os.environ, 'MYSQL_PWD': self.params['source_password']}
        mysql_env = {**os.environ, 'MYSQL_PWD': self.params['dest_password']}

        dump_proc = subprocess.Popen(  # nosec B603
            dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dump_env,
        )
        feed_stdout = dump_proc.stdout
        sed_proc = None
        if strip_collation:
            sed_proc = subprocess.Popen(  # nosec B603 — static sed pattern, no user input
                ['sed', SED_STRIP_MYSQL80_COLLATION], stdin=dump_proc.stdout, stdout=subprocess.PIPE, text=True,
            )
            dump_proc.stdout.close()
            feed_stdout = sed_proc.stdout

        mysql_proc = subprocess.Popen(  # nosec B603
            mysql_cmd, stdin=feed_stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=mysql_env,
        )
        feed_stdout.close()

        output_lines = []
        output_lock = threading.Lock()

        def _drain(stream):
            for line in stream:
                line = line.rstrip()
                if line:
                    with output_lock:
                        output_lines.append(line)
                    log_callback('info', line)

        threads = [threading.Thread(target=_drain, args=(mysql_proc.stderr,)),
                   threading.Thread(target=_drain, args=(dump_proc.stderr,))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        mysql_exit = mysql_proc.wait()
        if sed_proc:
            sed_proc.wait()
        dump_exit = dump_proc.wait()
        return dump_exit, mysql_exit, '\n'.join(output_lines)

    def _check_output(self, output: str) -> None:
        lowered = output.lower()
        if 'access denied' in lowered:
            raise MysqlTransferError('AUTH FAILED — sprawdź dane uwierzytelniania')
        if self.params.get('table_name') and "doesn't exist" in lowered:
            raise MysqlTransferError(f'TABLE NOT FOUND: {self.params["table_name"]}')

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        strip_collation = self._dest_needs_collation_strip(log_callback)
        last_dump_exit = last_mysql_exit = None
        for attempt in range(1, MYSQL_DUMP_MAX_RETRIES + 1):
            log_callback('info', f'Starting mysqldump|mysql (attempt {attempt})')
            last_dump_exit, last_mysql_exit, output = self._run_pipe(log_callback, strip_collation)
            self._check_output(output)
            if last_dump_exit == 0 and last_mysql_exit == 0:
                log_callback('info', 'Transfer complete')
                if self.params.get('verify_row_count'):
                    self._verify_row_counts(log_callback)
                return
            if attempt < MYSQL_DUMP_MAX_RETRIES:
                log_callback('warn', f'mysqldump/mysql failed (dump={last_dump_exit}, mysql={last_mysql_exit}), retrying in {MYSQL_DUMP_RETRY_DELAY}s...')
                time.sleep(MYSQL_DUMP_RETRY_DELAY)

        raise MysqlTransferError(
            f'TRANSFER FAILED — mysqldump/mysql failed after {MYSQL_DUMP_MAX_RETRIES} attempts '
            f'(dump exit={last_dump_exit}, mysql exit={last_mysql_exit})'
        )
```

- [ ] **Step 10: Run to verify pass**

Run: `docker compose run --rm -v "$PWD/services/worker:/app" worker python -m pytest tests/test_mysql_handler.py -q`
Expected: all PASS.

- [ ] **Step 11: Write failing test for `_verify_row_counts`** (mirror `PgTransferHandler._verify_row_counts`, using `pymysql` and `information_schema.tables` instead of `psycopg2`/`pg_tables`)

```python
# services/worker/tests/test_mysql_handler.py (add)
class TestMysqlVerifyRowCounts:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': 'a', 'source_port': 3306, 'source_username': 'u', 'source_password': 'p',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 3306, 'dest_username': 'u',
            'dest_password': 'p', 'dest_db_name': 'dst', 'table_name': 'users', 'verify_row_count': True,
        }
        defaults.update(kwargs)
        return defaults

    def test_matching_counts_logs_info_not_warn(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.pymysql.connect') as mock_connect:
            cur = MagicMock()
            cur.fetchone.return_value = (5,)
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            logs = []
            handler._verify_row_counts(lambda lvl, msg: logs.append((lvl, msg)))
            assert not any(lvl == 'warn' for lvl, _ in logs)

    def test_mismatched_counts_logs_warn(self):
        handler = MysqlTransferHandler(self._make_params())
        with patch('modules.mysql.handler.pymysql.connect') as mock_connect:
            cur = MagicMock()
            cur.fetchone.side_effect = [(5,), (3,)]
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            logs = []
            handler._verify_row_counts(lambda lvl, msg: logs.append((lvl, msg)))
            assert any(lvl == 'warn' for lvl, _ in logs)
```

- [ ] **Step 12: Run to verify failure, then implement**

```python
# services/worker/modules/mysql/handler.py — add method
    def _verify_row_counts(self, log_callback: Callable[[str, str], None]) -> None:
        p = self.params
        try:
            src_conn = pymysql.connect(host=p['source_host'], port=p['source_port'], user=p['source_username'],
                                        password=p['source_password'], database=p['source_db_name'], connect_timeout=10)
        except pymysql.Error as e:
            log_callback('warn', f'ROW COUNT VERIFICATION SKIPPED — nie udało się połączyć ze źródłem: {e}')
            return
        try:
            dst_conn = pymysql.connect(host=p['dest_host'], port=p['dest_port'], user=p['dest_username'],
                                        password=p['dest_password'], database=p['dest_db_name'], connect_timeout=10)
        except pymysql.Error as e:
            src_conn.close()
            log_callback('warn', f'ROW COUNT VERIFICATION SKIPPED — nie udało się połączyć z celem: {e}')
            return
        try:
            if p.get('table_name'):
                tables = [p['table_name']]
            else:
                with src_conn.cursor() as cur:
                    cur.execute(
                        'SELECT table_name FROM information_schema.tables WHERE table_schema = %s',
                        (p['source_db_name'],),
                    )
                    tables = [row[0] for row in cur.fetchall()]
            for table in tables:
                with src_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM `{table}`')  # nosec B608 — table name from information_schema/user-selected dropdown, not raw user text input
                    src_count = cur.fetchone()[0]
                with dst_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM `{table}`')  # nosec B608
                    dst_count = cur.fetchone()[0]
                if src_count != dst_count:
                    log_callback('warn', f'ROW COUNT MISMATCH w "{table}": source={src_count} dest={dst_count}')
                else:
                    log_callback('info', f'ROW COUNT OK w "{table}": {src_count}')
        except pymysql.Error as e:
            log_callback('warn', f'ROW COUNT VERIFICATION FAILED — {e}')
        finally:
            src_conn.close()
            dst_conn.close()
```

- [ ] **Step 13: Run full mysql handler suite, verify pass, commit**

```bash
docker compose run --rm -v "$PWD/services/worker:/app" worker python -m pytest tests/test_mysql_handler.py -q
git add services/worker/modules/mysql/handler.py services/worker/tests/test_mysql_handler.py
git commit -m "feat(mysql-transfer): pipe execution, retries, row-count verification"
```

---

### Task 4: MSSQL worker handler

**Files:**
- Create: `services/worker/modules/mssql/__init__.py`
- Create: `services/worker/modules/mssql/config.py`
- Create: `services/worker/modules/mssql/handler.py`
- Test: `services/worker/tests/test_mssql_handler.py`

**Interfaces:**
- Produces: `MssqlTransferHandler(params).execute(log_callback)` — same contract, same `params` shape as Task 3.
- Consumes: `pyodbc` for version detection and row-count verification (new dependency, Task 7).

- [ ] **Step 1: Write failing tests for target-version mapping**

```python
# services/worker/tests/test_mssql_handler.py
import pytest
from unittest.mock import patch, MagicMock

from modules.mssql.handler import MssqlTransferHandler, MssqlTransferError
from modules.mssql.config import MSSQL_MAX_RETRIES


class TestMssqlTargetVersionMapping:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'srcpw',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'dstpw', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    @pytest.mark.parametrize('product_version,expected_target', [
        ('12.0.2000.8', '2014'),
        ('13.0.1000.0', '2016'),
        ('14.0.1000.0', '2017'),
        ('15.0.2000.5', '2019'),
        ('16.0.1000.6', '2019'),  # SQL Server 2022 — mssql-scripter has no '2022' target, cap at newest known
    ])
    def test_maps_product_version_to_target(self, product_version, expected_target):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.pyodbc.connect') as mock_connect:
            cur = MagicMock()
            cur.fetchone.return_value = (product_version,)
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            assert handler._dest_target_server_version() == expected_target

    def test_unreachable_dest_defaults_to_newest_known_and_warns(self):
        import pyodbc
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.pyodbc.connect', side_effect=pyodbc.OperationalError('down')):
            logs = []
            result = handler._dest_target_server_version(log_callback=lambda lvl, msg: logs.append((lvl, msg)))
            assert result == '2019'
            assert any('VERSION' in msg.upper() for _, msg in logs)
```

- [ ] **Step 2: Run to verify failure**

Run: `docker compose run --rm -v "$PWD/services/worker:/app" worker python -m pytest tests/test_mssql_handler.py -q`
Expected: `ModuleNotFoundError: No module named 'modules.mssql'`

- [ ] **Step 3: Implement config + version mapping**

```python
# services/worker/modules/mssql/config.py
MSSQL_MAX_RETRIES = 3
MSSQL_RETRY_DELAY = 5

# mssql-scripter's --target-server-version accepts a fixed set of values and has not
# been updated for SQL Server 2022 (major version 16) — the tool itself is the
# constraint here, not our code. Any detected major version at or above 15 (2019)
# is capped at '2019', the newest value the tool understands; this is the same
# "newer client, older/differently-versioned server" compatibility problem already
# solved for Postgres (SED_STRIP_INCOMPATIBLE_SET) and MySQL (collation stripping),
# just solved by the tool's own targeting flag instead of a manual filter.
MSSQL_VERSION_MAP = {
    9: '2005', 10: '2008', 11: '2012', 12: '2014', 13: '2016', 14: '2017',
}
MSSQL_NEWEST_KNOWN_TARGET = '2019'
```

```python
# services/worker/modules/mssql/handler.py
import os
import subprocess  # nosec B404
import tempfile
import time
from typing import Callable

import pyodbc

from .config import MSSQL_MAX_RETRIES, MSSQL_RETRY_DELAY, MSSQL_VERSION_MAP, MSSQL_NEWEST_KNOWN_TARGET


class MssqlTransferError(Exception):
    pass


class MssqlTransferHandler:
    def __init__(self, params: dict):
        self.params = params

    def _conn_string(self, host, port, db, user, password) -> str:
        return (
            f'DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={host},{port};DATABASE={db};'
            f'UID={user};PWD={password};TrustServerCertificate=yes;'
        )

    def _dest_target_server_version(self, log_callback: Callable[[str, str], None] = None) -> str:
        p = self.params
        try:
            with pyodbc.connect(
                self._conn_string(p['dest_host'], p['dest_port'], p['dest_db_name'], p['dest_username'], p['dest_password']),
                timeout=10,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT SERVERPROPERTY('ProductVersion')")
                    product_version = cur.fetchone()[0]
            major = int(product_version.split('.')[0])
            if major >= 15:
                return MSSQL_NEWEST_KNOWN_TARGET
            return MSSQL_VERSION_MAP.get(major, MSSQL_NEWEST_KNOWN_TARGET)
        except (pyodbc.Error, ValueError, IndexError) as e:
            if log_callback:
                log_callback('warn', f'Nie udało się wykryć VERSION serwera docelowego — {e}. Używam najnowszego znanego celu ({MSSQL_NEWEST_KNOWN_TARGET}).')
            return MSSQL_NEWEST_KNOWN_TARGET
```

- [ ] **Step 4: Run to verify pass, commit**

```bash
docker compose run --rm -v "$PWD/services/worker:/app" worker python -m pytest tests/test_mssql_handler.py -q
git add services/worker/modules/mssql/config.py services/worker/modules/mssql/handler.py services/worker/tests/test_mssql_handler.py
git commit -m "feat(mssql-transfer): target-server-version detection and mapping"
```

- [ ] **Step 5: Write failing tests for `mssql-scripter`/`sqlcmd` command building and the two-step execute**

```python
# services/worker/tests/test_mssql_handler.py (add)
class TestMssqlCommandBuilding:
    def _make_params(self, **kwargs):
        defaults = {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'srcpw',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'dstpw', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_builds_scripter_command_whole_db(self, tmp_path):
        handler = MssqlTransferHandler(self._make_params())
        cmd = handler._build_scripter_cmd(str(tmp_path / 'out.sql'), target_version='2019')
        assert cmd[0] == 'mssql-scripter'
        assert '--target-server-version' in cmd and '2019' in cmd
        assert '--include-objects' not in cmd

    def test_builds_scripter_command_single_table(self, tmp_path):
        handler = MssqlTransferHandler(self._make_params(table_name='users'))
        cmd = handler._build_scripter_cmd(str(tmp_path / 'out.sql'), target_version='2019')
        assert '--include-objects' in cmd
        assert cmd[cmd.index('--include-objects') + 1] == 'users'

    def test_builds_sqlcmd_command(self, tmp_path):
        handler = MssqlTransferHandler(self._make_params())
        cmd = handler._build_sqlcmd_cmd(str(tmp_path / 'out.sql'))
        assert cmd[0] == 'sqlcmd'
        assert 'dst' in cmd


class TestMssqlExecute:
    def _make_params(self):
        return {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'srcpw',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'dstpw', 'dest_db_name': 'dst', 'table_name': None, 'verify_row_count': False,
        }

    def _mock_proc(self, stdout_lines, exit_code):
        proc = MagicMock()
        proc.stdout = iter(stdout_lines)
        proc.wait.return_value = exit_code
        return proc

    def test_successful_transfer_and_temp_file_cleaned_up(self):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.MssqlTransferHandler._dest_target_server_version', return_value='2019'), \
             patch('modules.mssql.handler.subprocess.Popen') as MockPopen, \
             patch('modules.mssql.handler.os.path.exists', return_value=True), \
             patch('modules.mssql.handler.os.unlink') as mock_unlink:
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler.execute(log_callback=lambda lvl, msg: None)
            mock_unlink.assert_called_once()

    def test_password_passed_via_argv_documented_risk(self):
        # mssql-scripter/sqlcmd have no env-var password option — this test pins
        # the accepted, documented trade-off rather than silently assuming otherwise.
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.MssqlTransferHandler._dest_target_server_version', return_value='2019'), \
             patch('modules.mssql.handler.subprocess.Popen') as MockPopen, \
             patch('modules.mssql.handler.os.path.exists', return_value=False):
            MockPopen.side_effect = [self._mock_proc([], 0), self._mock_proc([], 0)]
            handler.execute(log_callback=lambda lvl, msg: None)
            all_args = [arg for call in MockPopen.call_args_list for arg in call.args[0]]
            assert 'srcpw' in all_args or 'dstpw' in all_args

    def test_retries_on_failure_then_raises(self):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.MssqlTransferHandler._dest_target_server_version', return_value='2019'), \
             patch('modules.mssql.handler.subprocess.Popen') as MockPopen, \
             patch('modules.mssql.handler.os.path.exists', return_value=False), \
             patch('modules.mssql.handler.time.sleep'):
            MockPopen.side_effect = [self._mock_proc([], 1), self._mock_proc([], 0)] * MSSQL_MAX_RETRIES
            with pytest.raises(MssqlTransferError):
                handler.execute(log_callback=lambda lvl, msg: None)
```

- [ ] **Step 6: Run to verify failure, then implement command building + execute**

```python
# services/worker/modules/mssql/handler.py — add methods
    def _build_scripter_cmd(self, out_path: str, target_version: str) -> list:
        p = self.params
        cmd = [
            'mssql-scripter', '-S', f'{p["source_host"]},{p["source_port"]}', '-d', p['source_db_name'],
            '-U', p['source_username'], '-P', p['source_password'],
            '--schema-and-data', '--target-server-version', target_version, '-f', out_path,
        ]
        if p.get('table_name'):
            cmd += ['--include-objects', p['table_name']]
        return cmd

    def _build_sqlcmd_cmd(self, in_path: str) -> list:
        p = self.params
        return [
            'sqlcmd', '-S', f'{p["dest_host"]},{p["dest_port"]}', '-d', p['dest_db_name'],
            '-U', p['dest_username'], '-P', p['dest_password'], '-i', in_path,
        ]

    def _run_step(self, cmd: list, log_callback: Callable[[str, str], None]) -> int:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)  # nosec B603 — cmd built from validated connection params
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log_callback('info', line)
        return proc.wait()

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        target_version = self._dest_target_server_version(log_callback)
        fd, tmp_path = tempfile.mkstemp(suffix='.sql')
        os.close(fd)
        try:
            last_scripter_exit = last_sqlcmd_exit = None
            for attempt in range(1, MSSQL_MAX_RETRIES + 1):
                log_callback('info', f'Starting mssql-scripter|sqlcmd (attempt {attempt})')
                last_scripter_exit = self._run_step(self._build_scripter_cmd(tmp_path, target_version), log_callback)
                if last_scripter_exit != 0:
                    if attempt < MSSQL_MAX_RETRIES:
                        log_callback('warn', f'mssql-scripter failed (exit {last_scripter_exit}), retrying in {MSSQL_RETRY_DELAY}s...')
                        time.sleep(MSSQL_RETRY_DELAY)
                    continue
                last_sqlcmd_exit = self._run_step(self._build_sqlcmd_cmd(tmp_path), log_callback)
                if last_sqlcmd_exit == 0:
                    log_callback('info', 'Transfer complete')
                    if self.params.get('verify_row_count'):
                        self._verify_row_counts(log_callback)
                    return
                if attempt < MSSQL_MAX_RETRIES:
                    log_callback('warn', f'sqlcmd failed (exit {last_sqlcmd_exit}), retrying in {MSSQL_RETRY_DELAY}s...')
                    time.sleep(MSSQL_RETRY_DELAY)

            raise MssqlTransferError(
                f'TRANSFER FAILED — mssql-scripter/sqlcmd failed after {MSSQL_MAX_RETRIES} attempts '
                f'(scripter exit={last_scripter_exit}, sqlcmd exit={last_sqlcmd_exit})'
            )
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
```

- [ ] **Step 7: Run to verify pass, commit**

```bash
docker compose run --rm -v "$PWD/services/worker:/app" worker python -m pytest tests/test_mssql_handler.py -q
git add services/worker/modules/mssql/handler.py services/worker/tests/test_mssql_handler.py
git commit -m "feat(mssql-transfer): scripter+sqlcmd two-step execution with retries"
```

- [ ] **Step 8: Write failing test for `_verify_row_counts`** (mirror Task 3's MySQL version, using `pyodbc`/`INFORMATION_SCHEMA.TABLES`)

```python
# services/worker/tests/test_mssql_handler.py (add)
class TestMssqlVerifyRowCounts:
    def _make_params(self):
        return {
            'source_host': 'a', 'source_port': 1433, 'source_username': 'sa', 'source_password': 'p',
            'source_db_name': 'src', 'dest_host': 'b', 'dest_port': 1433, 'dest_username': 'sa',
            'dest_password': 'p', 'dest_db_name': 'dst', 'table_name': 'users', 'verify_row_count': True,
        }

    def test_matching_counts_no_warn(self):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.pyodbc.connect') as mock_connect:
            cur = MagicMock()
            cur.fetchone.return_value = (7,)
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            logs = []
            handler._verify_row_counts(lambda lvl, msg: logs.append((lvl, msg)))
            assert not any(lvl == 'warn' for lvl, _ in logs)

    def test_mismatched_counts_warns(self):
        handler = MssqlTransferHandler(self._make_params())
        with patch('modules.mssql.handler.pyodbc.connect') as mock_connect:
            cur = MagicMock()
            cur.fetchone.side_effect = [(7,), (4,)]
            mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
            logs = []
            handler._verify_row_counts(lambda lvl, msg: logs.append((lvl, msg)))
            assert any(lvl == 'warn' for lvl, _ in logs)
```

- [ ] **Step 9: Run to verify failure, then implement**

```python
# services/worker/modules/mssql/handler.py — add method
    def _verify_row_counts(self, log_callback: Callable[[str, str], None]) -> None:
        p = self.params
        try:
            src_conn = pyodbc.connect(
                self._conn_string(p['source_host'], p['source_port'], p['source_db_name'], p['source_username'], p['source_password']),
                timeout=10,
            )
        except pyodbc.Error as e:
            log_callback('warn', f'ROW COUNT VERIFICATION SKIPPED — nie udało się połączyć ze źródłem: {e}')
            return
        try:
            dst_conn = pyodbc.connect(
                self._conn_string(p['dest_host'], p['dest_port'], p['dest_db_name'], p['dest_username'], p['dest_password']),
                timeout=10,
            )
        except pyodbc.Error as e:
            src_conn.close()
            log_callback('warn', f'ROW COUNT VERIFICATION SKIPPED — nie udało się połączyć z celem: {e}')
            return
        try:
            if p.get('table_name'):
                tables = [p['table_name']]
            else:
                with src_conn.cursor() as cur:
                    cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
                    tables = [row[0] for row in cur.fetchall()]
            for table in tables:
                with src_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM [{table}]')  # nosec B608 — table name from INFORMATION_SCHEMA/user-selected dropdown
                    src_count = cur.fetchone()[0]
                with dst_conn.cursor() as cur:
                    cur.execute(f'SELECT COUNT(*) FROM [{table}]')  # nosec B608
                    dst_count = cur.fetchone()[0]
                if src_count != dst_count:
                    log_callback('warn', f'ROW COUNT MISMATCH w "{table}": source={src_count} dest={dst_count}')
                else:
                    log_callback('info', f'ROW COUNT OK w "{table}": {src_count}')
        except pyodbc.Error as e:
            log_callback('warn', f'ROW COUNT VERIFICATION FAILED — {e}')
        finally:
            src_conn.close()
            dst_conn.close()
```

- [ ] **Step 10: Run full mssql handler suite, verify pass, commit**

```bash
docker compose run --rm -v "$PWD/services/worker:/app" worker python -m pytest tests/test_mssql_handler.py -q
git add services/worker/modules/mssql/handler.py services/worker/tests/test_mssql_handler.py
git commit -m "feat(mssql-transfer): row-count verification"
```

---

### Task 5: Web introspection — `mysql_utils.py` / `mssql_utils.py` + generalized `db_tables` endpoint

**Files:**
- Create: `services/web/apps/connections/mysql_utils.py`
- Create: `services/web/apps/connections/mssql_utils.py`
- Modify: `services/web/apps/connections/views.py`
- Modify: `services/web/apps/connections/urls.py`
- Modify: `services/web/templates/connections/_pg_tables_options.html` → rename to `_db_tables_options.html`
- Test: `services/web/apps/connections/tests/test_mysql_utils.py`
- Test: `services/web/apps/connections/tests/test_mssql_utils.py`
- Test: `services/web/apps/connections/tests/test_views.py`

**Interfaces:**
- Produces: `mysql_utils.list_tables(connection) -> list[str]`, `mssql_utils.list_tables(connection) -> list[str]` — same shape as `pg_utils.list_tables`.
- Produces: `connection_db_tables` view (renamed from `connection_pg_tables`), dispatching introspection by `connection.kind`, URL name `connections:db_tables` (keep `connections:pg_tables` as a deprecated alias only if any other template still references it — grep first).

- [ ] **Step 1: Write failing tests for `mysql_utils.list_tables`/`mssql_utils.list_tables`**

```python
# services/web/apps/connections/tests/test_mysql_utils.py
from unittest.mock import patch, MagicMock
from apps.connections.mysql_utils import list_tables


class _Conn:
    host = 'h'; port = 3306; username = 'u'; password = 'p'; db_name = 'd'


def test_returns_table_names():
    with patch('apps.connections.mysql_utils.pymysql.connect') as mock_connect:
        cur = MagicMock()
        cur.fetchall.return_value = [('users',), ('orders',)]
        mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
        assert list_tables(_Conn()) == ['users', 'orders']
```

```python
# services/web/apps/connections/tests/test_mssql_utils.py
from unittest.mock import patch, MagicMock
from apps.connections.mssql_utils import list_tables


class _Conn:
    host = 'h'; port = 1433; username = 'u'; password = 'p'; db_name = 'd'


def test_returns_table_names():
    with patch('apps.connections.mssql_utils.pyodbc.connect') as mock_connect:
        cur = MagicMock()
        cur.fetchall.return_value = [('users',), ('orders',)]
        mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = cur
        assert list_tables(_Conn()) == ['users', 'orders']
```

- [ ] **Step 2: Run to verify failure, then implement**

```python
# services/web/apps/connections/mysql_utils.py
import pymysql


def list_tables(connection) -> list:
    with pymysql.connect(
        host=connection.host, port=connection.port, user=connection.username,
        password=connection.password, database=connection.db_name, connect_timeout=10,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name',
                (connection.db_name,),
            )
            return [row[0] for row in cur.fetchall()]
```

```python
# services/web/apps/connections/mssql_utils.py
import pyodbc


def _conn_string(connection) -> str:
    return (
        f'DRIVER={{ODBC Driver 18 for SQL Server}};'
        f'SERVER={connection.host},{connection.port};DATABASE={connection.db_name};'
        f'UID={connection.username};PWD={connection.password};TrustServerCertificate=yes;'
    )


def list_tables(connection) -> list:
    conn = pyodbc.connect(_conn_string(connection), timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
```

- [ ] **Step 3: Run to verify pass, commit**

```bash
docker compose --profile test run --rm web-test python -m pytest apps/connections/tests/test_mysql_utils.py apps/connections/tests/test_mssql_utils.py -q
git add services/web/apps/connections/mysql_utils.py services/web/apps/connections/mssql_utils.py services/web/apps/connections/tests/test_mysql_utils.py services/web/apps/connections/tests/test_mssql_utils.py
git commit -m "feat(connections): mysql/mssql table introspection"
```

- [ ] **Step 4: Write failing test for the generalized `connection_db_tables` view**

```python
# services/web/apps/connections/tests/test_views.py (add)
@pytest.mark.django_db
class TestConnectionDbTablesDispatch:
    def test_mysql_connection_lists_via_mysql_utils(self, admin_client, make_connection, admin_user):
        conn = make_connection(admin_user, kind=KIND_MYSQL, db_name='d')
        with patch('apps.connections.views._list_mysql_tables', return_value=['a', 'b']):
            response = admin_client.get(reverse('connections:db_tables'), {'source_connection': conn.pk})
        assert b'a' in response.content and b'b' in response.content

    def test_mssql_connection_lists_via_mssql_utils(self, admin_client, make_connection, admin_user):
        conn = make_connection(admin_user, kind=KIND_MSSQL, db_name='d')
        with patch('apps.connections.views._list_mssql_tables', return_value=['x']):
            response = admin_client.get(reverse('connections:db_tables'), {'source_connection': conn.pk})
        assert b'x' in response.content
```

- [ ] **Step 5: Run to verify failure, then rename/generalize the view + URL + template**

```python
# services/web/apps/connections/views.py
from .mysql_utils import list_tables as _list_mysql_tables
from .mssql_utils import list_tables as _list_mssql_tables
from .models import KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL
import pymysql
import pyodbc

@require_role(ROLE_READONLY)
def connection_db_tables(request):
    raw_source_connection = request.GET.get('source_connection')
    tables = []
    error = None
    conn_id = None
    if raw_source_connection:
        try:
            conn_id = int(raw_source_connection)
        except ValueError:
            conn_id = None
    source_connection = conn_id
    if conn_id is not None:
        conn = Connection.objects.filter(
            pk=conn_id, kind__in=[KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL]
        ).first()
        if conn:
            try:
                if conn.kind == KIND_POSTGRES:
                    tables = _list_pg_tables(conn)
                elif conn.kind == KIND_MYSQL:
                    tables = _list_mysql_tables(conn)
                elif conn.kind == KIND_MSSQL:
                    tables = _list_mssql_tables(conn)
            except (psycopg2.Error, pymysql.Error, pyodbc.Error) as e:
                error = f'Błąd połączenia z bazą źródłową — {e}'.strip()
    return render(request, 'connections/_db_tables_options.html', {
        'tables': tables,
        'source_connection': source_connection,
        'error': error,
    })
```

Rename `services/web/templates/connections/_pg_tables_options.html` → `services/web/templates/connections/_db_tables_options.html` (content unchanged — it's already generic, just a `<select>` of table names).

```python
# services/web/apps/connections/urls.py — replace the pg-tables/ line
    path('db-tables/', views.connection_db_tables, name='db_tables'),
```

Before removing the old `connection_pg_tables` name entirely, grep for any other reference:

```bash
grep -rn "pg_tables\|connection_pg_tables\|_pg_tables_options" services/web/templates services/web/static services/web/apps --include='*.py' --include='*.html' --include='*.js'
```

Update every hit found (expected: `db_transfers/create.html`'s `data-pg-tables-url` attribute and `db_transfers_create.js`'s `dataset.pgTablesUrl` — both handled in Task 8, note them here so Task 8 doesn't miss them).

- [ ] **Step 6: Run to verify pass, commit**

```bash
docker compose --profile test run --rm web-test python -m pytest apps/connections/ -q
git add services/web/apps/connections/views.py services/web/apps/connections/urls.py services/web/apps/connections/tests/test_views.py "services/web/templates/connections/_db_tables_options.html"
git rm services/web/templates/connections/_pg_tables_options.html
git commit -m "feat(connections): generalize table introspection endpoint for mysql/mssql"
```

---

### Task 6: `tasks.py` — generic engine dispatch

**Files:**
- Modify: `services/worker/tasks.py`
- Test: `services/worker/tests/test_tasks.py`

**Interfaces:**
- Consumes: `MysqlTransferHandler`/`MysqlTransferError` (Task 3), `MssqlTransferHandler`/`MssqlTransferError` (Task 4), `DbTransferJob`/`DbTransferLog` (Task 2).
- Produces: `execute_db_transfer` task (renamed from `execute_pg_transfer`, same registered Celery name `db_transfers.execute` — **do not rename the Celery task name**, only the Python function, so no in-flight/scheduled task references break), `_build_db_transfer_params(job)` (renamed from `_build_pg_params`, unchanged shape).

- [ ] **Step 1: Write failing tests for engine dispatch**

```python
# services/worker/tests/test_tasks.py (add)
class TestExecuteDbTransferEngineDispatch:
    def _mock_job(self, MockJob, engine):
        mock_job = MagicMock()
        mock_job.engine = engine
        mock_job.pk = 1
        MockJob.objects.select_related.return_value.get.return_value = mock_job
        return mock_job

    def test_dispatches_to_mysql_handler(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog'), \
             patch('tasks.MysqlTransferHandler') as MockMysql:
            self._mock_job(MockJob, 'mysql')
            MockMysql.return_value.execute.return_value = None
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            MockMysql.assert_called_once()

    def test_dispatches_to_mssql_handler(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog'), \
             patch('tasks.MssqlTransferHandler') as MockMssql:
            self._mock_job(MockJob, 'mssql')
            MockMssql.return_value.execute.return_value = None
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            MockMssql.assert_called_once()

    def test_dispatches_to_postgres_handler_unchanged(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog'), \
             patch('tasks.PgTransferHandler') as MockPg:
            self._mock_job(MockJob, 'postgres')
            MockPg.return_value.execute.return_value = None
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            MockPg.assert_called_once()

    def test_mysql_error_marks_job_failed(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog'), \
             patch('tasks.MysqlTransferHandler') as MockMysql:
            from modules.mysql.handler import MysqlTransferError
            mock_job = self._mock_job(MockJob, 'mysql')
            MockMysql.return_value.execute.side_effect = MysqlTransferError('AUTH FAILED')
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('AUTH FAILED')

    def test_mssql_error_marks_job_failed(self):
        with patch('tasks.DbTransferJob') as MockJob, \
             patch('tasks.DbTransferLog'), \
             patch('tasks.MssqlTransferHandler') as MockMssql:
            from modules.mssql.handler import MssqlTransferError
            mock_job = self._mock_job(MockJob, 'mssql')
            MockMssql.return_value.execute.side_effect = MssqlTransferError('CONN FAILED')
            from tasks import execute_db_transfer
            execute_db_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('CONN FAILED')
```

- [ ] **Step 2: Run to verify failure**

Run: `docker compose run --rm -v "$PWD/services/worker:/app" worker python -m pytest tests/test_tasks.py -k TestExecuteDbTransferEngineDispatch -q`
Expected: `ImportError: cannot import name 'execute_db_transfer'`

- [ ] **Step 3: Rename and generalize in `tasks.py`**

```python
# services/worker/tasks.py — update imports
from apps.db_transfers.models import DbTransferJob, DbTransferLog  # noqa: E402
from modules.postgres.handler import PgTransferHandler, PgTransferError  # noqa: E402
from modules.mysql.handler import MysqlTransferHandler, MysqlTransferError  # noqa: E402
from modules.mssql.handler import MssqlTransferHandler, MssqlTransferError  # noqa: E402

_DB_TRANSFER_HANDLERS = {
    'postgres': (PgTransferHandler, PgTransferError),
    'mysql': (MysqlTransferHandler, MysqlTransferError),
    'mssql': (MssqlTransferHandler, MssqlTransferError),
}


def _build_db_transfer_params(job) -> dict:
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
def execute_db_transfer(self, job_id: int):
    try:
        job = DbTransferJob.objects.select_related('source_connection', 'dest_connection').get(pk=job_id)
    except DbTransferJob.DoesNotExist:
        logger.error(f'DbTransferJob {job_id} not found — task aborted')
        return

    job.mark_running(self.request.id)

    def log_callback(level: str, message: str):
        DbTransferLog.objects.create(job=job, level=level, message=message)

    handler_cls, error_cls = _DB_TRANSFER_HANDLERS[job.engine]
    try:
        params = _build_db_transfer_params(job)
        handler_cls(params).execute(log_callback=log_callback)
        job.mark_done()
    except error_cls as e:
        job.mark_failed(str(e))
        log_callback('error', str(e))
        logger.error(f'DbTransferJob {job.pk} failed: {e}')
    except Exception as e:
        job.mark_failed(f'UNEXPECTED ERROR — {e}')
        log_callback('error', f'UNEXPECTED ERROR — {e}')
        logger.error(f'DbTransferJob {job.pk} unexpected error: {e}')
        raise
```

Delete the old `_build_pg_params`/`execute_pg_transfer` functions (fully replaced, not kept alongside).

- [ ] **Step 4: Run to verify pass**

Run: `docker compose run --rm -v "$PWD/services/worker:/app" worker python -m pytest tests/test_tasks.py -q`
Expected: all pass, including the pre-existing Postgres dispatch tests (update their references from `execute_pg_transfer`/`PgTransferJob` to `execute_db_transfer`/`DbTransferJob` if they patch those names directly — grep `tests/test_tasks.py` for `execute_pg_transfer`/`PgTransferJob` first).

- [ ] **Step 5: Commit**

```bash
git add services/worker/tasks.py services/worker/tests/test_tasks.py
git commit -m "feat(tasks): dispatch db_transfers.execute by engine (postgres/mysql/mssql)"
```

---

### Task 7: Docker/dependencies infrastructure

**Files:**
- Modify: `services/worker/Dockerfile`
- Modify: `services/worker/requirements.txt`
- Modify: `services/web/requirements-prod.txt`
- Modify: `services/worker/tests/conftest.py` (stub the two new worker-side modules, mirroring existing stubs)

**Interfaces:**
- Produces: `mysqldump`/`mysql` CLI, `sqlcmd` CLI, `mssql-scripter` CLI, `pymysql`/`pyodbc` Python packages available in both `web` and `worker` images.

- [ ] **Step 1: Add MySQL client + Python packages (low risk, standard apt repo)**

```dockerfile
# services/worker/Dockerfile — extend the existing apt-get install line
RUN apt-get update && apt-get install -y --no-install-recommends \
    rsync openssh-client libpq-dev gcc gnupg postgresql-client default-mysql-client \
    && rm -rf /var/lib/apt/lists/*
```

```
# services/worker/requirements.txt — add
pymysql==1.1.*
```

```
# services/web/requirements-prod.txt — add
pymysql==1.1.*
```

- [ ] **Step 2: Add Microsoft's apt repository for `mssql-tools18`/`msodbcsql18`, then `pyodbc`/`mssql-scripter`**

```dockerfile
# services/worker/Dockerfile — add before the existing apt-get install line
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg2 apt-transport-https \
    && curl -sSL -o /usr/share/keyrings/microsoft-prod.gpg https://packages.microsoft.com/keys/microsoft.asc \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends mssql-tools18 unixodbc-dev unixodbc msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/opt/mssql-tools18/bin:${PATH}"
```

```
# services/worker/requirements.txt — add
pyodbc==5.*
```

```
# services/web/requirements-prod.txt — add
pyodbc==5.*
```

`mssql-scripter` is a Python package but has no active PyPI wheel guarantee for arbitrary future Python versions — pin it explicitly and verify the build succeeds:

```
# services/worker/requirements.txt — add
mssql-scripter==1.0.*
```

If `services/web/Dockerfile` needs the same ODBC driver for `pyodbc`-based introspection/testers (Task 1, Task 5) — check whether `web`'s Dockerfile installs system packages independently of `worker`'s:

```bash
diff services/web/Dockerfile services/worker/Dockerfile
```

Apply the same Microsoft-repo + `msodbcsql18`/`unixodbc-dev` block to `services/web/Dockerfile` if it doesn't already share a base image with `worker` (it doesn't — verify by inspecting `FROM` lines in both).

- [ ] **Step 3: Rebuild both images and confirm the new binaries/packages are present**

```bash
docker compose build web worker
docker compose run --rm worker mysqldump --version
docker compose run --rm worker sqlcmd -?
docker compose run --rm worker mssql-scripter --version
docker compose run --rm worker python -c "import pymysql, pyodbc; print('ok')"
docker compose run --rm web python -c "import pymysql, pyodbc; print('ok')"
```

Expected: all five commands succeed without error.

- [ ] **Step 4: Stub the new worker-side modules in `tests/conftest.py`** (mirrors existing `apps.db_transfers`/`apps.connections` stubs — needed because `tasks.py` imports `apps.db_transfers.models` at module level, and the worker's test sys.path doesn't include `services/web/`)

```python
# services/worker/tests/conftest.py — add alongside existing sys.modules.setdefault calls
sys.modules.setdefault('apps.db_transfers', MagicMock())
sys.modules.setdefault('apps.db_transfers.models', MagicMock())
```

(This line likely already exists from the original Postgres module — verify with `grep db_transfers services/worker/tests/conftest.py` before adding a duplicate.)

- [ ] **Step 5: Full regression, both suites**

```bash
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/ -q
docker compose build worker
docker compose run --rm worker python -m pytest tests/ -q
```

Expected: all pass. This is the checkpoint that catches any stale-image issue (see `feedback-docker-compose-run-stale-image` memory) — both images are explicitly rebuilt before running tests here, not just `run --rm`.

- [ ] **Step 6: Commit**

```bash
git add services/worker/Dockerfile services/worker/requirements.txt services/web/requirements-prod.txt services/web/Dockerfile services/worker/tests/conftest.py
git commit -m "build: add mysql/mssql client tools and Python drivers to worker+web images"
```

---

### Task 8: `db_transfers` app — form/view/template generalization

**Files:**
- Modify: `services/web/apps/db_transfers/forms.py` (rename `PgTransferForm` → `DbTransferForm`)
- Modify: `services/web/apps/db_transfers/views.py`
- Modify: `services/web/templates/db_transfers/create.html`
- Modify: `services/web/templates/db_transfers/list.html`
- Modify: `services/web/static/js/db_transfers_create.js`
- Test: `services/web/apps/db_transfers/tests/test_forms.py`
- Test: `services/web/apps/db_transfers/tests/test_views.py`

**Interfaces:**
- Produces: `DbTransferForm` — `source_connection`/`dest_connection` querysets filtered to the engine selected via a new `engine` form field (not model-bound directly; sets `job.engine` on save), `scope`/`table_name`/`verify_row_count` unchanged.
- Consumes: `connections:db_tables` URL name (Task 5), `DbTransferJob`/`DbTransferLog` (Task 2).

- [ ] **Step 1: Write failing tests for `DbTransferForm` engine-based connection filtering**

```python
# services/web/apps/db_transfers/tests/test_forms.py (add/replace existing PgTransferForm tests)
import pytest
from apps.db_transfers.forms import DbTransferForm
from apps.connections.models import KIND_MYSQL, KIND_MSSQL


@pytest.mark.django_db
class TestDbTransferFormEngineFiltering:
    def test_mysql_engine_only_offers_mysql_connections(self, regular_user, make_connection):
        mysql_conn = make_connection(regular_user, kind=KIND_MYSQL, db_name='a')
        mssql_conn = make_connection(regular_user, kind=KIND_MSSQL, db_name='b')
        form = DbTransferForm(user=regular_user, engine=KIND_MYSQL)
        qs_pks = set(form.fields['source_connection'].queryset.values_list('pk', flat=True))
        assert mysql_conn.pk in qs_pks
        assert mssql_conn.pk not in qs_pks

    def test_mismatched_source_dest_kind_invalid(self, regular_user, make_connection):
        mysql_conn = make_connection(regular_user, kind=KIND_MYSQL, db_name='a')
        mssql_conn = make_connection(regular_user, kind=KIND_MSSQL, db_name='b')
        form = DbTransferForm(
            {'source_connection': mysql_conn.pk, 'dest_connection': mssql_conn.pk, 'scope': 'whole_db'},
            user=regular_user, engine=KIND_MYSQL,
        )
        assert not form.is_valid()
```

- [ ] **Step 2: Run to verify failure, then implement**

```python
# services/web/apps/db_transfers/forms.py
from django import forms
from apps.connections.models import Connection
from .models import DbTransferJob


class DbTransferForm(forms.ModelForm):
    SCOPE_WHOLE_DB = 'whole_db'
    SCOPE_TABLE = 'table'
    SCOPE_CHOICES = [(SCOPE_WHOLE_DB, 'CAŁA BAZA'), (SCOPE_TABLE, 'POJEDYNCZA TABELA')]

    ENGINE_CHOICES = [('postgres', 'POSTGRES'), ('mysql', 'MYSQL'), ('mssql', 'MSSQL')]

    engine = forms.ChoiceField(choices=ENGINE_CHOICES, widget=forms.RadioSelect, initial='postgres')
    scope = forms.ChoiceField(choices=SCOPE_CHOICES, widget=forms.RadioSelect, initial=SCOPE_WHOLE_DB)

    class Meta:
        model = DbTransferJob
        fields = ['engine', 'source_connection', 'table_name', 'dest_connection', 'verify_row_count']
        labels = {'verify_row_count': 'Weryfikuj liczbę wierszy po transferze (COUNT)'}

    def __init__(self, *args, user=None, engine=None, **kwargs):
        super().__init__(*args, **kwargs)
        selected_engine = engine or (self.data.get('engine') if self.is_bound else None) or 'postgres'
        qs = Connection.objects.filter(kind=selected_engine)
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
        src = cleaned.get('source_connection')
        dst = cleaned.get('dest_connection')
        if src and dst and src.kind != dst.kind:
            raise forms.ValidationError('Źródło i cel muszą być tym samym silnikiem bazy danych.')
        return cleaned

    def save(self, commit=True):
        job = super().save(commit=False)
        job.engine = self.cleaned_data['source_connection'].kind
        if commit:
            job.save()
        return job
```

- [ ] **Step 3: Run to verify pass, commit**

```bash
docker compose --profile test run --rm web-test python -m pytest apps/db_transfers/tests/test_forms.py -q
git add services/web/apps/db_transfers/forms.py services/web/apps/db_transfers/tests/test_forms.py
git commit -m "feat(db-transfers): DbTransferForm with engine-based connection filtering"
```

- [ ] **Step 4: Update `views.py`** — mechanical rename of `PgTransferJob`/`PgTransferForm` references to `DbTransferJob`/`DbTransferForm`; pass `engine` from `request.GET`/`request.POST` into the form constructor on both GET (engine picker default) and POST

```python
# services/web/apps/db_transfers/views.py — key changes
from .models import DbTransferJob, STATUS_RUNNING, STATUS_PENDING
from .forms import DbTransferForm

@require_role(ROLE_READONLY)
def db_transfer_list(request):
    jobs = DbTransferJob.objects.all().select_related('source_connection', 'dest_connection')
    return render(request, 'db_transfers/list.html', {'jobs': jobs})


@require_role(ROLE_OPERATOR)
def db_transfer_create(request):
    engine = request.POST.get('engine') or request.GET.get('engine') or 'postgres'
    form = DbTransferForm(request.POST or None, user=request.user, engine=engine)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            job = form.save(commit=False)
            job.owner = request.user
            job.save()

            def _dispatch():
                result = current_app.send_task('db_transfers.execute', kwargs={'job_id': job.pk})
                DbTransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)
            transaction.on_commit(_dispatch)
        return redirect(DB_TRANSFERS_DETAIL, pk=job.pk)
    return render(request, 'db_transfers/create.html', {'form': form})
```

Apply the same `PgTransferJob` → `DbTransferJob` rename mechanically to `db_transfer_detail`, `log_fragment`, `db_transfer_stop`, `db_transfer_delete` (no other logic changes needed in those four).

- [ ] **Step 5: Update templates + JS** — add engine radio selector, wire connection dropdowns to reload on engine change, fix the introspection URL reference (Task 5's rename)

```html
<!-- services/web/templates/db_transfers/create.html — add engine selector, fix data attribute -->
<form method="post" id="db-transfer-form" data-db-tables-url="{% url 'connections:db_tables' %}">
  {% csrf_token %}
  ...
  {% for field in form %}
  {% if field.name == 'engine' %}
  <div class="field">
    <label>{{ field.label|upper }}:</label>
    {{ field }}
  </div>
  {% elif field.name == 'table_name' %}
  ...
```

```javascript
// services/web/static/js/db_transfers_create.js — rename data attribute reference
  const tablesUrl = form.dataset.dbTablesUrl;
```

Add an engine-change handler that reloads the page with `?engine=<value>` (simplest correct approach — reuses the existing server-side `Connection.objects.filter(kind=selected_engine)` queryset filtering in the form rather than duplicating that logic in JS):

```javascript
  const engineInputs = document.querySelectorAll('input[name="engine"]');
  engineInputs.forEach(function (input) {
    input.addEventListener('change', function () {
      window.location.href = window.location.pathname + '?engine=' + encodeURIComponent(input.value);
    });
  });
```

Add an `ENGINE` column to `services/web/templates/db_transfers/list.html`'s existing table (mirrors the `STATUS` column styling).

- [ ] **Step 6: Write/update view tests for engine-filtered create flow**

```python
# services/web/apps/db_transfers/tests/test_views.py (add)
@pytest.mark.django_db
class TestDbTransferCreateEngineSelection:
    def test_get_with_engine_param_filters_connection_choices(self, admin_client, admin_user, make_connection):
        mysql_conn = make_connection(admin_user, kind=KIND_MYSQL, db_name='a')
        response = admin_client.get(reverse('db_transfers:create'), {'engine': 'mysql'})
        assert response.context['form'].fields['source_connection'].queryset.filter(pk=mysql_conn.pk).exists()

    def test_post_creates_job_with_engine_from_source_connection(
        self, admin_client, admin_user, make_connection, mocker, django_capture_on_commit_callbacks,
    ):
        from types import SimpleNamespace
        mocker.patch('apps.db_transfers.views.current_app.send_task', return_value=SimpleNamespace(id='t1'))
        src = make_connection(admin_user, kind=KIND_MYSQL, db_name='a')
        dst = make_connection(admin_user, kind=KIND_MYSQL, db_name='b')
        with django_capture_on_commit_callbacks(execute=True):
            admin_client.post(reverse('db_transfers:create'), {
                'engine': 'mysql', 'source_connection': src.pk, 'dest_connection': dst.pk, 'scope': 'whole_db',
            })
        job = DbTransferJob.objects.get(source_connection=src)
        assert job.engine == 'mysql'
```

- [ ] **Step 7: Run full `db_transfers` + `connections` regression, commit**

```bash
docker compose --profile test run --rm web-test python -m pytest apps/db_transfers/ apps/connections/ -q
git add services/web/apps/db_transfers/views.py services/web/apps/db_transfers/tests/test_views.py \
        services/web/templates/db_transfers/create.html services/web/templates/db_transfers/list.html \
        services/web/static/js/db_transfers_create.js
git commit -m "feat(db-transfers): engine selector in create form, ENGINE column in list"
```

---

### Task 9: Full regression, live-stack verification, documentation

**Files:**
- No new source files — verification + vault documentation only.

- [ ] **Step 1: Full rebuild + full regression, both services**

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/ -q
docker compose build worker
docker compose run --rm worker python -m pytest tests/ -q
```

Expected: 0 failures on both. Record the new totals (web/worker test counts).

- [ ] **Step 2: Manual smoke test on the live stack**

```bash
docker compose build web worker
docker compose run --rm web python manage.py migrate
docker compose up -d --force-recreate web worker
```

In the browser: create a MySQL `Connection` (kind=MySQL), verify `[TEST CONNECTION]` and the DB NAME field appear correctly; create a `DbTransferJob` at `/db-transfers/new/` with engine=MySQL, confirm the table dropdown populates via the new `connections:db_tables` endpoint; repeat for MSSQL if a real MSSQL instance is reachable for manual testing, otherwise confirm the engine selector and form validation behave correctly even without a live server to test against (auth/connection failures should surface as clean error messages, not crashes).

- [ ] **Step 3: Vault documentation** (per this project's established workflow, `tmask-tt/CLAUDE.md`)

Update, in `/Users/dniemczok/Desktop/obsidian/11-Apps/CSCS/tmask-transporter/`:
- `Projekt-tmask-transporter-HISTORIA.md` — new entry for this feature (what was built, the GTID/collation/target-version compatibility mitigations, final test counts)
- `Projekt-tmask-transporter.md` — bump post-MVP feature count, update test count in "Testy" section
- `testy/Projekt-tmask-transporter-Testy.md` — overwrite "Aktualny stan", add one row to "Historia (trend)"
- Update `tmask-tt/CLAUDE.md` test-count comments (separate commit, as established)

- [ ] **Step 4: Final commit(s)**

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt && git add CLAUDE.md && git commit -m "docs: licznik testów po dodaniu MySQL/MSSQL transfer"
cd /Users/dniemczok/Desktop/obsidian && git add "11-Apps/CSCS/tmask-transporter/" && git commit -m "docs(tmask-transporter): MySQL/MSSQL database transfer support"
```

Per the standing project preference: merge the feature branch to `main` locally and do **not** push to `origin` without separate explicit confirmation (push triggers the production CI/CD deploy).
