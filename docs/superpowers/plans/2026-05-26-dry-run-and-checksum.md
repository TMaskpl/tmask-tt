# Dry-run przed rsync + Weryfikacja SHA-256 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodanie dry-run przed każdym rsync transferem oraz weryfikacji integralności SHA-256 po transferze dla sftp i rsync.

**Architecture:** Dwa nowe pola boolean na modelu `Connection` (`dry_run_before_transfer`, `verify_checksum`) przekazywane przez `_build_params()` do handlerów workera. Nowy moduł `modules/checksum/handler.py` z funkcjami `verify_sftp()` i `verify_rsync()`. `RsyncHandler` wykonuje dry-run przed retry pętlą i wywołuje `verify_rsync()` po sukcesie. `SFTPHandler._transfer_once()` dostaje parametr `use_gpg` i wywołuje `verify_sftp()` przed zamknięciem klienta.

**Tech Stack:** Django 5.x, paramiko 3.x, subprocess, hashlib (stdlib), pytest + MagicMock + patch, Docker Compose

---

## Mapa plików

| Plik | Akcja | Opis |
|------|-------|------|
| `services/web/apps/connections/models.py` | Modyfikacja | Dwa nowe pola BooleanField |
| `services/web/apps/connections/migrations/0002_dry_run_and_checksum.py` | Tworzenie | Django migration |
| `services/web/apps/connections/forms.py` | Modyfikacja | Dwa nowe pola w ConnectionForm |
| `services/web/apps/connections/tests/test_models.py` | Modyfikacja | 2 nowe testy defaults |
| `services/web/templates/connections/form.html` | Modyfikacja | Sekcja OPCJE ZAAWANSOWANE |
| `services/worker/modules/checksum/__init__.py` | Tworzenie | Pusty plik modułu |
| `services/worker/modules/checksum/handler.py` | Tworzenie | `_local_sha256`, `verify_sftp`, `verify_rsync` |
| `services/worker/tests/test_checksum_handler.py` | Tworzenie | 8 testów modułu checksum |
| `services/worker/modules/rsync/handler.py` | Modyfikacja | dry_run w `_build_command`, `_build_ssh_cmd_prefix`, checksum w `execute` |
| `services/worker/tests/test_rsync_handler.py` | Modyfikacja | `TestRsyncDryRun` (4 testy) + `TestRsyncChecksumVerification` (4 testy) |
| `services/worker/modules/sftp/handler.py` | Modyfikacja | `use_gpg` param w `_transfer_once`, checksum po transferze |
| `services/worker/tests/test_sftp_handler.py` | Modyfikacja | `TestSFTPChecksumVerification` (4 testy) |
| `services/worker/tasks.py` | Modyfikacja | `_build_params` — 2 nowe klucze |

---

## Task 1: Connection model — nowe pola + migracja

**Files:**
- Modify: `services/web/apps/connections/models.py:18`
- Create: `services/web/apps/connections/migrations/0002_dry_run_and_checksum.py` (generowana)
- Test: `services/web/apps/connections/tests/test_models.py`

- [ ] **Step 1: Napisz testy defaults**

Dodaj do klasy `TestConnection` w `services/web/apps/connections/tests/test_models.py`:

```python
def test_dry_run_before_transfer_default_false(self, regular_user):
    conn = Connection(
        owner=regular_user, name='X', host='h', username='u', protocol='rsync'
    )
    assert conn.dry_run_before_transfer is False

def test_verify_checksum_default_false(self, regular_user):
    conn = Connection(
        owner=regular_user, name='X', host='h', username='u', protocol='sftp'
    )
    assert conn.verify_checksum is False
```

- [ ] **Step 2: Uruchom testy — oczekiwane FAIL**

```bash
docker compose run --rm web pytest apps/connections/tests/test_models.py::TestConnection::test_dry_run_before_transfer_default_false apps/connections/tests/test_models.py::TestConnection::test_verify_checksum_default_false -v
```

Oczekiwane: `AttributeError: 'Connection' object has no attribute 'dry_run_before_transfer'`

- [ ] **Step 3: Dodaj pola do modelu**

W `services/web/apps/connections/models.py`, po linii 21 (`known_host_key = ...`), przed `created_at`:

```python
dry_run_before_transfer = models.BooleanField(default=False)
verify_checksum         = models.BooleanField(default=False)
```

Pełny model po zmianie (linie 9–29):

