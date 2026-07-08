# Podgląd dry-run rsync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Przycisk `[DRY RUN]` na formularzu New Transfer pokazuje output `rsync --dry-run` przed wykonaniem prawdziwego transferu (roadmap #5).

**Architecture:** Nowa metoda `RsyncHandler.preview()` (worker) wydzielona z istniejącej logiki dry-run w `execute()`. Nowy, bezstanowy task Celery `transfers.dry_run_preview` buduje parametry z `Connection` + jawnych ścieżek (bez `TransferJob`). Web dispatchuje task i polluje wynik przez `AsyncResult` (już skonfigurowany `CELERY_RESULT_BACKEND='django-db'`) — zero nowego modelu.

**Tech Stack:** Python 3.12, Django 5.x, Celery, pytest, HTMX (polling przez `hx-trigger="every Ns"`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-08-dry-run-preview-design.md` — wszystkie decyzje projektowe stamtąd obowiązują (m.in. preview NIE tworzy `TransferJob`, NIE rzuca wyjątku przy niezerowym exit code, dopisuje ostrzeżenie host-key na początek `output`, dwa niezależne submity `[DRY RUN]`/`[TRANSFER]` bez reużycia pliku).
- Praca na gałęzi `feat/dry-run-preview` (już utworzona, spec zacommitowany na `main` w `6ef853f`).
- Polecenia uruchamiać z katalogu projektu: `/Users/dniemczok/Desktop/TMaskPL/tmask-tt`.
- **Bezpieczeństwo danych:** `postgres`/`redis`/`web`/`worker`/`beat`/`nginx` to żywe kontenery produkcyjne. Testy web korzystają z efemerycznej bazy pytest-django (bezpieczne). Testy worker i web NIE MOGĄ dotykać realnego zamontowanego `/transfers` — worker przez `tmp_path`+`patch('tasks.settings.TRANSFERS_DIR', ...)`, web przez pytest-django `settings` fixture (`settings.TRANSFERS_DIR = str(tmp_path)`) + `tmp_path`.
- **TDD dev-loop:** worker `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/ -v`, web `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/ -v`.
- **Weryfikacja końcowa (rebuild, jak CI):** `docker compose build worker && docker compose run --rm worker python -m pytest tests/ -v` oraz `docker compose --profile test build web-test && docker compose --profile test run --rm web-test python -m pytest apps/ -v`.
- Commity: prefiks `feat:`/`test:`, opis po polsku, stopka `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Mockowanie w testach rsync handlera: `patch('modules.rsync.handler.subprocess.Popen', ...)` (fake process z `.stdout`/`.wait()`) — **nie** mockować `_run_attempt` bezpośrednio, zgodnie z istniejącym wzorcem w `services/worker/tests/test_rsync_handler.py`.
- Fixtures web (`services/web/conftest.py`): `readonly_client`/`auth_client`/`admin_client` (gotowe zalogowane klienty), `make_connection(user, **kwargs)` (domyślnie `protocol='sftp'` — dla testów rsync przekazać `protocol='rsync'` jawnie).

---

### Task 1: `RsyncHandler.preview()`

**Files:**
- Modify: `services/worker/modules/rsync/handler.py`
- Test: `services/worker/tests/test_rsync_handler.py`

**Interfaces:**
- Consumes: istniejące `self._build_command(source_override, dest_override, known_hosts_path, dry_run)`, `self._run_attempt(cmd, log_callback) -> tuple[int, str]`, `encrypt_file(source_path, gpg_passphrase)` (już importowane w handler.py z `modules.gpg.handler`).
- Produces: `RsyncHandler.preview(self, log_callback) -> dict` — `{'exit_code': int, 'output': str}`. Nigdy nie rzuca `RsyncTransferError`. Wywoływane przez Task 2.

- [ ] **Step 1: Napisz czerwone testy `TestRsyncHandlerPreview`**

Dodaj na końcu `services/worker/tests/test_rsync_handler.py`:

```python
class TestRsyncHandlerPreview:
    def _make_params(self, **kwargs):
        defaults = {
            'host': '192.168.1.10',
            'port': 22,
            'username': 'deploy',
            'password': None,
            'ssh_key': None,
            'source_path': '/data/',
            'destination_path': '/backup/',
            'compress': False,
            'encrypt': False,
            'gpg_passphrase': None,
            'strict_host_key_checking': False,
            'known_host_key': None,
        }
        defaults.update(kwargs)
        return defaults

    def test_returns_exit_code_and_output_on_success(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['sending incremental file list\n', 'file.tar\n'])
            mock_proc.wait.return_value = 0
            MockPopen.return_value = mock_proc
            result = RsyncHandler(self._make_params()).preview(lambda lvl, msg: None)
            assert result['exit_code'] == 0
            assert 'file.tar' in result['output']

    def test_returns_nonzero_exit_code_instead_of_raising(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['Permission denied (publickey).\n'])
            mock_proc.wait.return_value = 255
            MockPopen.return_value = mock_proc
            result = RsyncHandler(self._make_params()).preview(lambda lvl, msg: None)
            assert result['exit_code'] == 255
            assert 'Permission denied' in result['output']

    def test_uses_dry_run_flag_in_command(self):
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(list(cmd))
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params()).preview(lambda lvl, msg: None)

        assert len(calls) == 1
        assert '--dry-run' in calls[0]

    def test_does_not_execute_real_transfer(self):
        call_count = [0]

        def fake_popen(cmd, **kwargs):
            call_count[0] += 1
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params()).preview(lambda lvl, msg: None)

        assert call_count[0] == 1  # tylko dry-run, żadnego drugiego wywołania

    def test_prepends_host_key_warning_when_verification_disabled(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['sending incremental file list\n'])
            mock_proc.wait.return_value = 0
            MockPopen.return_value = mock_proc
            result = RsyncHandler(self._make_params(strict_host_key_checking=False)).preview(
                lambda lvl, msg: None
            )
            assert 'Host key verification DISABLED' in result['output']

    def test_uses_encrypted_path_when_gpg_enabled(self):
        encrypted_tmp = '/tmp/data_abc.gpg'
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(list(cmd))
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.rsync.handler.os.path.exists', return_value=True), \
             patch('modules.rsync.handler.os.unlink'), \
             patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params(encrypt=True, gpg_passphrase='secret')).preview(
                lambda lvl, msg: None
            )

        assert len(calls) == 1
        assert encrypted_tmp in calls[0]

    def test_creates_and_cleans_up_known_hosts_tempfile(self):
        params = self._make_params(
            strict_host_key_checking=True,
            known_host_key='192.168.1.10 ssh-rsa AAAA...',
        )
        created_paths = []

        def fake_popen(cmd, **kwargs):
            for part in cmd:
                if 'UserKnownHostsFile=' in part:
                    path = part.split('=', 1)[1].strip("'")
                    created_paths.append(path)
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(params).preview(lambda lvl, msg: None)

        assert len(created_paths) == 1
        assert not __import__('os').path.exists(created_paths[0])
```

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/test_rsync_handler.py::TestRsyncHandlerPreview -v`
Expected: FAIL — `AttributeError: 'RsyncHandler' object has no attribute 'preview'`

- [ ] **Step 3: Zaimplementuj `preview()`**

W `services/worker/modules/rsync/handler.py`, zaraz po istniejącej metodzie `execute()` (po jej ostatniej linii, przed końcem klasy), dodaj:

```python
    def preview(self, log_callback: Callable[[str, str], None]) -> dict:
        use_gpg = self.params.get('encrypt') and self.params.get('gpg_passphrase')
        encrypted_path = None
        known_hosts_path = None
        warning_prefix = ''

        try:
            if self.params.get('strict_host_key_checking') and self.params.get('known_host_key'):
                with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
                    f.write(self.params['known_host_key'])
                    known_hosts_path = f.name
            else:
                warning_prefix = 'Host key verification DISABLED — connection is vulnerable to MITM\n'
                log_callback('warn', 'Host key verification DISABLED — connection is vulnerable to MITM')

            if use_gpg:
                log_callback('info', 'GPG: szyfrowanie pliku...')
                try:
                    encrypted_path = encrypt_file(self.params['source_path'], self.params['gpg_passphrase'])
                except GPGEncryptError as e:
                    return {'exit_code': None, 'output': warning_prefix + f'GPG ENCRYPTION FAILED: {e}'}
                source_override = encrypted_path
                dest_override = self.params['destination_path'] + '.gpg'
            else:
                source_override = None
                dest_override = None

            dry_cmd = self._build_command(
                source_override=source_override,
                dest_override=dest_override,
                known_hosts_path=known_hosts_path,
                dry_run=True,
            )
            exit_code, output = self._run_attempt(dry_cmd, log_callback)
            return {'exit_code': exit_code, 'output': warning_prefix + output}
        finally:
            if encrypted_path and os.path.exists(encrypted_path):
                os.unlink(encrypted_path)
            if known_hosts_path and os.path.exists(known_hosts_path):
                os.unlink(known_hosts_path)
```

- [ ] **Step 4: Uruchom testy — zielone**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/test_rsync_handler.py::TestRsyncHandlerPreview -v`
Expected: PASS (7 testów)

- [ ] **Step 5: Pełny zestaw testów worker — brak regresji**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/ -v`
Expected: PASS — istniejące testy `TestRsyncHandler`/`TestRsyncDryRun`/`TestRsyncChecksumVerification` nadal zielone (żadna z nich nie dotyka `preview()`, `execute()` niezmienione).

- [ ] **Step 6: Commit**

```bash
git add services/worker/modules/rsync/handler.py services/worker/tests/test_rsync_handler.py
git commit -m "$(cat <<'EOF'
feat: dodaj RsyncHandler.preview() dla samodzielnego podglądu dry-run

Wydzielone z istniejącej logiki dry-run w execute() — nowa metoda
zwraca exit_code+output zamiast rzucać wyjątek, bo ma być pokazana
userowi jako informacja, nie przerywać niczego. Dopisuje ostrzeżenie
o wyłączonej weryfikacji host key na początek output (execute() dziś
loguje je tylko do TransferLog, którego preview nie ma).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Task Celery `transfers.dry_run_preview`

**Files:**
- Modify: `services/worker/tasks.py`
- Test: `services/worker/tests/test_tasks.py`

**Interfaces:**
- Consumes: `RsyncHandler.preview(log_callback) -> dict` (Task 1), `apps.connections.models.Connection` (już importowany pośrednio w tasks.py przez `job.connection`, ale `Connection` sam w sobie nie jest tam jeszcze zaimportowany bezpośrednio — trzeba dodać import).
- Produces: task Celery `'transfers.dry_run_preview'` — `dry_run_preview(connection_id: int, source_path: str, destination_path: str, gpg_passphrase: str | None = None) -> dict`. Zawsze zwraca `{'exit_code': int|None, 'output': str}` — **ten sam kształt** co `RsyncHandler.preview()` (Task 1), również gdy połączenie nie istnieje (`exit_code=None`, komunikat w `output`). Wywoływane przez Task 3 (`current_app.send_task('transfers.dry_run_preview', ...)`).

- [ ] **Step 1: Napisz czerwone testy `TestDryRunPreviewTask`**

Dodaj na końcu `services/worker/tests/test_tasks.py`:

```python
class TestDryRunPreviewTask:
    def test_builds_params_from_connection_and_delegates_to_preview(self):
        with patch('tasks.Connection') as MockConn, \
             patch('tasks.RsyncHandler') as MockRsync:
            mock_conn = MagicMock()
            mock_conn.host = '10.0.0.5'
            mock_conn.port = 22
            mock_conn.username = 'deploy'
            mock_conn.password = None
            mock_conn.ssh_key = 'key-data'
            mock_conn.compress = True
            mock_conn.encrypt = False
            mock_conn.strict_host_key_checking = True
            mock_conn.known_host_key = 'known-host-entry'
            MockConn.objects.get.return_value = mock_conn
            MockRsync.return_value.preview.return_value = {'exit_code': 0, 'output': 'ok'}

            from tasks import dry_run_preview
            result = dry_run_preview(connection_id=1, source_path='/transfers/f.tar', destination_path='/backup/')

            assert result == {'exit_code': 0, 'output': 'ok'}
            params = MockRsync.call_args[0][0]
            assert params['host'] == '10.0.0.5'
            assert params['source_path'] == '/transfers/f.tar'
            assert params['destination_path'] == '/backup/'
            assert params['compress'] is True

    def test_returns_error_dict_when_connection_not_found(self):
        with patch('tasks.Connection') as MockConn:
            MockConn.DoesNotExist = Exception
            MockConn.objects.get.side_effect = MockConn.DoesNotExist
            from tasks import dry_run_preview
            result = dry_run_preview(connection_id=999, source_path='/transfers/f.tar', destination_path='/backup/')
            assert result['exit_code'] is None
            assert 'nie istnieje' in result['output']

    def test_passes_gpg_passphrase_to_params(self):
        with patch('tasks.Connection') as MockConn, \
             patch('tasks.RsyncHandler') as MockRsync:
            mock_conn = MagicMock()
            mock_conn.encrypt = True
            MockConn.objects.get.return_value = mock_conn
            MockRsync.return_value.preview.return_value = {'exit_code': 0, 'output': 'ok'}

            from tasks import dry_run_preview
            dry_run_preview(
                connection_id=1, source_path='/transfers/f.tar',
                destination_path='/backup/', gpg_passphrase='secret123',
            )

            params = MockRsync.call_args[0][0]
            assert params['gpg_passphrase'] == 'secret123'
            assert params['encrypt'] is True

    def test_delegates_to_rsync_handler_preview_not_execute(self):
        with patch('tasks.Connection') as MockConn, \
             patch('tasks.RsyncHandler') as MockRsync:
            MockConn.objects.get.return_value = MagicMock()
            MockRsync.return_value.preview.return_value = {'exit_code': 0, 'output': 'ok'}

            from tasks import dry_run_preview
            dry_run_preview(connection_id=1, source_path='/a', destination_path='/b')

            MockRsync.return_value.preview.assert_called_once()
            MockRsync.return_value.execute.assert_not_called()
```

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/test_tasks.py::TestDryRunPreviewTask -v`
Expected: FAIL — `ImportError: cannot import name 'dry_run_preview' from 'tasks'`

- [ ] **Step 3: Dodaj import `Connection` i task `dry_run_preview`**

W `services/worker/tasks.py`, w bloku importów, zmień:

```python
from apps.transfers.models import TransferJob, TransferLog  # noqa: E402
```

na:

```python
from apps.connections.models import Connection  # noqa: E402
from apps.transfers.models import TransferJob, TransferLog  # noqa: E402
```

Następnie, zaraz po `cleanup_old_transfers` (po jego ostatniej linii `logger.info(f'Retention: usunięto {removed} plików z {settings.TRANSFERS_DIR}')`), dodaj:

```python
@app.task(name='transfers.dry_run_preview')
def dry_run_preview(connection_id: int, source_path: str, destination_path: str, gpg_passphrase: str | None = None) -> dict:
    try:
        conn = Connection.objects.get(pk=connection_id)
    except Connection.DoesNotExist:
        return {'exit_code': None, 'output': f'Connection {connection_id} nie istnieje'}

    params = {
        'host': conn.host,
        'port': conn.port,
        'username': conn.username,
        'password': conn.password,
        'ssh_key': conn.ssh_key,
        'source_path': source_path,
        'destination_path': destination_path,
        'compress': conn.compress,
        'encrypt': conn.encrypt,
        'gpg_passphrase': gpg_passphrase,
        'strict_host_key_checking': conn.strict_host_key_checking,
        'known_host_key': conn.known_host_key,
    }

    def log_callback(level: str, message: str):
        logger.info(f'[dry-run preview] {level}: {message}') if level != 'warn' else logger.warning(f'[dry-run preview] {message}')

    return RsyncHandler(params).preview(log_callback)
```

- [ ] **Step 4: Uruchom testy — zielone**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/test_tasks.py::TestDryRunPreviewTask -v`
Expected: PASS (4 testy)

- [ ] **Step 5: Pełny zestaw testów worker — brak regresji**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/worker/tasks.py services/worker/tests/test_tasks.py
git commit -m "$(cat <<'EOF'
feat: dodaj task transfers.dry_run_preview

Buduje parametry bezpośrednio z Connection + jawnych ścieżek (bez
TransferJob) i deleguje do RsyncHandler.preview(). log_callback loguje
do loggera workera (operacyjnie), nie do TransferLog — dry-run nie ma
joba.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Widok `transfer_dry_run` (dispatch)

**Files:**
- Modify: `services/web/apps/transfers/views.py`
- Modify: `services/web/apps/transfers/urls.py`
- Test: `services/web/apps/transfers/tests/test_views.py`

**Interfaces:**
- Consumes: `transfers.dry_run_preview` task (Task 2, wywoływane przez `current_app.send_task`), istniejący `TransferForm` (bez zmian).
- Produces: URL `transfers:dry_run` (POST) → renderuje `transfers/create.html` z dodatkowym kontekstem `dry_run_task_id: str` gdy dispatch się powiódł. Task 5 (template) czyta ten kontekst.

- [ ] **Step 1: Napisz czerwone testy**

Dodaj na końcu `services/web/apps/transfers/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestTransferDryRunView:
    def test_dry_run_forbidden_for_readonly(self, readonly_client, regular_user, make_connection):
        conn = make_connection(regular_user, protocol='rsync')
        response = readonly_client.post(reverse('transfers:dry_run'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': SimpleUploadedFile('file.tar', b'payload'),
        })
        assert response.status_code == 403

    def test_dry_run_rejects_non_rsync_connection(self, auth_client, regular_user, make_connection, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        conn = make_connection(regular_user, protocol='sftp')
        response = auth_client.post(reverse('transfers:dry_run'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': SimpleUploadedFile('file.tar', b'payload'),
        })
        assert response.status_code == 200
        assert 'rsync' in response.content.decode().lower()
        assert TransferJob.objects.count() == 0

    def test_dry_run_validates_form_same_as_create(self, auth_client, regular_user, make_connection, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        conn = make_connection(regular_user, protocol='rsync')
        response = auth_client.post(reverse('transfers:dry_run'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            # brak 'upload' — pole wymagane
        })
        assert response.status_code == 200
        assert TransferJob.objects.count() == 0

    def test_dry_run_saves_upload_without_creating_transferjob(self, auth_client, regular_user, make_connection, settings, tmp_path, mocker):
        settings.TRANSFERS_DIR = str(tmp_path)
        mocker.patch(
            'apps.transfers.views.current_app.send_task',
            return_value=SimpleNamespace(id='fake-task-id'),
        )
        conn = make_connection(regular_user, protocol='rsync')
        upload = SimpleUploadedFile('preview.tar', b'payload-bytes')
        response = auth_client.post(reverse('transfers:dry_run'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': upload,
        })
        assert response.status_code == 200
        assert TransferJob.objects.count() == 0
        assert (tmp_path / 'preview.tar').exists()

    def test_dry_run_dispatches_task_and_returns_task_id(self, auth_client, regular_user, make_connection, settings, tmp_path, mocker):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_send = mocker.patch(
            'apps.transfers.views.current_app.send_task',
            return_value=SimpleNamespace(id='fake-task-id'),
        )
        conn = make_connection(regular_user, protocol='rsync')
        upload = SimpleUploadedFile('preview.tar', b'payload-bytes')
        response = auth_client.post(reverse('transfers:dry_run'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': upload,
        })
        assert response.status_code == 200
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == 'transfers.dry_run_preview'
        assert 'fake-task-id' in response.content.decode()
```

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/transfers/tests/test_views.py::TestTransferDryRunView -v`
Expected: FAIL — `NoReverseMatch: Reverse for 'dry_run' not found`

- [ ] **Step 3: Dodaj URL**

W `services/web/apps/transfers/urls.py`, dodaj do `urlpatterns` (przed `path('logs/', ...)`):

```python
    path('dry-run/', views.transfer_dry_run, name='dry_run'),
```

- [ ] **Step 4: Dodaj widok `transfer_dry_run`**

W `services/web/apps/transfers/views.py`, zaraz po istniejącym `transfer_create` (po jego ostatniej linii `return render(request, 'transfers/create.html', {'form': form})`), dodaj:

```python
@require_role(ROLE_OPERATOR)
def transfer_dry_run(request):
    form = TransferForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        connection = form.cleaned_data['connection']
        if connection.protocol != 'rsync':
            form.add_error(None, 'Dry-run jest dostępny tylko dla połączeń rsync.')
            return render(request, 'transfers/create.html', {'form': form})
        uploaded = form.cleaned_data['upload']
        dest = form.cleaned_data['source_path']
        try:
            with open(dest, 'wb') as fh:
                for chunk in uploaded.chunks():
                    fh.write(chunk)
        except OSError as exc:
            form.add_error(None, f'Nie udało się zapisać pliku: {exc}')
            return render(request, 'transfers/create.html', {'form': form})
        passphrase = (form.cleaned_data.get('gpg_passphrase') or '').strip() or None
        result = current_app.send_task('transfers.dry_run_preview', kwargs={
            'connection_id': connection.pk,
            'source_path': form.cleaned_data['source_path'],
            'destination_path': form.cleaned_data['destination_path'],
            'gpg_passphrase': passphrase,
        })
        return render(request, 'transfers/create.html', {'form': form, 'dry_run_task_id': result.id})
    return render(request, 'transfers/create.html', {'form': form})
```

- [ ] **Step 5: Uruchom testy — zielone**

Run: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/transfers/tests/test_views.py::TestTransferDryRunView -v`
Expected: PASS (5 testów)

- [ ] **Step 6: Pełny zestaw testów web — brak regresji**

Run: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add services/web/apps/transfers/views.py services/web/apps/transfers/urls.py services/web/apps/transfers/tests/test_views.py
git commit -m "$(cat <<'EOF'
feat: dodaj widok transfer_dry_run (dispatch podglądu rsync)

Identyczna walidacja i zapis uploadu co transfer_create, ale bez
tworzenia TransferJob — dispatchuje transfers.dry_run_preview i
zwraca task_id do pollingu. Odrzuca połączenia inne niż rsync.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Widok `transfer_dry_run_status` (polling)

**Files:**
- Modify: `services/web/apps/transfers/views.py`
- Modify: `services/web/apps/transfers/urls.py`
- Create: `services/web/templates/transfers/_dry_run_result.html`
- Test: `services/web/apps/transfers/tests/test_views.py`

**Interfaces:**
- Consumes: `celery.result.AsyncResult`, `CELERY_RESULT_BACKEND='django-db'` (już skonfigurowany).
- Produces: URL `transfers:dry_run_status` (GET, `<str:task_id>`) → fragment HTML. Konsumowane przez Task 5 (template, HTMX polling).

- [ ] **Step 1: Napisz czerwone testy**

Dodaj na końcu `services/web/apps/transfers/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestTransferDryRunStatusView:
    def test_status_forbidden_for_readonly(self, readonly_client):
        response = readonly_client.get(reverse('transfers:dry_run_status', args=['fake-id']))
        assert response.status_code == 403

    def test_status_renders_pending(self, auth_client, mocker):
        mock_result = mocker.MagicMock()
        mock_result.state = 'PENDING'
        mocker.patch('apps.transfers.views.AsyncResult', return_value=mock_result)
        response = auth_client.get(reverse('transfers:dry_run_status', args=['fake-id']))
        assert response.status_code == 200
        body = response.content.decode()
        assert 'every' in body  # kontener nadal polluje (hx-trigger)

    def test_status_renders_success_exit_zero(self, auth_client, mocker):
        mock_result = mocker.MagicMock()
        mock_result.state = 'SUCCESS'
        mock_result.result = {'exit_code': 0, 'output': 'sending incremental file list\nfile.tar'}
        mocker.patch('apps.transfers.views.AsyncResult', return_value=mock_result)
        response = auth_client.get(reverse('transfers:dry_run_status', args=['fake-id']))
        assert response.status_code == 200
        body = response.content.decode()
        assert 'file.tar' in body
        assert 'msg-ok' in body

    def test_status_renders_success_nonzero_exit(self, auth_client, mocker):
        mock_result = mocker.MagicMock()
        mock_result.state = 'SUCCESS'
        mock_result.result = {'exit_code': 23, 'output': 'rsync: No such file or directory'}
        mocker.patch('apps.transfers.views.AsyncResult', return_value=mock_result)
        response = auth_client.get(reverse('transfers:dry_run_status', args=['fake-id']))
        assert response.status_code == 200
        body = response.content.decode()
        assert 'No such file' in body
        assert 'msg-error' in body

    def test_status_renders_failure(self, auth_client, mocker):
        mock_result = mocker.MagicMock()
        mock_result.state = 'FAILURE'
        mocker.patch('apps.transfers.views.AsyncResult', return_value=mock_result)
        response = auth_client.get(reverse('transfers:dry_run_status', args=['fake-id']))
        assert response.status_code == 200
        assert 'msg-error' in response.content.decode()
```

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/transfers/tests/test_views.py::TestTransferDryRunStatusView -v`
Expected: FAIL — `NoReverseMatch: Reverse for 'dry_run_status' not found`

- [ ] **Step 3: Dodaj URL**

W `services/web/apps/transfers/urls.py`, dodaj po `dry-run/`:

```python
    path('dry-run/<str:task_id>/status/', views.transfer_dry_run_status, name='dry_run_status'),
```

- [ ] **Step 4: Dodaj CSS `.msg-ok`**

Edytuj **wyłącznie** `services/web/static/css/crt.css` — `services/web/staticfiles/css/crt.css` to wygenerowana kopia (`collectstatic`, uruchamiane w `entrypoint.sh` przy starcie kontenera; potwierdzone identyczne z `static/` przed tą zmianą), nie edytować ręcznie. Zaraz po istniejącej regule `.msg-error { color: var(--red); padding: 0.5rem; border: 1px solid var(--red); margin-bottom: 0.5rem; }`, dodaj:

```css
.msg-ok { color: var(--green); padding: 0.5rem; border: 1px solid var(--green); margin-bottom: 0.5rem; white-space: pre-wrap; }
```

Rozszerz też `.msg-error` o `white-space: pre-wrap;` (output rsync jest wieloliniowy, dziś ta reguła by go spłaszczyła):

```css
.msg-error { color: var(--red); padding: 0.5rem; border: 1px solid var(--red); margin-bottom: 0.5rem; white-space: pre-wrap; }
```

- [ ] **Step 5: Dodaj widok `transfer_dry_run_status` i fragment szablonu**

W `services/web/apps/transfers/views.py`, dodaj import na górze pliku:

```python
from celery.result import AsyncResult
```

Zaraz po `transfer_dry_run`, dodaj:

```python
@require_role(ROLE_OPERATOR)
def transfer_dry_run_status(request, task_id):
    result = AsyncResult(task_id)
    return render(request, 'transfers/_dry_run_result.html', {
        'task_id': task_id,
        'state': result.state,
        'result': result.result if result.state == 'SUCCESS' else None,
    })
```

Utwórz `services/web/templates/transfers/_dry_run_result.html`:

```html
{% if state == 'PENDING' or state == 'STARTED' %}
<div id="dry-run-result" class="msg-ok"
  hx-get="{% url 'transfers:dry_run_status' task_id %}"
  hx-trigger="every 2s"
  hx-swap="outerHTML">
  &gt; DRY-RUN W TOKU...
</div>
{% elif state == 'SUCCESS' and result.exit_code == 0 %}
<div id="dry-run-result" class="msg-ok">&gt; DRY-RUN OK — poniżej co zostanie przesłane:
{{ result.output }}</div>
{% elif state == 'SUCCESS' %}
<div id="dry-run-result" class="msg-error">&gt; DRY-RUN FAILED (exit {{ result.exit_code }}):
{{ result.output }}</div>
{% else %}
<div id="dry-run-result" class="msg-error">&gt; DRY-RUN BŁĄD — nie udało się wykonać podglądu.</div>
{% endif %}
```

- [ ] **Step 6: Uruchom testy — zielone**

Run: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/transfers/tests/test_views.py::TestTransferDryRunStatusView -v`
Expected: PASS (5 testów)

- [ ] **Step 7: Pełny zestaw testów web — brak regresji**

Run: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add services/web/apps/transfers/views.py services/web/apps/transfers/urls.py services/web/templates/transfers/_dry_run_result.html services/web/static/css/crt.css services/web/apps/transfers/tests/test_views.py
git commit -m "$(cat <<'EOF'
feat: dodaj endpoint pollingu wyniku dry-run + fragment szablonu

AsyncResult czyta wynik z już skonfigurowanego CELERY_RESULT_BACKEND
(django-db) — zero nowego modelu. Fragment self-polluje przez HTMX
dopóki task nie osiągnie SUCCESS/FAILURE.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Przycisk `[DRY RUN]` w formularzu + widoczność wg protokołu

**Files:**
- Modify: `services/web/templates/transfers/create.html`
- Modify: `services/web/apps/transfers/views.py`

**Interfaces:**
- Consumes: `dry_run_task_id` z kontekstu (Task 3), `_dry_run_result.html` (Task 4).
- Produces: nic konsumowane przez dalsze taski — to ostatnia zmiana funkcjonalna przed weryfikacją końcową.

Ten task nie ma automatycznych testów (czysto wizualna/JS warstwa formularza — spójne z tym, jak projekt traktuje warstwę HTML/JS gdzie indziej, np. HTTPS/nginx w poprzednich planach). Weryfikacja manualna w przeglądarce w Step 4.

- [ ] **Step 1: Dodaj `connection_protocols` do kontekstu obu widoków**

W `services/web/apps/transfers/views.py`, dodaj helper zaraz pod importami (po ostatnim `from .forms import TransferForm`):

```python
def _connection_protocols():
    return dict(Connection.objects.values_list('pk', 'protocol'))
```

`transfer_create` ma dziś dokładnie **dwa** wywołania `render(request, 'transfers/create.html', ...)`. Zamień oba:

```python
@require_role(ROLE_OPERATOR)
def transfer_create(request):
    form = TransferForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        uploaded = form.cleaned_data['upload']
        dest = form.cleaned_data['source_path']
        try:
            with open(dest, 'wb') as fh:
                for chunk in uploaded.chunks():
                    fh.write(chunk)
        except OSError as exc:
            form.add_error(None, f'Nie udało się zapisać pliku: {exc}')
            return render(request, 'transfers/create.html', {'form': form, 'connection_protocols': _connection_protocols()})
        with transaction.atomic():
            job = form.save(commit=False)
            job.owner = request.user
            job.source_path = form.cleaned_data['source_path']
            job.save()
            passphrase = (form.cleaned_data.get('gpg_passphrase') or '').strip() or None

            def _dispatch():
                result = current_app.send_task('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': passphrase})
                TransferJob.objects.filter(pk=job.pk).update(celery_task_id=result.id)
            transaction.on_commit(_dispatch)
        return redirect('transfers:detail', pk=job.pk)
    return render(request, 'transfers/create.html', {'form': form, 'connection_protocols': _connection_protocols()})
```

`transfer_dry_run` (Task 3) ma dziś dokładnie **cztery** wywołania `render(request, 'transfers/create.html', ...)` — błąd protokołu, błąd zapisu pliku, sukces, fallback GET/invalid-form. Zamień całą funkcję:

```python
@require_role(ROLE_OPERATOR)
def transfer_dry_run(request):
    form = TransferForm(request.POST or None, request.FILES or None, user=request.user)
    ctx_base = {'connection_protocols': _connection_protocols()}
    if request.method == 'POST' and form.is_valid():
        connection = form.cleaned_data['connection']
        if connection.protocol != 'rsync':
            form.add_error(None, 'Dry-run jest dostępny tylko dla połączeń rsync.')
            return render(request, 'transfers/create.html', {**ctx_base, 'form': form})
        uploaded = form.cleaned_data['upload']
        dest = form.cleaned_data['source_path']
        try:
            with open(dest, 'wb') as fh:
                for chunk in uploaded.chunks():
                    fh.write(chunk)
        except OSError as exc:
            form.add_error(None, f'Nie udało się zapisać pliku: {exc}')
            return render(request, 'transfers/create.html', {**ctx_base, 'form': form})
        passphrase = (form.cleaned_data.get('gpg_passphrase') or '').strip() or None
        result = current_app.send_task('transfers.dry_run_preview', kwargs={
            'connection_id': connection.pk,
            'source_path': form.cleaned_data['source_path'],
            'destination_path': form.cleaned_data['destination_path'],
            'gpg_passphrase': passphrase,
        })
        return render(request, 'transfers/create.html', {**ctx_base, 'form': form, 'dry_run_task_id': result.id})
    return render(request, 'transfers/create.html', {**ctx_base, 'form': form})
```

To **zastępuje w całości** wersję `transfer_dry_run` napisaną w Task 3 Step 4 (ten sam plik, ta sama funkcja — Task 3 jej jeszcze nie zna kontekstu `connection_protocols`, bo to dokłada dopiero ten task).

- [ ] **Step 2: Dodaj przycisk `[DRY RUN]` i kontener wyniku do `create.html`**

W `services/web/templates/transfers/create.html`, zmień:

```html
      <button type="submit" class="btn">[ EXECUTE TRANSFER ]</button>
    </form>
  </div>
```

na:

```html
      <button type="submit" class="btn">[ EXECUTE TRANSFER ]</button>
      <button type="submit" formaction="{% url 'transfers:dry_run' %}" class="btn btn-warn" id="dry-run-btn">[ DRY RUN ]</button>
    </form>
    {% if dry_run_task_id %}
    <div hx-get="{% url 'transfers:dry_run_status' dry_run_task_id %}" hx-trigger="load" hx-swap="outerHTML"></div>
    {% endif %}
  </div>
```

Na końcu pliku (przed `{% endblock %}`), dodaj:

```html
<script id="connection-protocols" type="application/json">{{ connection_protocols|safe|default:"{}" }}</script>
<script>
(function () {
  var protocols = JSON.parse(document.getElementById('connection-protocols').textContent);
  var select = document.getElementById('id_connection');
  var btn = document.getElementById('dry-run-btn');
  if (!select || !btn) return;
  function sync() {
    var proto = protocols[select.value];
    btn.style.display = (proto === 'rsync') ? 'inline-block' : 'none';
  }
  select.addEventListener('change', sync);
  sync();
})();
</script>
```

- [ ] **Step 3: Uruchom pełny zestaw testów web**

Run: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/ -v`
Expected: PASS — `connection_protocols` w kontekście nie psuje istniejących testów `TestTransferCreateView` (dict serializuje się do JSON poprawnie nawet pusty; `{{ connection_protocols|safe }}` z pustym dict renderuje `{}`, prawidłowy JSON).

- [ ] **Step 4: Manualna weryfikacja w przeglądarce**

Uruchom stos (`docker compose up -d`), zaloguj się jako Operator/Admin, wejdź na `/transfers/` (New Transfer):
- Utwórz (lub użyj istniejącego) połączenia z `protocol=rsync` i drugie z `protocol=sftp`.
- Wybierz połączenie SFTP w dropdownie — przycisk `[ DRY RUN ]` ma zniknąć.
- Wybierz połączenie rsync — przycisk ma się pojawić.
- Wypełnij plik + ścieżkę docelową, kliknij `[ DRY RUN ]` — powinien pojawić się output rsync (realny SSH do testowego hosta, albo oczekiwany błąd połączenia jeśli host nieosiągalny — liczy się, że UI poprawnie renderuje wynik, nie konkretna treść).
- Sprawdź że po samym `[ DRY RUN ]` **nie** powstał wpis na liście transferów (`/transfers/logs/`).

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/transfers/views.py services/web/templates/transfers/create.html
git commit -m "$(cat <<'EOF'
feat: dodaj przycisk [DRY RUN] do formularza New Transfer

Widoczny tylko dla połączeń rsync (JS wg connection_protocols z
kontekstu, zmieniany przy zmianie wyboru połączenia). Zweryfikowane
manualnie w przeglądarce.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Weryfikacja końcowa całej gałęzi

**Files:** brak zmian — tylko weryfikacja.

- [ ] **Step 1: Rebuild + pełny zestaw testów worker (dokładnie jak CI)**

Run:
```bash
docker compose build worker
docker compose run --rm worker python -m pytest tests/ -v
```
Expected: PASS

- [ ] **Step 2: Rebuild + pełny zestaw testów web (dokładnie jak CI)**

Run:
```bash
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/ -v
```
Expected: PASS

- [ ] **Step 3: Przegląd całej gałęzi**

Użyj `superpowers:requesting-code-review` (whole-branch review, model opus) na `feat/dry-run-preview` względem `main` przed mergem.

---

## Po wdrożeniu (poza planem TDD)

- Aktualizacja dokumentacji w vault Obsidian: `11-Apps/CSCS/tmask-transporter/Projekt-tmask-transporter.md` (nowy punkt) oraz `Propozycje rozbudowy.md` (oznaczyć #5 jako zrealizowane). Wpis do `LOG.md`.
