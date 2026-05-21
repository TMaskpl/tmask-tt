# Relay Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-to-server relay transfer via a named `Flow` config (source SSH → worker buffer → dest SSH), with full CRUD UI and Scheduler integration, alongside the existing local→remote transfer mode.

**Architecture:** New `flows` Django app owns the `Flow` model. `TransferJob` and `ScheduledTransfer` get a nullable `flow` FK alongside the existing nullable `connection`. Worker gains `RelayHandler` (SFTP download + SFTP upload via BytesIO/tempfile). `execute_transfer` task dispatches to relay or single-server branch based on `job.flow_id`.

**Tech Stack:** Python 3.12, Django 5.x, Paramiko, Celery 5.x, pytest, HTMX, Docker Compose

**Run web tests from:** `services/web/`  
**Run worker tests from:** `services/worker/`  
**Web test command:** `docker compose exec web pytest`  
**Worker test command:** `docker compose exec worker pytest`

---

### Task 1: `flows` Django app — model + settings

**Files:**
- Create: `services/web/apps/flows/__init__.py`
- Create: `services/web/apps/flows/models.py`
- Create: `services/web/apps/flows/admin.py`
- Create: `services/web/apps/flows/tests/__init__.py`
- Create: `services/web/apps/flows/tests/test_models.py`
- Modify: `services/web/config/settings/base.py`

- [ ] **Step 1: Write the failing test**

Create `services/web/apps/flows/tests/__init__.py` (empty).

Create `services/web/apps/flows/tests/test_models.py`:

```python
import pytest
from django.core.exceptions import ValidationError
from apps.flows.models import Flow


@pytest.mark.django_db
class TestFlowModel:
    def test_create_flow(self, regular_user, make_connection):
        src = make_connection(regular_user, name='Source', host='10.0.0.1')
        dst = make_connection(regular_user, name='Dest', host='10.0.0.2')
        flow = Flow.objects.create(
            owner=regular_user,
            name='Daily Backup',
            source_conn=src,
            source_path='/data/file.tar',
            dest_conn=dst,
            dest_path='/backup/file.tar',
        )
        assert flow.pk is not None
        assert str(flow) == 'Daily Backup'

    def test_same_conn_same_path_invalid(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        flow = Flow(
            owner=regular_user,
            name='Bad',
            source_conn=conn,
            source_path='/same/path',
            dest_conn=conn,
            dest_path='/same/path',
        )
        with pytest.raises(ValidationError):
            flow.full_clean()

    def test_same_conn_different_path_valid(self, regular_user, make_connection):
        conn = make_connection(regular_user)
        flow = Flow(
            owner=regular_user,
            name='Local Copy',
            source_conn=conn,
            source_path='/data/file.tar',
            dest_conn=conn,
            dest_path='/backup/file.tar',
        )
        flow.full_clean()  # should not raise

    def test_owner_isolation(self, regular_user, admin_user, make_connection):
        src = make_connection(admin_user, name='Src', host='10.0.0.1')
        dst = make_connection(admin_user, name='Dst', host='10.0.0.2')
        Flow.objects.create(
            owner=admin_user, name='Admin Flow',
            source_conn=src, source_path='/x',
            dest_conn=dst, dest_path='/y',
        )
        assert Flow.objects.filter(owner=regular_user).count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec web pytest apps/flows/tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'apps.flows'`

- [ ] **Step 3: Create the `flows` app files**

Create `services/web/apps/flows/__init__.py` (empty file).

Create `services/web/apps/flows/models.py`:

```python
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.connections.models import Connection


class Flow(models.Model):
    owner       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='flows')
    name        = models.CharField(max_length=100)
    source_conn = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='source_flows')
    source_path = models.CharField(max_length=2000)
    dest_conn   = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='dest_flows')
    dest_path   = models.CharField(max_length=2000)
    created_at  = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.source_conn_id == self.dest_conn_id and self.source_path == self.dest_path:
            raise ValidationError('Source and destination cannot be the same file on the same server.')

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-created_at']
```

Create `services/web/apps/flows/admin.py`:

```python
from django.contrib import admin
from .models import Flow

admin.site.register(Flow)
```

- [ ] **Step 4: Register in INSTALLED_APPS**

In `services/web/config/settings/base.py`, add `'apps.flows'` after `'apps.scheduler'`:

```python
    'apps.accounts',
    'apps.connections',
    'apps.transfers',
    'apps.scheduler',
    'apps.flows',
```

- [ ] **Step 5: Generate and apply migration**

```bash
docker compose exec web python manage.py makemigrations flows
docker compose exec web python manage.py migrate
```

Expected: `Applying flows.0001_initial... OK`

- [ ] **Step 6: Run tests to verify they pass**

```bash
docker compose exec web pytest apps/flows/tests/test_models.py -v
```

Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add services/web/apps/flows/ services/web/config/settings/base.py
git commit -m "feat: add flows app with Flow model"
```

---

### Task 2: `TransferJob` — nullable `connection` + `flow` FK

**Files:**
- Modify: `services/web/apps/transfers/models.py`
- Create: `services/web/apps/transfers/migrations/0003_transferjob_flow.py` (via makemigrations)

- [ ] **Step 1: Write the failing test**

Add to `services/web/apps/transfers/tests/test_models.py`:

```python
@pytest.mark.django_db
class TestTransferJobFlowValidation:
    def test_flow_job_requires_no_connection(self, regular_user, make_connection, make_flow):
        flow = make_flow(regular_user)
        job = TransferJob.objects.create(
            owner=regular_user,
            flow=flow,
            source_path='/data/file.tar',
            destination_path='/backup/file.tar',
        )
        assert job.connection is None
        assert job.flow == flow

    def test_cannot_set_both_connection_and_flow(self, regular_user, make_connection, make_flow):
        from django.core.exceptions import ValidationError
        conn = make_connection(regular_user)
        flow = make_flow(regular_user)
        job = TransferJob(
            owner=regular_user,
            connection=conn,
            flow=flow,
            source_path='/x',
            destination_path='/y',
        )
        with pytest.raises(ValidationError):
            job.full_clean()

    def test_must_set_at_least_one(self, regular_user):
        from django.core.exceptions import ValidationError
        job = TransferJob(
            owner=regular_user,
            source_path='/x',
            destination_path='/y',
        )
        with pytest.raises(ValidationError):
            job.full_clean()
```

Add `make_flow` fixture to `services/web/conftest.py`:

```python
@pytest.fixture
def make_flow():
    from apps.flows.models import Flow
    from apps.connections.models import Connection
    def _make(user, **kwargs):
        src = Connection.objects.create(
            owner=user, name='FlowSrc', host='10.0.0.1', port=22,
            username='u', password='p', protocol='sftp',
        )
        dst = Connection.objects.create(
            owner=user, name='FlowDst', host='10.0.0.2', port=22,
            username='u', password='p', protocol='sftp',
        )
        defaults = dict(
            name='Test Flow',
            source_conn=src, source_path='/data/file.tar',
            dest_conn=dst,   dest_path='/backup/file.tar',
        )
        defaults.update(kwargs)
        return Flow.objects.create(owner=user, **defaults)
    return _make