```python
class Connection(models.Model):
    owner    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='connections')
    name     = models.CharField(max_length=100)
    host     = models.CharField(max_length=255)
    port     = models.IntegerField(default=22)
    username = models.CharField(max_length=100)
    password = EncryptedCharField(max_length=500, null=True, blank=True)
    ssh_key  = EncryptedTextField(null=True, blank=True)
    protocol = models.CharField(max_length=10, choices=PROTOCOL_CHOICES, default=PROTOCOL_SFTP)
    compress = models.BooleanField(default=False)
    encrypt  = models.BooleanField(default=False)
    strict_host_key_checking = models.BooleanField(default=True)
    known_host_key           = models.TextField(null=True, blank=True)
    dry_run_before_transfer  = models.BooleanField(default=False)
    verify_checksum          = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.host}:{self.port})'

    class Meta:
        ordering = ['-created_at']
```

- [ ] **Step 4: Wygeneruj migrację**

```bash
docker compose run --rm web python manage.py makemigrations connections --name dry_run_and_checksum
```

Oczekiwane: `Migrations for 'connections': services/web/apps/connections/migrations/0002_dry_run_and_checksum.py`

- [ ] **Step 5: Zastosuj migrację**

```bash
docker compose run --rm web python manage.py migrate
```

Oczekiwane: `Applying connections.0002_dry_run_and_checksum... OK`

- [ ] **Step 6: Uruchom testy — oczekiwane PASS**

```bash
docker compose run --rm web pytest apps/connections/tests/test_models.py -v
```

Oczekiwane: wszystkie PASS

- [ ] **Step 7: Commit**

```bash
git add services/web/apps/connections/models.py services/web/apps/connections/migrations/0002_dry_run_and_checksum.py services/web/apps/connections/tests/test_models.py
git commit -m "feat: add dry_run_before_transfer and verify_checksum fields to Connection"
```

---

## Task 2: Moduł checksum

**Files:**
- Create: `services/worker/modules/checksum/__init__.py`
- Create: `services/worker/modules/checksum/handler.py`
- Create: `services/worker/tests/test_checksum_handler.py`

- [ ] **Step 1: Utwórz pusty `__init__.py`**

```bash
touch services/worker/modules/checksum/__init__.py
```

- [ ] **Step 2: Napisz testy**

Utwórz `services/worker/tests/test_checksum_handler.py`:

```python
import hashlib
import pytest
from unittest.mock import MagicMock, patch

from modules.checksum.handler import (
    ChecksumVerificationError,
    _local_sha256,
    verify_sftp,
    verify_rsync,
)


class TestLocalSha256:
    def test_returns_correct_hash(self, tmp_path):
        data = b"hello world"
        f = tmp_path / "test.bin"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert _local_sha256(str(f)) == expected

    def test_reads_large_file_correctly(self, tmp_path):
        data = b"x" * (65536 * 2 + 1)
        f = tmp_path / "large.bin"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert _local_sha256(str(f)) == expected


class TestVerifySftp:
    def _make_client(self, stdout_content: bytes, stderr_content: bytes = b""):
        mock_client = MagicMock()
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = stdout_content
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = stderr_content
        mock_client.exec_command.return_value = (None, mock_stdout, mock_stderr)
        return mock_client

    def test_ok_when_hashes_match(self, tmp_path):
        data = b"file content"
        src = tmp_path / "src.bin"
        src.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        client = self._make_client(f"{sha}  /dest/file.bin\n".encode())
        logs = []
        verify_sftp(str(src), client, "/dest/file.bin", lambda lvl, msg: logs.append(msg))
        assert any("SHA-256 OK" in m for m in logs)

    def test_raises_on_mismatch(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"local content")
        wrong_hash = "deadbeef" * 8  # 64 hex chars, inny niż lokalny
        client = self._make_client(f"{wrong_hash}  /dest/file.bin\n".encode())
        with pytest.raises(ChecksumVerificationError, match="MISMATCH"):
            verify_sftp(str(src), client, "/dest/file.bin", lambda lvl, msg: None)

    def test_raises_when_sha256sum_missing(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"content")
        client = self._make_client(b"", b"sha256sum: command not found")
        with pytest.raises(ChecksumVerificationError, match="sha256sum failed"):
            verify_sftp(str(src), client, "/dest/file.bin", lambda lvl, msg: None)


class TestVerifyRsync:
    def _make_result(self, returncode, stdout="", stderr=""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def test_ok_when_hashes_match(self, tmp_path):
        data = b"file content"
        src = tmp_path / "src.bin"
        src.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        result = self._make_result(0, f"{sha}  /dest/file.bin\n")
        logs = []
        with patch("modules.checksum.handler.subprocess.run", return_value=result):
            verify_rsync(
                str(src), ["ssh", "user@host"], "/dest/file.bin",
                lambda lvl, msg: logs.append(msg),
            )
        assert any("SHA-256 OK" in m for m in logs)

    def test_raises_on_mismatch(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"local content")
        wrong_hash = "deadbeef" * 8
        result = self._make_result(0, f"{wrong_hash}  /dest/file.bin\n")
        with patch("modules.checksum.handler.subprocess.run", return_value=result):
            with pytest.raises(ChecksumVerificationError, match="MISMATCH"):
                verify_rsync(
                    str(src), ["ssh", "user@host"], "/dest/file.bin",
                    lambda lvl, msg: None,
                )

    def test_raises_on_nonzero_exit(self, tmp_path):
        src = tmp_path / "src.bin"
        src.write_bytes(b"content")
        result = self._make_result(1, "", "sha256sum: No such file or directory")
        with patch("modules.checksum.handler.subprocess.run", return_value=result):
            with pytest.raises(ChecksumVerificationError, match="sha256sum failed"):
                verify_rsync(
                    str(src), ["ssh", "user@host"], "/dest/file.bin",
                    lambda lvl, msg: None,
                )
```

- [ ] **Step 3: Uruchom testy — oczekiwane FAIL**

```bash
docker compose run --rm worker pytest tests/test_checksum_handler.py -v
```

Oczekiwane: `ModuleNotFoundError: No module named 'modules.checksum'`

- [ ] **Step 4: Zaimplementuj moduł**

Utwórz `services/worker/modules/checksum/handler.py`:

```python
import hashlib
import shlex
import subprocess


class ChecksumVerificationError(Exception):
    pass


def _local_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_sftp(source_path: str, ssh_client, remote_path: str, log_callback) -> None:
    local_hash = _local_sha256(source_path)
    _, stdout, stderr = ssh_client.exec_command(f'sha256sum {shlex.quote(remote_path)}')
    output = stdout.read().decode().strip()
    if not output:
        raise ChecksumVerificationError(f'sha256sum failed: {stderr.read().decode().strip()}')
    remote_hash = output.split()[0]
    if local_hash != remote_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: local={local_hash[:16]}... remote={remote_hash[:16]}...'
        )
    log_callback('info', f'SHA-256 OK: {local_hash[:16]}...')


def verify_rsync(source_path: str, ssh_cmd_prefix: list, remote_path: str, log_callback) -> None:
    local_hash = _local_sha256(source_path)
    cmd = ssh_cmd_prefix + [f'sha256sum {shlex.quote(remote_path)}']
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ChecksumVerificationError(f'sha256sum failed: {result.stderr.strip()}')
    remote_hash = result.stdout.strip().split()[0]
    if local_hash != remote_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: local={local_hash[:16]}... remote={remote_hash[:16]}...'
        )
    log_callback('info', f'SHA-256 OK: {local_hash[:16]}...')
```

- [ ] **Step 5: Uruchom testy — oczekiwane PASS**

```bash
docker compose run --rm worker pytest tests/test_checksum_handler.py -v
```

Oczekiwane: 8 PASS

- [ ] **Step 6: Commit**

```bash
git add services/worker/modules/checksum/ services/worker/tests/test_checksum_handler.py
git commit -m "feat: add checksum module with SHA-256 verify_sftp and verify_rsync"
```

---

## Task 3: RsyncHandler — dry-run

**Files:**
- Modify: `services/worker/modules/rsync/handler.py`
- Test: `services/worker/tests/test_rsync_handler.py`

- [ ] **Step 1: Napisz testy**

Dodaj nową klasę na końcu `services/worker/tests/test_rsync_handler.py`:

```python
class TestRsyncDryRun:
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
            'dry_run': False,
            'verify_checksum': False,
        }
        defaults.update(kwargs)
        return defaults

    def test_dry_run_command_includes_flag(self):
        handler = RsyncHandler(self._make_params())
        cmd = handler._build_command(dry_run=True)
        assert '--dry-run' in cmd

    def test_real_command_excludes_dry_run_flag(self):
        handler = RsyncHandler(self._make_params())
        cmd = handler._build_command(dry_run=False)
        assert '--dry-run' not in cmd

    def test_dry_run_runs_before_real_transfer(self):
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(list(cmd))
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params(dry_run=True)).execute(lambda lvl, msg: None)

        assert len(calls) == 2
        assert '--dry-run' in calls[0]
        assert '--dry-run' not in calls[1]

    def test_dry_run_failure_aborts_transfer(self):
        call_count = [0]

        def fake_popen(cmd, **kwargs):
            call_count[0] += 1
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 1
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            with pytest.raises(RsyncTransferError, match='DRY-RUN FAILED'):
                RsyncHandler(self._make_params(dry_run=True)).execute(lambda lvl, msg: None)

        assert call_count[0] == 1  # tylko dry-run, właściwy transfer nie wywołany

    def test_dry_run_skipped_when_disabled(self):
        calls = []

        def fake_popen(cmd, **kwargs):
            calls.append(list(cmd))
            m = MagicMock()
            m.stdout = iter([])
            m.wait.return_value = 0
            return m

        with patch('modules.rsync.handler.subprocess.Popen', side_effect=fake_popen):
            RsyncHandler(self._make_params(dry_run=False)).execute(lambda lvl, msg: None)

        assert len(calls) == 1
        assert '--dry-run' not in calls[0]
```

- [ ] **Step 2: Uruchom testy — oczekiwane FAIL**

```bash
docker compose run --rm worker pytest tests/test_rsync_handler.py::TestRsyncDryRun -v
```

Oczekiwane: `TypeError: _build_command() got an unexpected keyword argument 'dry_run'`

- [ ] **Step 3: Zaimplementuj dry-run w RsyncHandler**

W `services/worker/modules/rsync/handler.py` zmień sygnaturę `_build_command()` (linia 42):

```python
def _build_command(self, source_override=None, dest_override=None,
                   known_hosts_path=None, dry_run: bool = False) -> list:
    source = source_override or self.params['source_path']
    dest = dest_override or self.params['destination_path']
    cmd = ['rsync'] + list(RSYNC_BASE_FLAGS)
    if self.params.get('compress'):
        cmd.append(RSYNC_COMPRESS_FLAG)
    if dry_run:
        cmd.append('--dry-run')
    ssh_opts = self._build_ssh_options(known_hosts_path=known_hosts_path)
    cmd += ['-e', f'ssh {ssh_opts}', '--']
    cmd.append(source)
    cmd.append(f'{self.params["username"]}@{self.params["host"]}:{dest}')
    return cmd
```

W `execute()` (linia 79) dodaj dry-run blok bezpośrednio po GPG setup (`source_override`, `dest_override` ustawione), przed pętlą `for attempt in range(...)`. Sekcja `execute()` po zmianach (cały pełny blok po `try:`):

```python
def execute(self, log_callback: Callable[[str, str], None]) -> None:
    use_gpg = self.params.get('encrypt') and self.params.get('gpg_passphrase')
    encrypted_path = None
    known_hosts_path = None

    try:
        if self.params.get('strict_host_key_checking') and self.params.get('known_host_key'):
            with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
                f.write(self.params['known_host_key'])
                known_hosts_path = f.name
        else:
            log_callback('warn', 'Host key verification DISABLED — connection is vulnerable to MITM')

        if use_gpg:
            log_callback('info', 'GPG: szyfrowanie pliku...')
            try:
                encrypted_path = encrypt_file(self.params['source_path'], self.params['gpg_passphrase'])
            except GPGEncryptError as e:
                raise RsyncTransferError(str(e))
            source_override = encrypted_path
            dest_override = self.params['destination_path'] + '.gpg'
        else:
            source_override = None
            dest_override = None

        if self.params.get('dry_run'):
            log_callback('info', 'Dry-run: sprawdzam transfer...')
            dry_cmd = self._build_command(
                source_override=source_override,
                dest_override=dest_override,
                known_hosts_path=known_hosts_path,
                dry_run=True,
            )
            exit_code, output = self._run_attempt(dry_cmd, log_callback)
            self._check_rsync_output(exit_code, output)
            if exit_code != 0:
                raise RsyncTransferError(f'DRY-RUN FAILED (exit {exit_code}) — transfer anulowany')
            log_callback('info', 'Dry-run OK — kontynuuję transfer')

        cmd = self._build_command(source_override=source_override, dest_override=dest_override, known_hosts_path=known_hosts_path)
        last_exit_code = None

        for attempt in range(1, RSYNC_MAX_RETRIES + 1):
            log_callback('info', f'Starting rsync (attempt {attempt}): {" ".join(cmd)}')
            last_exit_code, output = self._run_attempt(cmd, log_callback)
            self._check_rsync_output(last_exit_code, output)
            if last_exit_code == 0:
                log_callback('info', 'Transfer complete')
                return
            if attempt < RSYNC_MAX_RETRIES:
                log_callback('warn', f'rsync failed (exit {last_exit_code}), retrying in {RSYNC_RETRY_DELAY}s...')
                time.sleep(RSYNC_RETRY_DELAY)

        raise RsyncTransferError(
            f'TRANSFER FAILED — rsync failed after {RSYNC_MAX_RETRIES} attempts (last exit code: {last_exit_code})'
        )
    finally:
        if encrypted_path and os.path.exists(encrypted_path):
            os.unlink(encrypted_path)
        if known_hosts_path and os.path.exists(known_hosts_path):
            os.unlink(known_hosts_path)
```