```

- [ ] **Step 2: Run to verify it fails**

```bash
docker compose exec web pytest apps/transfers/tests/test_models.py::TestTransferJobFlowValidation -v
```

Expected: `AttributeError: type object 'TransferJob' has no attribute 'flow'`

- [ ] **Step 3: Modify `TransferJob`**

In `services/web/apps/transfers/models.py`, replace:

```python
    connection       = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='jobs'
    )
```

with:

```python
    connection       = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='jobs',
        null=True, blank=True,
    )
    flow             = models.ForeignKey(
        'flows.Flow', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='jobs',
    )
```

Add `clean()` method to `TransferJob` (before `mark_running`):

```python
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.connection_id and self.flow_id:
            raise ValidationError('Set connection or flow, not both.')
        if not self.connection_id and not self.flow_id:
            raise ValidationError('Set either connection or flow.')
```

- [ ] **Step 4: Generate and apply migration**

```bash
docker compose exec web python manage.py makemigrations transfers
docker compose exec web python manage.py migrate
```

Expected: `Applying transfers.0003_transferjob_flow... OK`

- [ ] **Step 5: Run tests to verify they pass**

```bash
docker compose exec web pytest apps/transfers/tests/ -v
```

Expected: all existing tests + 3 new tests pass (existing tests still use `connection=make_connection(...)` which is valid since connection is still optional-but-one-of)

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/transfers/ services/web/conftest.py
git commit -m "feat: TransferJob nullable connection + flow FK"
```

---

### Task 3: `ScheduledTransfer` — nullable `connection` + `flow` FK

**Files:**
- Modify: `services/web/apps/scheduler/models.py`
- Create: `services/web/apps/scheduler/migrations/0002_scheduledtransfer_flow.py` (via makemigrations)

- [ ] **Step 1: Write the failing test**

Add to `services/web/apps/scheduler/tests/test_models.py`:

```python
@pytest.mark.django_db
class TestScheduledTransferFlowValidation:
    def test_flow_schedule_requires_no_connection(self, regular_user, make_flow):
        flow = make_flow(regular_user)
        sched = ScheduledTransfer.objects.create(
            owner=regular_user,
            flow=flow,
            source_path='',
            destination_path='',
            cron_expr='0 3 * * *',
        )
        assert sched.connection is None
        assert sched.flow == flow
        assert str(sched) == 'Test Flow: 0 3 * * *'

    def test_cannot_set_both_connection_and_flow(self, regular_user, make_connection, make_flow):
        from django.core.exceptions import ValidationError
        sched = ScheduledTransfer(
            owner=regular_user,
            connection=make_connection(regular_user),
            flow=make_flow(regular_user),
            source_path='/x', destination_path='/y',
            cron_expr='0 3 * * *',
        )
        with pytest.raises(ValidationError):
            sched.full_clean()
```

Check what's in `services/web/apps/scheduler/tests/test_models.py` to see what imports are needed:

```bash
docker compose exec web cat apps/scheduler/tests/test_models.py
```

Add the `make_flow` fixture to the existing tests by importing it from conftest (pytest auto-discovers fixtures). Also add `ScheduledTransfer` import if missing at top of test file.

- [ ] **Step 2: Run to verify it fails**

```bash
docker compose exec web pytest apps/scheduler/tests/test_models.py::TestScheduledTransferFlowValidation -v
```

Expected: `AttributeError: type object 'ScheduledTransfer' has no attribute 'flow'`

- [ ] **Step 3: Modify `ScheduledTransfer`**

In `services/web/apps/scheduler/models.py`, replace:

```python
    connection       = models.ForeignKey(
        Connection, on_delete=models.CASCADE, related_name='schedules'
    )
    source_path      = models.CharField(max_length=2000)
    destination_path = models.CharField(max_length=2000)
```

with:

```python
    connection       = models.ForeignKey(
        Connection, on_delete=models.CASCADE, related_name='schedules',
        null=True, blank=True,
    )
    flow             = models.ForeignKey(
        'flows.Flow', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='schedules',
    )
    source_path      = models.CharField(max_length=2000, blank=True)
    destination_path = models.CharField(max_length=2000, blank=True)
```

Replace `__str__`:

```python
    def __str__(self) -> str:
        label = self.flow.name if self.flow_id else self.connection.name
        return f'{label}: {self.cron_expr}'
```

Add `clean()` before `__str__`:

```python
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.connection_id and self.flow_id:
            raise ValidationError('Set connection or flow, not both.')
        if not self.connection_id and not self.flow_id:
            raise ValidationError('Set either connection or flow.')
```

- [ ] **Step 4: Generate and apply migration**

```bash
docker compose exec web python manage.py makemigrations scheduler
docker compose exec web python manage.py migrate
```

Expected: `Applying scheduler.0002_scheduledtransfer_flow... OK`

- [ ] **Step 5: Run tests**

```bash
docker compose exec web pytest apps/scheduler/tests/ -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/scheduler/
git commit -m "feat: ScheduledTransfer nullable connection + flow FK"
```

---

### Task 4: `RelayHandler` worker module

**Files:**
- Create: `services/worker/modules/relay/__init__.py`
- Create: `services/worker/modules/relay/config.py`
- Create: `services/worker/modules/relay/handler.py`
- Create: `services/worker/tests/test_relay_handler.py`

- [ ] **Step 1: Write the failing tests**

Create `services/worker/tests/test_relay_handler.py`:

```python
import io
import os
import pytest
import paramiko
from unittest.mock import MagicMock, patch, call

from modules.relay.handler import RelayHandler, RelayTransferError


@pytest.fixture
def relay_params():
    source = {
        'host': '10.0.0.1', 'port': 22, 'username': 'src_user',
        'password': 'secret', 'ssh_key': None,
        'source_path': '/data/file.tar',
        'strict_host_key_checking': False, 'known_host_key': None,
    }
    dest = {
        'host': '10.0.0.2', 'port': 22, 'username': 'dst_user',
        'password': 'secret', 'ssh_key': None,
        'destination_path': '/backup/file.tar',
        'strict_host_key_checking': False, 'known_host_key': None,
    }
    return source, dest


class TestRelayHandler:
    def test_happy_path_small_file(self, relay_params):
        source_params, dest_params = relay_params
        fake_data = b'hello relay'

        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            mock_src_client = MagicMock()
            mock_dst_client = MagicMock()
            MockSSH.side_effect = [mock_src_client, mock_dst_client]

            mock_src_sftp = MagicMock()
            mock_dst_sftp = MagicMock()
            mock_src_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_src_sftp)
            mock_src_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            mock_dst_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_dst_sftp)
            mock_dst_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)

            mock_stat = MagicMock()
            mock_stat.st_size = 10
            mock_src_sftp.stat.return_value = mock_stat

            def fake_getfo(remote_path, buf):
                buf.write(fake_data)
            mock_src_sftp.getfo.side_effect = fake_getfo

            logs = []
            RelayHandler(source_params, dest_params).execute(log_callback=lambda l, m: logs.append((l, m)))

            mock_src_sftp.getfo.assert_called_once()
            mock_dst_sftp.putfo.assert_called_once()
            assert any('Transfer complete' in msg for _, msg in logs)

    def test_source_auth_failure_raises_source_error(self, relay_params):
        source_params, dest_params = relay_params
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            mock_src_client = MagicMock()
            MockSSH.return_value = mock_src_client
            mock_src_client.connect.side_effect = paramiko.AuthenticationException()
            with pytest.raises(RelayTransferError, match='SOURCE ERROR'):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda l, m: None)

    def test_dest_auth_failure_raises_dest_error(self, relay_params):
        source_params, dest_params = relay_params
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            mock_src_client = MagicMock()
            mock_dst_client = MagicMock()
            MockSSH.side_effect = [mock_src_client, mock_dst_client]

            mock_src_sftp = MagicMock()
            mock_src_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_src_sftp)
            mock_src_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            mock_stat = MagicMock()
            mock_stat.st_size = 5
            mock_src_sftp.stat.return_value = mock_stat
            mock_src_sftp.getfo.side_effect = lambda p, buf: buf.write(b'x')

            mock_dst_client.connect.side_effect = paramiko.AuthenticationException()
            with pytest.raises(RelayTransferError, match='DEST ERROR'):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda l, m: None)

    def test_source_file_not_found_raises_error(self, relay_params):
        source_params, dest_params = relay_params
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH:
            mock_src_client = MagicMock()
            MockSSH.return_value = mock_src_client
            mock_src_sftp = MagicMock()
            mock_src_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_src_sftp)
            mock_src_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            mock_src_sftp.stat.side_effect = FileNotFoundError('/data/file.tar')
            with pytest.raises(RelayTransferError, match='SOURCE ERROR — FILE NOT FOUND'):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda l, m: None)

    def test_tempfile_cleaned_up_on_dest_error(self, relay_params):
        source_params, dest_params = relay_params
        large_size = 200 * 1024 * 1024  # 200 MB — exceeds threshold

        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.tempfile.NamedTemporaryFile') as MockTmp, \
             patch('modules.relay.handler.os.path.exists', return_value=True) as mock_exists, \
             patch('modules.relay.handler.os.unlink') as mock_unlink:

            mock_src_client = MagicMock()
            mock_dst_client = MagicMock()
            MockSSH.side_effect = [mock_src_client, mock_dst_client]

            mock_src_sftp = MagicMock()
            mock_src_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_src_sftp)
            mock_src_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            mock_stat = MagicMock()
            mock_stat.st_size = large_size
            mock_src_sftp.stat.return_value = mock_stat

            fake_tmp = MagicMock()
            fake_tmp.name = '/tmp/relay_test_abc'
            MockTmp.return_value.__enter__ = MagicMock(return_value=fake_tmp)
            MockTmp.return_value.__exit__ = MagicMock(return_value=False)
            # NamedTemporaryFile is used as a context manager? No, we use it directly:
            MockTmp.return_value = fake_tmp

            mock_dst_client.connect.side_effect = paramiko.AuthenticationException()

            with pytest.raises(RelayTransferError):
                RelayHandler(source_params, dest_params).execute(log_callback=lambda l, m: None)

            mock_unlink.assert_called_once_with('/tmp/relay_test_abc')
```

- [ ] **Step 2: Run to verify it fails**

```bash
docker compose exec worker pytest tests/test_relay_handler.py -v
```

Expected: `ModuleNotFoundError: No module named 'modules.relay'`

- [ ] **Step 3: Implement the relay module**

Create `services/worker/modules/relay/__init__.py` (empty).

Create `services/worker/modules/relay/config.py`:

```python
RELAY_STREAM_THRESHOLD = 100 * 1024 * 1024  # 100 MB — files larger go to tempfile
RELAY_TEMP_DIR = None  # use system default
```

Create `services/worker/modules/relay/handler.py`:

```python
import io
import os
import tempfile

import paramiko

from .config import RELAY_STREAM_THRESHOLD, RELAY_TEMP_DIR


class RelayTransferError(Exception):
    pass


class RelayHandler:
    def __init__(self, source_params: dict, dest_params: dict):
        self.source_params = source_params
        self.dest_params = dest_params

    def _build_client(self, params: dict) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        if params.get('strict_host_key_checking') and params.get('known_host_key'):
            with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
                f.write(params['known_host_key'])
                tmp_path = f.name
            try:
                client.load_host_keys(tmp_path)
            finally:
                os.unlink(tmp_path)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return client

    def _connect(self, client: paramiko.SSHClient, params: dict) -> None:
        connect_kwargs = {
            'hostname': params['host'],
            'port': params['port'],
            'username': params['username'],
            'timeout': 30,
            'look_for_keys': False,
            'allow_agent': False,
        }
        if params.get('ssh_key'):
            connect_kwargs['pkey'] = paramiko.PKey.from_private_key(
                io.StringIO(params['ssh_key'])
            )
        elif params.get('password'):
            connect_kwargs['password'] = params['password']
        client.connect(**connect_kwargs)

    def execute(self, log_callback) -> None:
        buf = None
        tmp_path = None

        source_client = self._build_client(self.source_params)
        try:
            log_callback('info', f'SOURCE: Connecting to {self.source_params["host"]}:{self.source_params["port"]}')
            try:
                self._connect(source_client, self.source_params)
            except paramiko.AuthenticationException:
                raise RelayTransferError('SOURCE ERROR — AUTH FAILED')
            except Exception as e:
                raise RelayTransferError(f'SOURCE ERROR — {e}')

            log_callback('info', f'SOURCE: Downloading {self.source_params["source_path"]}')
            try:
                with source_client.open_sftp() as sftp:
                    try:
                        size = sftp.stat(self.source_params['source_path']).st_size or 0
                    except FileNotFoundError:
                        raise RelayTransferError(
                            f'SOURCE ERROR — FILE NOT FOUND: {self.source_params["source_path"]}'
                        )
                    if size > RELAY_STREAM_THRESHOLD:
                        tmp = tempfile.NamedTemporaryFile(delete=False, dir=RELAY_TEMP_DIR)
                        tmp_path = tmp.name
                        tmp.close()
                        sftp.get(self.source_params['source_path'], tmp_path)
                        log_callback('info', f'SOURCE: Downloaded {size} bytes to tempfile')
                    else:
                        buf = io.BytesIO()
                        sftp.getfo(self.source_params['source_path'], buf)
                        buf.seek(0)
                        log_callback('info', f'SOURCE: Downloaded {buf.getbuffer().nbytes} bytes to buffer')
            except RelayTransferError:
                raise
            except OSError as e:
                raise RelayTransferError(f'SOURCE ERROR — {e}')
        finally:
            source_client.close()

        dest_client = self._build_client(self.dest_params)
        try:
            log_callback('info', f'DEST: Connecting to {self.dest_params["host"]}:{self.dest_params["port"]}')
            try:
                self._connect(dest_client, self.dest_params)
            except paramiko.AuthenticationException:
                raise RelayTransferError('DEST ERROR — AUTH FAILED')
            except Exception as e:
                raise RelayTransferError(f'DEST ERROR — {e}')

            log_callback('info', f'DEST: Uploading to {self.dest_params["destination_path"]}')
            try:
                with dest_client.open_sftp() as sftp:
                    if tmp_path:
                        sftp.put(tmp_path, self.dest_params['destination_path'])
                    else:
                        sftp.putfo(buf, self.dest_params['destination_path'])
            except RelayTransferError:
                raise
            except OSError as e:
                raise RelayTransferError(f'DEST ERROR — {e}')

            log_callback('info', 'RELAY: Transfer complete')
        finally:
            dest_client.close()
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec worker pytest tests/test_relay_handler.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add services/worker/modules/relay/ services/worker/tests/test_relay_handler.py
git commit -m "feat: RelayHandler SFTP source→buffer→dest"
```

---

### Task 5: `tasks.py` — relay branch + scheduled execution

**Files:**
- Modify: `services/worker/tasks.py`
- Modify: `services/worker/tests/test_tasks.py`

- [ ] **Step 1: Write the failing tests**

Replace the full content of `services/worker/tests/test_tasks.py` with:

```python
import pytest
from unittest.mock import patch, MagicMock


class TestExecuteTransferTask:
    def test_dispatches_to_sftp_module(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            MockSFTP.assert_called_once()
            MockSFTP.return_value.execute.assert_called_once()
            mock_job.mark_done.assert_called_once()

    def test_marks_job_failed_on_sftp_error(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            from modules.sftp.handler import SFTPTransferError
            MockSFTP.return_value.execute.side_effect = SFTPTransferError('AUTH FAILED')
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('AUTH FAILED')

    def test_dispatches_to_rsync_module(self):
        with patch('tasks.RsyncHandler') as MockRsync, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'rsync'
            MockRsync.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            MockRsync.assert_called_once()
            MockRsync.return_value.execute.assert_called_once()

    def test_unexpected_exception_marks_failed_and_reraises(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            MockSFTP.return_value.execute.side_effect = RuntimeError('disk full')
            from tasks import execute_transfer
            with pytest.raises(RuntimeError):
                execute_transfer(job_id=1)
            assert 'UNEXPECTED ERROR' in mock_job.mark_failed.call_args[0][0]

    def test_dispatches_relay_handler_when_flow_set(self):
        with patch('tasks.RelayHandler') as MockRelay, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = 99
            MockRelay.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            MockRelay.assert_called_once()
            MockRelay.return_value.execute.assert_called_once()
            mock_job.mark_done.assert_called_once()

    def test_relay_error_marks_job_failed(self):
        with patch('tasks.RelayHandler') as MockRelay, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = 99
            from modules.relay.handler import RelayTransferError
            MockRelay.return_value.execute.side_effect = RelayTransferError('SOURCE ERROR — AUTH FAILED')
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('SOURCE ERROR — AUTH FAILED')

    def test_scheduled_id_creates_job_and_executes(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog, \
             patch('tasks._create_job_from_schedule') as MockCreate:
            mock_job = MagicMock()
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            MockCreate.return_value = mock_job
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=None, scheduled_id=5)
            MockCreate.assert_called_once_with(5)
            mock_job.mark_done.assert_called_once()

    def test_scheduled_id_skips_when_schedule_not_found(self):
        with patch('tasks._create_job_from_schedule') as MockCreate, \
             patch('tasks.TransferJob') as MockJob:
            MockCreate.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=None, scheduled_id=999)
            MockJob.objects.get.assert_not_called()


class TestCleanupOrphanJobs:
    def test_marks_old_running_jobs_as_failed(self):
        with patch('tasks.TransferJob') as MockJob:
            mock_qs = MagicMock()
            mock_qs.count.return_value = 2
            MockJob.objects.filter.return_value = mock_qs
            from tasks import cleanup_orphan_jobs
            cleanup_orphan_jobs()
            mock_qs.update.assert_called_once()
            call_kwargs = mock_qs.update.call_args[1]
            assert call_kwargs.get('status') == 'failed'
            assert 'TASK INTERRUPTED' in call_kwargs.get('error_message', '')
```

- [ ] **Step 2: Run to verify they fail**

```bash
docker compose exec worker pytest tests/test_tasks.py -v
```

Expected: existing tests fail (`flow_id` attribute not found), new tests fail (`RelayHandler` not imported in tasks)

- [ ] **Step 3: Rewrite `tasks.py`**

Replace `services/worker/tasks.py` with:

```python
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from celery import Celery
from celery.utils.log import get_task_logger
from apps.transfers.models import TransferJob, TransferLog
from modules.sftp.handler import SFTPHandler, SFTPTransferError
from modules.rsync.handler import RsyncHandler, RsyncTransferError
from modules.relay.handler import RelayHandler, RelayTransferError

app = Celery('transporter')
app.config_from_object('django.conf:settings', namespace='CELERY')

logger = get_task_logger(__name__)


def _build_params(job: TransferJob) -> dict:
    conn = job.connection
    return {
        'host': conn.host,
        'port': conn.port,
        'username': conn.username,
        'password': conn.password,
        'ssh_key': conn.ssh_key,
        'source_path': job.source_path,
        'destination_path': job.destination_path,
        'compress': conn.compress,
        'encrypt': conn.encrypt,
        'strict_host_key_checking': conn.strict_host_key_checking,
        'known_host_key': conn.known_host_key,
    }


def _build_relay_params(flow) -> tuple:
    def _conn_params(conn, source_path, destination_path):
        return {
            'host': conn.host,
            'port': conn.port,
            'username': conn.username,
            'password': conn.password,
            'ssh_key': conn.ssh_key,
            'source_path': source_path,
            'destination_path': destination_path,
            'strict_host_key_checking': conn.strict_host_key_checking,
            'known_host_key': conn.known_host_key,
        }
    source_params = _conn_params(flow.source_conn, flow.source_path, flow.source_path)
    dest_params = _conn_params(flow.dest_conn, flow.source_path, flow.dest_path)
    return source_params, dest_params


def _create_job_from_schedule(scheduled_id: int):
    from django.utils import timezone
    from apps.scheduler.models import ScheduledTransfer
    try:
        sched = ScheduledTransfer.objects.get(pk=scheduled_id, enabled=True)
    except ScheduledTransfer.DoesNotExist:
        logger.error(f'ScheduledTransfer {scheduled_id} not found or disabled — skipping')
        return None
    if sched.flow_id:
        job = TransferJob.objects.create(
            owner=sched.owner,
            flow=sched.flow,
            source_path=sched.flow.source_path,
            destination_path=sched.flow.dest_path,
        )
    else:
        job = TransferJob.objects.create(
            owner=sched.owner,
            connection=sched.connection,
            source_path=sched.source_path,
            destination_path=sched.destination_path,
        )
    sched.last_run = timezone.now()
    sched.save(update_fields=['last_run'])
    return job


@app.task(bind=True, name='transfers.execute')
def execute_transfer(self, job_id: int = None, scheduled_id: int = None):
    if job_id is None and scheduled_id is not None:
        job = _create_job_from_schedule(scheduled_id)
        if job is None:
            return
    else:
        try:
            job = TransferJob.objects.get(pk=job_id)
        except TransferJob.DoesNotExist:
            logger.error(f'TransferJob {job_id} not found — task aborted')
            return

    job.mark_running(self.request.id)

    def log_callback(level: str, message: str):
        TransferLog.objects.create(job=job, level=level, message=message)

    try:
        if job.flow_id:
            source_params, dest_params = _build_relay_params(job.flow)
            RelayHandler(source_params, dest_params).execute(log_callback=log_callback)
        else:
            params = _build_params(job)
            handler_cls = SFTPHandler if job.connection.protocol == 'sftp' else RsyncHandler
            handler_cls(params).execute(log_callback=log_callback)
        job.mark_done()
    except (SFTPTransferError, RsyncTransferError, RelayTransferError) as e:
        job.mark_failed(str(e))
        log_callback('error', str(e))
        logger.error(f'Transfer job {job.pk} failed: {e}')
    except Exception as e:
        job.mark_failed(f'UNEXPECTED ERROR — {e}')
        log_callback('error', f'UNEXPECTED ERROR — {e}')
        logger.error(f'Transfer job {job.pk} unexpected error: {e}')
        raise


@app.task(name='transfers.cleanup_orphans')
def cleanup_orphan_jobs():
    from django.utils import timezone
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(hours=1)
    orphans = TransferJob.objects.filter(status='running', started_at__lt=cutoff)
    count = orphans.count()
    orphans.update(status='failed', error_message='TASK INTERRUPTED — worker restarted')
    logger.info(f'Cleaned up {count} orphaned jobs')
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec worker pytest tests/test_tasks.py -v
```