- [ ] **Step 4: Uruchom testy — oczekiwane PASS**

```bash
docker compose run --rm worker pytest tests/test_rsync_handler.py -v
```

Oczekiwane: wszystkie PASS (istniejące + 5 nowych)

- [ ] **Step 5: Commit**

```bash
git add services/worker/modules/rsync/handler.py services/worker/tests/test_rsync_handler.py
git commit -m "feat: add dry-run before rsync transfer"
```

---

## Task 4: RsyncHandler — SHA-256

**Files:**
- Modify: `services/worker/modules/rsync/handler.py`
- Test: `services/worker/tests/test_rsync_handler.py`

- [ ] **Step 1: Napisz testy**

Dodaj nową klasę na końcu `services/worker/tests/test_rsync_handler.py`:

```python
class TestRsyncChecksumVerification:
    def _make_params(self, **kwargs):
        defaults = {
            'host': '192.168.1.10',
            'port': 22,
            'username': 'deploy',
            'password': None,
            'ssh_key': None,
            'source_path': '/data/file.tar',
            'destination_path': '/backup/file.tar',
            'compress': False,
            'encrypt': False,
            'gpg_passphrase': None,
            'strict_host_key_checking': False,
            'known_host_key': None,
            'dry_run': False,
            'verify_checksum': False,
        }
        defaults.update(kwargs)
        return defaults

    def _popen_ok(self):
        m = MagicMock()
        m.stdout = iter([])
        m.wait.return_value = 0
        return m

    def test_calls_verify_rsync_after_successful_transfer(self):
        with patch('modules.rsync.handler.subprocess.Popen', return_value=self._popen_ok()), \
             patch('modules.rsync.handler.verify_rsync') as mock_verify:
            RsyncHandler(self._make_params(verify_checksum=True)).execute(lambda lvl, msg: None)
        mock_verify.assert_called_once()

    def test_skips_verify_when_disabled(self):
        with patch('modules.rsync.handler.subprocess.Popen', return_value=self._popen_ok()), \
             patch('modules.rsync.handler.verify_rsync') as mock_verify:
            RsyncHandler(self._make_params(verify_checksum=False)).execute(lambda lvl, msg: None)
        mock_verify.assert_not_called()

    def test_raises_transfer_error_on_mismatch(self):
        from modules.checksum.handler import ChecksumVerificationError
        with patch('modules.rsync.handler.subprocess.Popen', return_value=self._popen_ok()), \
             patch('modules.rsync.handler.verify_rsync',
                   side_effect=ChecksumVerificationError('SHA-256 MISMATCH')):
            with pytest.raises(RsyncTransferError, match='MISMATCH'):
                RsyncHandler(self._make_params(verify_checksum=True)).execute(lambda lvl, msg: None)

    def test_skips_verify_when_gpg_enabled(self):
        encrypted_tmp = '/tmp/data_abc.gpg'
        logs = []
        with patch('modules.rsync.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.rsync.handler.os.path.exists', return_value=True), \
             patch('modules.rsync.handler.os.unlink'), \
             patch('modules.rsync.handler.subprocess.Popen', return_value=self._popen_ok()), \
             patch('modules.rsync.handler.verify_rsync') as mock_verify:
            RsyncHandler(self._make_params(
                encrypt=True, gpg_passphrase='secret', verify_checksum=True,
            )).execute(lambda lvl, msg: logs.append((lvl, msg)))
        mock_verify.assert_not_called()
        assert any('SHA-256' in msg and 'pomijane' in msg for _, msg in logs)
```