Expected: 8 passed

- [ ] **Step 5: Restart worker to apply changes**

```bash
docker compose restart worker beat
```

- [ ] **Step 6: Commit**

```bash
git add services/worker/tasks.py services/worker/tests/test_tasks.py
git commit -m "feat: tasks.py relay branch + scheduled job creation"
```

---

### Task 6: Flows CRUD — views, forms, URLs, templates, tests

**Files:**
- Create: `services/web/apps/flows/forms.py`
- Create: `services/web/apps/flows/views.py`
- Create: `services/web/apps/flows/urls.py`
- Create: `services/web/apps/flows/tests/test_views.py`
- Create: `services/web/templates/flows/list.html`
- Create: `services/web/templates/flows/form.html`
- Modify: `services/web/config/urls.py`

- [ ] **Step 1: Write the failing tests**

Create `services/web/apps/flows/tests/test_views.py`:

```python
import pytest
from django.urls import reverse
from apps.flows.models import Flow
from apps.transfers.models import TransferJob, STATUS_PENDING


@pytest.mark.django_db
class TestFlowListView:
    def test_requires_login(self, client):
        response = client.get(reverse('flows:list'))
        assert response.status_code == 302
        assert '/accounts/login/' in response['Location']

    def test_shows_only_own_flows(self, auth_client, regular_user, admin_user, make_flow):
        make_flow(regular_user, name='My Flow')
        make_flow(admin_user, name='Other Flow')
        response = auth_client.get(reverse('flows:list'))
        assert response.status_code == 200
        assert b'My Flow' in response.content
        assert b'Other Flow' not in response.content


@pytest.mark.django_db
class TestFlowCreateView:
    def test_create_form_renders(self, auth_client):
        response = auth_client.get(reverse('flows:create'))
        assert response.status_code == 200

    def test_create_flow(self, auth_client, regular_user, make_connection):
        src = make_connection(regular_user, name='Src', host='10.0.0.1')
        dst = make_connection(regular_user, name='Dst', host='10.0.0.2')
        response = auth_client.post(reverse('flows:create'), {
            'name': 'New Flow',
            'source_conn': src.pk,
            'source_path': '/data/file.tar',
            'dest_conn': dst.pk,
            'dest_path': '/backup/file.tar',
        })
        assert response.status_code == 302
        assert Flow.objects.filter(owner=regular_user, name='New Flow').exists()

    def test_cannot_see_other_users_connections(self, auth_client, admin_user, make_connection):
        admin_conn = make_connection(admin_user, name='AdminConn')
        response = auth_client.get(reverse('flows:create'))
        assert response.status_code == 200
        assert b'AdminConn' not in response.content


@pytest.mark.django_db
class TestFlowRunView:
    def test_run_creates_transfer_job(self, auth_client, regular_user, make_flow, mocker):
        mock_delay = mocker.patch('apps.flows.views.execute_transfer.delay')
        flow = make_flow(regular_user)
        response = auth_client.post(reverse('flows:run', args=[flow.pk]))
        assert response.status_code == 302
        job = TransferJob.objects.get(owner=regular_user, flow=flow)
        assert job.status == STATUS_PENDING
        assert job.source_path == flow.source_path
        assert job.destination_path == flow.dest_path
        mock_delay.assert_called_once_with(job_id=job.pk)

    def test_run_requires_post(self, auth_client, regular_user, make_flow):
        flow = make_flow(regular_user)
        response = auth_client.get(reverse('flows:run', args=[flow.pk]))
        assert response.status_code == 405

    def test_cannot_run_other_users_flow(self, auth_client, admin_user, make_flow):
        flow = make_flow(admin_user)
        response = auth_client.post(reverse('flows:run', args=[flow.pk]))
        assert response.status_code == 404


@pytest.mark.django_db
class TestFlowDeleteView:
    def test_delete_removes_flow(self, auth_client, regular_user, make_flow):
        flow = make_flow(regular_user)
        response = auth_client.post(reverse('flows:delete', args=[flow.pk]))
        assert response.status_code == 302
        assert not Flow.objects.filter(pk=flow.pk).exists()

    def test_cannot_delete_other_users_flow(self, auth_client, admin_user, make_flow):
        flow = make_flow(admin_user)
        response = auth_client.post(reverse('flows:delete', args=[flow.pk]))
        assert response.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

```bash
docker compose exec web pytest apps/flows/tests/test_views.py -v
```

Expected: `NoReverseMatch: Reverse for 'flows:list' not found`

- [ ] **Step 3: Create `forms.py`**

Create `services/web/apps/flows/forms.py`:

```python
from django import forms
from apps.connections.models import Connection
from .models import Flow


class FlowForm(forms.ModelForm):
    class Meta:
        model = Flow
        fields = ['name', 'source_conn', 'source_path', 'dest_conn', 'dest_path']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            qs = Connection.objects.filter(owner=user)
            self.fields['source_conn'].queryset = qs
            self.fields['dest_conn'].queryset = qs
```

- [ ] **Step 4: Create `views.py`**

Create `services/web/apps/flows/views.py`:

```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from apps.transfers.models import TransferJob
from apps.transfers.tasks import execute_transfer
from .forms import FlowForm
from .models import Flow


@login_required
def flow_list(request):
    flows = Flow.objects.filter(owner=request.user).select_related('source_conn', 'dest_conn')
    return render(request, 'flows/list.html', {'flows': flows})


@login_required
def flow_create(request):
    form = FlowForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        flow = form.save(commit=False)
        flow.owner = request.user
        flow.save()
        return redirect('flows:list')
    return render(request, 'flows/form.html', {'form': form, 'action': 'CREATE'})


@login_required
def flow_edit(request, pk):
    flow = get_object_or_404(Flow, pk=pk, owner=request.user)
    form = FlowForm(request.POST or None, instance=flow, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('flows:list')
    return render(request, 'flows/form.html', {'form': form, 'action': 'EDIT', 'flow': flow})


@login_required
@require_POST
def flow_delete(request, pk):
    flow = get_object_or_404(Flow, pk=pk, owner=request.user)
    flow.delete()
    return redirect('flows:list')


@login_required
@require_POST
def flow_run(request, pk):
    flow = get_object_or_404(Flow, pk=pk, owner=request.user)
    job = TransferJob.objects.create(
        owner=request.user,
        flow=flow,
        source_path=flow.source_path,
        destination_path=flow.dest_path,
    )
    execute_transfer.delay(job_id=job.pk)
    return redirect('transfers:detail', pk=job.pk)
```

- [ ] **Step 5: Create `urls.py`**

Create `services/web/apps/flows/urls.py`:

```python
from django.urls import path
from . import views

app_name = 'flows'

urlpatterns = [
    path('', views.flow_list, name='list'),
    path('new/', views.flow_create, name='create'),
    path('<int:pk>/edit/', views.flow_edit, name='edit'),
    path('<int:pk>/delete/', views.flow_delete, name='delete'),
    path('<int:pk>/run/', views.flow_run, name='run'),
]
```

- [ ] **Step 6: Register URLs in `config/urls.py`**

In `services/web/config/urls.py`, add flows after connections:

```python
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('connections/', include('apps.connections.urls')),
    path('flows/', include('apps.flows.urls')),
    path('transfers/', include('apps.transfers.urls')),
    path('scheduler/', include('apps.scheduler.urls')),
    path('', RedirectView.as_view(url='/transfers/', permanent=False)),
]
```

- [ ] **Step 7: Create templates**

Create `services/web/templates/flows/list.html`:

```html
{% extends "base.html" %}
{% block title %}FLOWS — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">RELAY FLOWS</span>
  <div style="margin-bottom:1rem;">
    <a href="{% url 'flows:create' %}" class="btn">[ + NEW FLOW ]</a>
  </div>
  {% if flows %}
  <table>
    <thead>
      <tr>
        <th>NAME</th><th>SOURCE</th><th>SOURCE PATH</th>
        <th>DEST</th><th>DEST PATH</th><th>ACTIONS</th>
      </tr>
    </thead>
    <tbody>
      {% for flow in flows %}
      <tr>
        <td class="glow">{{ flow.name }}</td>
        <td>{{ flow.source_conn.name }}</td>
        <td>{{ flow.source_path }}</td>
        <td>{{ flow.dest_conn.name }}</td>
        <td>{{ flow.dest_path }}</td>
        <td>
          <form method="post" action="{% url 'flows:run' flow.pk %}" style="display:inline">
            {% csrf_token %}
            <button type="submit" class="btn btn-warn">[ RUN ]</button>
          </form>
          <a href="{% url 'flows:edit' flow.pk %}" class="btn">[ EDIT ]</a>
          <form method="post" action="{% url 'flows:delete' flow.pk %}" style="display:inline"
            onsubmit="return confirm('DELETE {{ flow.name }}?')">
            {% csrf_token %}
            <button type="submit" class="btn btn-danger">[ DEL ]</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color:#555;">NO FLOWS CONFIGURED — ADD ONE ABOVE</p>
  {% endif %}
</div>
{% endblock %}
```

Create `services/web/templates/flows/form.html`:

```html
{% extends "base.html" %}
{% block title %}{{ action }} FLOW — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="box" style="max-width:700px;">
  <span class="box-title">{{ action }} RELAY FLOW</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error">{% for e in form.non_field_errors %}> {{ e }}{% endfor %}</div>
    {% endif %}
    <div class="field">
      <label>NAME:</label>
      {{ form.name }}
      {% if form.name.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.name.errors }}</div>{% endif %}
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1rem;">
      <div>
        <span class="box-title" style="font-size:0.75rem;">SOURCE</span>
        <div class="field">
          <label>CONNECTION:</label>
          {{ form.source_conn }}
          {% if form.source_conn.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.source_conn.errors }}</div>{% endif %}
        </div>
        <div class="field">
          <label>PATH:</label>
          {{ form.source_path }}
          {% if form.source_path.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.source_path.errors }}</div>{% endif %}
        </div>
      </div>
      <div>
        <span class="box-title" style="font-size:0.75rem;">DESTINATION</span>
        <div class="field">
          <label>CONNECTION:</label>
          {{ form.dest_conn }}
          {% if form.dest_conn.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.dest_conn.errors }}</div>{% endif %}
        </div>
        <div class="field">
          <label>PATH:</label>
          {{ form.dest_path }}
          {% if form.dest_path.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.dest_path.errors }}</div>{% endif %}
        </div>
      </div>
    </div>
    <div style="display:flex;gap:1rem;margin-top:1.5rem;">
      <button type="submit" class="btn">[ SAVE FLOW ]</button>
      <a href="{% url 'flows:list' %}" class="btn btn-danger">[ CANCEL ]</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
docker compose exec web pytest apps/flows/tests/ -v
```

Expected: 10 passed

- [ ] **Step 9: Commit**

```bash
git add services/web/apps/flows/ services/web/config/urls.py services/web/templates/flows/
git commit -m "feat: flows CRUD views, forms, URLs, templates"
```

---

### Task 7: Nav + logs/detail template updates

**Files:**
- Modify: `services/web/templates/base.html`
- Modify: `services/web/templates/logs/list.html`
- Modify: `services/web/templates/transfers/create.html`

- [ ] **Step 1: Add Flows link to nav in `base.html`**

In `services/web/templates/base.html`, replace:

```html
    <a href="{% url 'connections:list' %}" class="{% if request.resolver_match.app_name == 'connections' %}active{% endif %}">CONNECTIONS</a>
    <a href="{% url 'scheduler:list' %}" class="{% if request.resolver_match.app_name == 'scheduler' %}active{% endif %}">SCHEDULER</a>
```

with:

```html
    <a href="{% url 'connections:list' %}" class="{% if request.resolver_match.app_name == 'connections' %}active{% endif %}">CONNECTIONS</a>
    <a href="{% url 'flows:list' %}" class="{% if request.resolver_match.app_name == 'flows' %}active{% endif %}">FLOWS</a>
    <a href="{% url 'scheduler:list' %}" class="{% if request.resolver_match.app_name == 'scheduler' %}active{% endif %}">SCHEDULER</a>
```

- [ ] **Step 2: Fix `logs/list.html` — guard nullable connection**

Replace the entire `services/web/templates/logs/list.html`:

```html
{% extends "base.html" %}
{% block title %}LOGS — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">TRANSFER HISTORY</span>
  {% if jobs %}
  <table>
    <thead>
      <tr>
        <th>#</th><th>TYPE</th><th>SOURCE</th><th>DEST</th>
        <th>STATUS</th><th>STARTED</th><th>FINISHED</th><th>ACTIONS</th>
      </tr>
    </thead>
    <tbody>
      {% for job in jobs %}
      <tr>
        <td>{{ job.pk }}</td>
        <td>
          {% if job.flow %}
            <span style="color:var(--green-bright);">RELAY</span><br>
            <span style="font-size:0.75rem;color:#aaa;">{{ job.flow.name }}</span>
          {% else %}
            LOCAL→REMOTE<br>
            <span style="font-size:0.75rem;color:#aaa;">{{ job.connection.name }}</span>
          {% endif %}
        </td>
        <td>{{ job.source_path }}</td>
        <td>{{ job.destination_path }}</td>
        <td><span class="status status-{{ job.status }}">{{ job.status|upper }}</span></td>
        <td>{{ job.started_at|date:"Y-m-d H:i"|default:"—" }}</td>
        <td>{{ job.finished_at|date:"Y-m-d H:i"|default:"—" }}</td>
        <td><a href="{% url 'transfers:detail' job.pk %}" class="btn">[VIEW]</a></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color:#555;">NO TRANSFER HISTORY</p>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 3: Update `transfers/create.html` — show flow info in detail view**