- [ ] **Step 2: Uruchom testy — oczekiwane FAIL**

```bash
docker compose run --rm worker pytest tests/test_rsync_handler.py::TestRsyncChecksumVerification -v
```

Oczekiwane: `ImportError` lub `AssertionError: Expected 'verify_rsync' to be called once`

- [ ] **Step 3: Dodaj import i `_build_ssh_cmd_prefix` do handler.py**

Na górze `services/worker/modules/rsync/handler.py`, po istniejących importach, dodaj:

```python
from modules.checksum.handler import verify_rsync, ChecksumVerificationError
```

Dodaj metodę `_build_ssh_cmd_prefix()` do klasy `RsyncHandler`, po `_build_command()`:

```python
def _build_ssh_cmd_prefix(self, known_hosts_path=None) -> list:
    port = int(self.params['port'])
    cmd = ['ssh', '-p', str(port), '-o', 'BatchMode=yes']
    if self.params.get('strict_host_key_checking') and known_hosts_path:
        cmd += ['-o', f'UserKnownHostsFile={known_hosts_path}',
                '-o', 'StrictHostKeyChecking=yes']
    elif not self.params.get('strict_host_key_checking', True):
        cmd += ['-o', 'StrictHostKeyChecking=no']
    if self.params.get('ssh_key'):
        cmd += ['-i', self.params['ssh_key']]
    cmd.append(f'{self.params["username"]}@{self.params["host"]}')
    return cmd
```

W `execute()`, wewnątrz pętli retry, zamień:

```python
if last_exit_code == 0:
    log_callback('info', 'Transfer complete')
    return
```

na:

```python
if last_exit_code == 0:
    log_callback('info', 'Transfer complete')
    if self.params.get('verify_checksum') and not use_gpg:
        try:
            ssh_prefix = self._build_ssh_cmd_prefix(known_hosts_path)
            verify_rsync(
                source_override or self.params['source_path'],
                ssh_prefix,
                dest_override or self.params['destination_path'],
                log_callback,
            )
        except ChecksumVerificationError as e:
            raise RsyncTransferError(str(e))
    elif self.params.get('verify_checksum') and use_gpg:
        log_callback('warn', 'SHA-256: pomijane — GPG włączone (encrypted file)')
    return
```

- [ ] **Step 4: Uruchom testy — oczekiwane PASS**

```bash
docker compose run --rm worker pytest tests/test_rsync_handler.py -v
```

Oczekiwane: wszystkie PASS

- [ ] **Step 5: Commit**

```bash
git add services/worker/modules/rsync/handler.py services/worker/tests/test_rsync_handler.py
git commit -m "feat: add SHA-256 checksum verification to RsyncHandler"
```

---

## Task 5: SFTPHandler — SHA-256

**Files:**
- Modify: `services/worker/modules/sftp/handler.py`
- Test: `services/worker/tests/test_sftp_handler.py`

- [ ] **Step 1: Napisz testy**

Dodaj nową klasę na końcu `services/worker/tests/test_sftp_handler.py`:

```python
class TestSFTPChecksumVerification:
    def _make_params(self, **kwargs):
        defaults = {
            'host': '192.168.1.10',
            'port': 22,
            'username': 'deploy',
            'password': 'secret',
            'ssh_key': None,
            'source_path': '/data/file.tar',
            'destination_path': '/backup/file.tar',
            'compress': False,
            'encrypt': False,
            'gpg_passphrase': None,
            'strict_host_key_checking': False,
            'known_host_key': None,
            'verify_checksum': False,
        }
        defaults.update(kwargs)
        return defaults

    def _make_mock_ssh(self):
        mock_client = MagicMock()
        mock_sftp = MagicMock()
        mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
        mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
        return mock_client

    def test_calls_verify_sftp_after_transfer(self):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.sftp.handler.verify_sftp') as mock_verify:
            MockSSH.return_value = self._make_mock_ssh()
            SFTPHandler(self._make_params(verify_checksum=True)).execute(lambda lvl, msg: None)
        mock_verify.assert_called_once()

    def test_skips_verify_when_disabled(self):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.sftp.handler.verify_sftp') as mock_verify:
            MockSSH.return_value = self._make_mock_ssh()
            SFTPHandler(self._make_params(verify_checksum=False)).execute(lambda lvl, msg: None)
        mock_verify.assert_not_called()

    def test_raises_transfer_error_on_mismatch(self):
        from modules.checksum.handler import ChecksumVerificationError
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.sftp.handler.verify_sftp',
                   side_effect=ChecksumVerificationError('SHA-256 MISMATCH')):
            MockSSH.return_value = self._make_mock_ssh()
            with pytest.raises(SFTPTransferError, match='MISMATCH'):
                SFTPHandler(self._make_params(verify_checksum=True)).execute(lambda lvl, msg: None)

    def test_skips_verify_when_gpg_enabled(self):
        encrypted_tmp = '/tmp/file_abc.gpg'
        logs = []
        with patch('modules.sftp.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.sftp.handler.os.path.exists', return_value=True), \
             patch('modules.sftp.handler.os.unlink'), \
             patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.sftp.handler.verify_sftp') as mock_verify:
            MockSSH.return_value = self._make_mock_ssh()
            SFTPHandler(self._make_params(
                encrypt=True, gpg_passphrase='secret', verify_checksum=True,
            )).execute(lambda lvl, msg: logs.append((lvl, msg)))
        mock_verify.assert_not_called()
        assert any('SHA-256' in msg and 'pomijane' in msg for _, msg in logs)
```

- [ ] **Step 2: Uruchom testy — oczekiwane FAIL**

```bash
docker compose run --rm worker pytest tests/test_sftp_handler.py::TestSFTPChecksumVerification -v
```

Oczekiwane: `AssertionError: Expected 'verify_sftp' to be called once`

- [ ] **Step 3: Zaimplementuj w SFTPHandler**

Na górze `services/worker/modules/sftp/handler.py`, po istniejących importach:

```python
from modules.checksum.handler import verify_sftp, ChecksumVerificationError
```

Zmień sygnaturę `_transfer_once()` (linia 54):

```python
def _transfer_once(self, source: str, dest: str, log_callback, use_gpg: bool = False) -> None:
```

Wewnątrz `_transfer_once()`, po bloku `with client.open_sftp() as sftp:` (po `sftp.put()`), przed `log_callback('info', 'Transfer complete')`:

```python
            with client.open_sftp() as sftp:
                def _progress(done: int, total: int) -> None:
                    if total:
                        log_callback('info', f'Progress: {int(done / total * 100)}%')
                sftp.put(source, dest, callback=_progress)

            if self.params.get('verify_checksum') and not use_gpg:
                try:
                    verify_sftp(source, client, dest, log_callback)
                except ChecksumVerificationError as e:
                    raise SFTPTransferError(str(e))
            elif self.params.get('verify_checksum') and use_gpg:
                log_callback('warn', 'SHA-256: pomijane — GPG włączone (encrypted file)')

            log_callback('info', 'Transfer complete')
```

W `execute()` zaktualizuj wywołanie `_transfer_once()`:

```python
self._transfer_once(source, dest, log_callback, use_gpg=use_gpg)
```

Pełna metoda `execute()` po zmianach:

```python
def execute(self, log_callback) -> None:
    if not (self.params.get('strict_host_key_checking') and self.params.get('known_host_key')):
        log_callback('warn', 'Host key verification DISABLED — connection is vulnerable to MITM')

    use_gpg = self.params.get('encrypt') and self.params.get('gpg_passphrase')
    encrypted_path = None

    try:
        if use_gpg:
            log_callback('info', 'GPG: szyfrowanie pliku...')
            try:
                encrypted_path = encrypt_file(self.params['source_path'], self.params['gpg_passphrase'])
            except GPGEncryptError as e:
                raise SFTPTransferError(str(e))
            source = encrypted_path
            dest = self.params['destination_path'] + '.gpg'
        else:
            source = self.params['source_path']
            dest = self.params['destination_path']

        for attempt in range(1, SFTP_MAX_RETRIES + 1):
            try:
                self._transfer_once(source, dest, log_callback, use_gpg=use_gpg)
                return
            except (socket.timeout, socket.gaierror):
                if attempt < SFTP_MAX_RETRIES:
                    log_callback('warn', f'Connection failed, retrying in {SFTP_RETRY_DELAY}s...')
                    time.sleep(SFTP_RETRY_DELAY)

        raise SFTPTransferError(f'CONNECTION TIMEOUT — {self.params["host"]} unreachable')
    finally:
        if encrypted_path and os.path.exists(encrypted_path):
            os.unlink(encrypted_path)
```