Replace `services/web/templates/transfers/create.html`:

```html
{% extends "base.html" %}
{% block title %}TRANSFER — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div style="display:grid; grid-template-columns:1fr 1fr; gap:2rem;">
  <div class="box">
    <span class="box-title">NEW TRANSFER</span>
    <form method="post">
      {% csrf_token %}
      {% for field in form %}
      <div class="field">
        <label>{{ field.label|upper }}:</label>
        {{ field }}
        {% if field.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ field.errors }}</div>{% endif %}
      </div>
      {% endfor %}
      <button type="submit" class="btn">[ EXECUTE TRANSFER ]</button>
    </form>
    <div style="margin-top:1.5rem;border-top:1px solid #333;padding-top:1rem;">
      <span style="color:#555;font-size:0.8rem;">RELAY TRANSFER? USE <a href="{% url 'flows:list' %}" style="color:var(--green);">FLOWS</a></span>
    </div>
  </div>

  {% if job %}
  <div class="box">
    {% if job.flow %}
    <span class="box-title">RELAY FLOW LOG — #{{ job.pk }}</span>
    <div style="margin-bottom:0.5rem;font-size:0.85rem;">
      <div>FLOW: <span class="glow">{{ job.flow.name }}</span></div>
      <div>SOURCE: {{ job.flow.source_conn.name }} → {{ job.source_path }}</div>
      <div>DEST:&nbsp;&nbsp; {{ job.flow.dest_conn.name }} → {{ job.destination_path }}</div>
    </div>
    {% else %}
    <span class="box-title">TRANSFER LOG — #{{ job.pk }}</span>
    {% endif %}
    <div style="margin-bottom:0.5rem;">
      STATUS: <span class="status status-{{ job.status }}">{{ job.status|upper }}</span>
    </div>
    <div
      id="log-output"
      class="log-terminal"
      {% if job.status == 'running' or job.status == 'pending' %}
        hx-get="{% url 'transfers:log_fragment' job.pk %}"
        hx-trigger="every 2s"
        hx-swap="innerHTML"
      {% endif %}
    >
      {% include "transfers/log_fragment.html" with logs=job.logs.all %}
    </div>
  </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 4: Update `transfer_logs` view to select_related flow**

In `services/web/apps/transfers/views.py`, replace:

```python
    jobs = TransferJob.objects.filter(owner=request.user).select_related('connection')
```

with:

```python
    jobs = TransferJob.objects.filter(owner=request.user).select_related('connection', 'flow')
```

- [ ] **Step 5: Rebuild web container and verify in browser**

```bash
docker compose build web && docker compose up -d web
```

Navigate to `http://localhost/` — verify "FLOWS" appears in the nav between CONNECTIONS and SCHEDULER.

- [ ] **Step 6: Commit**

```bash
git add services/web/templates/ services/web/apps/transfers/views.py
git commit -m "feat: nav flows link, logs type column, transfer detail flow info"
```

---

### Task 8: Scheduler form + view + template updates

**Files:**
- Modify: `services/web/apps/scheduler/forms.py`
- Modify: `services/web/apps/scheduler/views.py`
- Modify: `services/web/templates/scheduler/list.html`
- Modify: `services/web/templates/scheduler/form.html`

- [ ] **Step 1: Write the failing tests**

Add to `services/web/apps/scheduler/tests/test_models.py` (append at end):

```python
@pytest.mark.django_db
class TestSchedulerFlowFormValidation:
    def test_form_accepts_flow_without_paths(self, regular_user, make_flow):
        from apps.scheduler.forms import ScheduledTransferForm
        flow = make_flow(regular_user)
        form = ScheduledTransferForm(data={
            'flow': flow.pk,
            'source_path': '',
            'destination_path': '',
            'cron_expr': '0 3 * * *',
            'enabled': True,
        }, user=regular_user)
        assert form.is_valid(), form.errors

    def test_form_rejects_both_connection_and_flow(self, regular_user, make_connection, make_flow):
        from apps.scheduler.forms import ScheduledTransferForm
        conn = make_connection(regular_user)
        flow = make_flow(regular_user)
        form = ScheduledTransferForm(data={
            'connection': conn.pk,
            'flow': flow.pk,
            'source_path': '/x',
            'destination_path': '/y',
            'cron_expr': '0 3 * * *',
            'enabled': True,
        }, user=regular_user)
        assert not form.is_valid()
        assert '__all__' in form.errors

    def test_form_rejects_connection_without_paths(self, regular_user, make_connection):
        from apps.scheduler.forms import ScheduledTransferForm
        conn = make_connection(regular_user)
        form = ScheduledTransferForm(data={
            'connection': conn.pk,
            'source_path': '',
            'destination_path': '',
            'cron_expr': '0 3 * * *',
            'enabled': True,
        }, user=regular_user)
        assert not form.is_valid()
```

- [ ] **Step 2: Run to verify they fail**

```bash
docker compose exec web pytest apps/scheduler/tests/test_models.py::TestSchedulerFlowFormValidation -v
```

Expected: tests fail (form has no `flow` field)

- [ ] **Step 3: Update `scheduler/forms.py`**

Replace `services/web/apps/scheduler/forms.py`:

```python
from django import forms

from apps.connections.models import Connection
from apps.flows.models import Flow
from .models import ScheduledTransfer


class ScheduledTransferForm(forms.ModelForm):
    class Meta:
        model = ScheduledTransfer
        fields = ['connection', 'flow', 'source_path', 'destination_path', 'cron_expr', 'enabled']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['connection'].queryset = Connection.objects.filter(owner=user)
            self.fields['flow'].queryset = Flow.objects.filter(owner=user)
        self.fields['connection'].required = False
        self.fields['flow'].required = False
        self.fields['source_path'].required = False
        self.fields['destination_path'].required = False

    def clean_cron_expr(self):
        expr = self.cleaned_data['cron_expr']
        parts = expr.split()
        if len(parts) != 5:
            raise forms.ValidationError('INVALID CRON — format: "min hour day month weekday" (5 fields)')
        return expr

    def clean(self):
        cleaned = super().clean()
        connection = cleaned.get('connection')
        flow = cleaned.get('flow')
        source_path = cleaned.get('source_path', '')
        destination_path = cleaned.get('destination_path', '')

        if connection and flow:
            raise forms.ValidationError('Set connection or flow, not both.')
        if not connection and not flow:
            raise forms.ValidationError('Set either connection or flow.')
        if connection and not source_path:
            raise forms.ValidationError('Source path is required for connection-based schedules.')
        if connection and not destination_path:
            raise forms.ValidationError('Destination path is required for connection-based schedules.')
        return cleaned
```

- [ ] **Step 4: Update `scheduler/views.py` — handle flow schedules**

In `services/web/apps/scheduler/views.py`, replace `schedule_list`:

```python
@login_required
def schedule_list(request):
    schedules = ScheduledTransfer.objects.filter(owner=request.user).select_related('connection', 'flow')
    return render(request, 'scheduler/list.html', {'schedules': schedules})
```

- [ ] **Step 5: Update `scheduler/list.html`**

Replace `services/web/templates/scheduler/list.html`:

```html
{% extends "base.html" %}
{% block title %}SCHEDULER{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">SCHEDULED TRANSFERS</span>
  <div style="margin-bottom:1rem;">
    <a href="{% url 'scheduler:create' %}" class="btn">[ + NEW SCHEDULE ]</a>
  </div>
  {% if schedules %}
  <table>
    <thead>
      <tr><th>TYPE</th><th>SOURCE</th><th>DESTINATION</th><th>CRON</th><th>LAST RUN</th><th>STATUS</th><th>ACTIONS</th></tr>
    </thead>
    <tbody>
      {% for s in schedules %}
      <tr>
        {% if s.flow %}
        <td class="glow">RELAY: {{ s.flow.name }}</td>
        <td>{{ s.flow.source_conn.name }}:{{ s.flow.source_path }}</td>
        <td>{{ s.flow.dest_conn.name }}:{{ s.flow.dest_path }}</td>
        {% else %}
        <td class="glow">{{ s.connection.name }}</td>
        <td>{{ s.source_path }}</td>
        <td>{{ s.destination_path }}</td>
        {% endif %}
        <td>{{ s.cron_expr }}</td>
        <td>{{ s.last_run|date:"Y-m-d H:i"|default:"—" }}</td>
        <td>{% if s.enabled %}<span style="color:var(--green-bright);">● ACTIVE</span>{% else %}<span style="color:#555;">○ PAUSED</span>{% endif %}</td>
        <td>
          <form method="post" action="{% url 'scheduler:toggle' s.pk %}" style="display:inline">{% csrf_token %}
            <button type="submit" class="btn btn-warn">{% if s.enabled %}[PAUSE]{% else %}[RESUME]{% endif %}</button>
          </form>
          <a href="{% url 'scheduler:edit' s.pk %}" class="btn">[EDIT]</a>
          <form method="post" action="{% url 'scheduler:delete' s.pk %}" style="display:inline"
            onsubmit="return confirm('DELETE schedule?')">{% csrf_token %}
            <button type="submit" class="btn btn-danger">[DEL]</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color:#555;">NO SCHEDULES — ADD ONE ABOVE</p>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 6: Update `scheduler/form.html`**

Replace `services/web/templates/scheduler/form.html`:

```html
{% extends "base.html" %}
{% block title %}{{ action }} SCHEDULE{% endblock %}
{% block content %}
<div class="box" style="max-width:600px;">
  <span class="box-title">{{ action }} SCHEDULE</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error">{% for e in form.non_field_errors %}> {{ e }}{% endfor %}</div>
    {% endif %}

    <div style="margin-bottom:1rem;">
      <label style="margin-right:1rem;">
        <input type="radio" name="sched_type" value="connection"
          {% if not form.instance.flow_id %}checked{% endif %}
          onchange="document.getElementById('conn-fields').style.display='';document.getElementById('flow-fields').style.display='none';">
        CONNECTION
      </label>
      <label>
        <input type="radio" name="sched_type" value="flow"
          {% if form.instance.flow_id %}checked{% endif %}
          onchange="document.getElementById('conn-fields').style.display='none';document.getElementById('flow-fields').style.display='';">
        RELAY FLOW
      </label>
    </div>

    <div id="conn-fields" {% if form.instance.flow_id %}style="display:none"{% endif %}>
      <div class="field">
        <label>CONNECTION:</label>
        {{ form.connection }}
        {% if form.connection.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.connection.errors }}</div>{% endif %}
      </div>
      <div class="field">
        <label>SOURCE PATH:</label>
        {{ form.source_path }}
        {% if form.source_path.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.source_path.errors }}</div>{% endif %}
      </div>
      <div class="field">
        <label>DESTINATION PATH:</label>
        {{ form.destination_path }}
        {% if form.destination_path.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.destination_path.errors }}</div>{% endif %}
      </div>
    </div>

    <div id="flow-fields" {% if not form.instance.flow_id %}style="display:none"{% endif %}>
      <div class="field">
        <label>FLOW:</label>
        {{ form.flow }}
        {% if form.flow.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.flow.errors }}</div>{% endif %}
      </div>
    </div>

    <div class="field">
      <label>CRON EXPR:</label>
      {{ form.cron_expr }}
      {% if form.cron_expr.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.cron_expr.errors }}</div>{% endif %}
    </div>
    <div class="field">
      <label>ENABLED:</label>
      {{ form.enabled }}
    </div>
    <p style="color:#555; font-size:0.8rem; margin-bottom:1rem;">CRON FORMAT: "min hour day month weekday" — e.g. "0 3 * * *" = daily at 03:00</p>
    <div style="display:flex;gap:1rem;">
      <button type="submit" class="btn">[ SAVE ]</button>
      <a href="{% url 'scheduler:list' %}" class="btn btn-danger">[ CANCEL ]</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: Run all scheduler tests**

```bash
docker compose exec web pytest apps/scheduler/tests/ -v
```

Expected: all pass

- [ ] **Step 8: Run full test suite to check for regressions**

```bash
docker compose exec web pytest -v
docker compose exec worker pytest -v
```

Expected: all web + worker tests pass (59+ existing + new)

- [ ] **Step 9: Rebuild containers and do a manual smoke test**

```bash
docker compose build web worker && docker compose up -d
```

1. Navigate to `http://localhost/flows/` — Flows list visible in nav
2. Create two Connections (different hosts)
3. Create a Flow (source conn + path, dest conn + path)
4. Click `[RUN]` on the flow → redirected to Transfer Log showing `RELAY FLOW LOG`
5. Navigate to `http://localhost/transfers/logs/` — job shows `RELAY` type with flow name
6. Navigate to `http://localhost/scheduler/new/` — toggle between Connection and Relay Flow

- [ ] **Step 10: Commit**

```bash
git add services/web/apps/scheduler/ services/web/templates/scheduler/
git commit -m "feat: scheduler Connection/Flow toggle with form validation"
```

---

### Task 9: Final integration commit

- [ ] **Step 1: Run complete test suite one last time**

```bash
docker compose exec web pytest -v --tb=short
docker compose exec worker pytest -v --tb=short
```

Expected: all tests pass, 0 failures

- [ ] **Step 2: Final commit**

```bash
git add .
git commit -m "$(cat <<'EOF'
feat: relay flows — server-to-server transfer via worker intermediary

- New `flows` app: Flow model (source conn + path → dest conn + path)
- RelayHandler: SFTP download → BytesIO/tempfile → SFTP upload
- TransferJob + ScheduledTransfer: nullable connection + flow FK
- Scheduler: Connection/Flow toggle with validation
- Transfer logs: TYPE column (LOCAL→REMOTE vs RELAY)
- Transfer detail: shows flow source/dest info
- Nav: FLOWS link between CONNECTIONS and SCHEDULER
- tasks.py: relay branch + _create_job_from_schedule for Beat triggers

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```