- [ ] **Step 4: Uruchom testy — oczekiwane PASS**

```bash
docker compose run --rm worker pytest tests/test_sftp_handler.py -v
```

Oczekiwane: wszystkie PASS (istniejące + 4 nowe; uwaga: `test_connection_timeout_retries_and_raises` jest pre-existing fail z innego commitu — zignoruj jeśli się pojawi)

- [ ] **Step 5: Commit**

```bash
git add services/worker/modules/sftp/handler.py services/worker/tests/test_sftp_handler.py
git commit -m "feat: add SHA-256 checksum verification to SFTPHandler"
```

---

## Task 6: tasks.py — _build_params

**Files:**
- Modify: `services/worker/tasks.py:20-35`

- [ ] **Step 1: Zaktualizuj `_build_params()`**

W `services/worker/tasks.py` zamień funkcję `_build_params()` (linie 20–35):

```python
def _build_params(job: TransferJob, gpg_passphrase=None) -> dict:
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
        'gpg_passphrase': gpg_passphrase,
        'strict_host_key_checking': conn.strict_host_key_checking,
        'known_host_key': conn.known_host_key,
        'dry_run': conn.dry_run_before_transfer,
        'verify_checksum': conn.verify_checksum,
    }
```

- [ ] **Step 2: Uruchom wszystkie testy workera**

```bash
docker compose run --rm worker pytest -v
```

Oczekiwane: wszystkie PASS (pomijając pre-existing fail `test_connection_timeout_retries_and_raises`)

- [ ] **Step 3: Commit**

```bash
git add services/worker/tasks.py
git commit -m "feat: pass dry_run and verify_checksum from Connection to handler params"
```

---

## Task 7: Web — formularz i szablon

**Files:**
- Modify: `services/web/apps/connections/forms.py:7-8`
- Modify: `services/web/templates/connections/form.html`

- [ ] **Step 1: Zaktualizuj `ConnectionForm`**

W `services/web/apps/connections/forms.py` zamień całą klasę `ConnectionForm`:

```python
from django import forms
from .models import Connection


class ConnectionForm(forms.ModelForm):
    class Meta:
        model = Connection
        fields = [
            'name', 'host', 'port', 'username', 'password', 'ssh_key',
            'protocol', 'compress', 'encrypt', 'strict_host_key_checking',
            'known_host_key', 'dry_run_before_transfer', 'verify_checksum',
        ]
        labels = {
            'dry_run_before_transfer': 'Dry-run przed transferem (tylko rsync)',
            'verify_checksum':         'Weryfikuj integralność SHA-256 po transferze',
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
        if not cleaned.get('password') and not cleaned.get('ssh_key'):
            raise forms.ValidationError('Podaj hasło lub klucz SSH.')
        return cleaned
```

- [ ] **Step 2: Zaktualizuj szablon połączenia**

W `services/web/templates/connections/form.html` zmień blok `{% for field in form %}` (linie 11–36):

```html
    {% for field in form %}
    {% if field.name == 'known_host_key' %}
    <div class="field" id="known-host-section" style="display:none">
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
    <div class="box-title" style="margin-top:1.2rem;font-size:0.85rem;">[ OPCJE ZAAWANSOWANE ]</div>
    <div class="field">
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
```

- [ ] **Step 3: Uruchom wszystkie testy webowe**

```bash
docker compose run --rm web pytest -v
```

Oczekiwane: wszystkie PASS

- [ ] **Step 4: Commit**

```bash
git add services/web/apps/connections/forms.py services/web/templates/connections/form.html
git commit -m "feat: add dry_run and verify_checksum fields to ConnectionForm and template"
```

---

## Weryfikacja końcowa

- [ ] **Uruchom pełny suite worker**

```bash
docker compose run --rm worker pytest -v
```

- [ ] **Uruchom pełny suite web**

```bash
docker compose run --rm web pytest -v
```

Oczekiwane łącznie: ~192 PASS (175 poprzednich + 17 nowych), 1 pre-existing FAIL (`test_connection_timeout_retries_and_raises` z commit `5bfc352` — poza zakresem)
