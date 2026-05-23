# GPG encrypt=True Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Szyfrowanie symetryczne AES-256 przez GPG CLI przed transferem SFTP/rsync — passphrase podawana per-transfer, nigdy niezapisywana.

**Architecture:** Nowy moduł `modules/gpg/handler.py` szyfruje plik lokalnie na workerze tuż przed transferem. Oba handlery (SFTP, rsync) dostają encrypted_path jako source i `dest + '.gpg'` jako destination. Cleanup w `finally` — zawsze, nawet przy błędzie. Passphrase przepływa przez: formularz → widok → `execute_transfer.delay(gpg_passphrase=...)` → `_build_params()` → handler.

**Tech Stack:** Python `subprocess` + GPG CLI (`gnupg`), `tempfile.mkstemp`, Django forms, Celery task args.

---

## File Map

**Nowe pliki:**
- `services/worker/modules/gpg/__init__.py`
- `services/worker/modules/gpg/config.py`
- `services/worker/modules/gpg/handler.py`
- `services/worker/tests/test_gpg_handler.py`

**Zmodyfikowane pliki:**
- `services/worker/conftest.py` — dodanie `gpg_passphrase: None` do fixtures `sftp_params` i `rsync_params`
- `services/worker/modules/sftp/handler.py` — GPG krok przed `sftp.put()`, cleanup w `finally`
- `services/worker/modules/rsync/handler.py` — GPG krok przed rsync, `_build_command(source_override, dest_override)`, cleanup w `finally`
- `services/worker/tasks.py` — `execute_transfer(gpg_passphrase=None)`, `_build_params(job, gpg_passphrase=None)`, WARN dla scheduled
- `services/worker/tests/test_sftp_handler.py` — 2 nowe testy
- `services/worker/tests/test_rsync_handler.py` — 2 nowe testy
- `services/worker/tests/test_tasks.py` — 1 nowy test
- `services/web/apps/transfers/forms.py` — pole `gpg_passphrase`
- `services/web/apps/transfers/views.py` — passphrase → `execute_transfer.delay`
- `services/worker/Dockerfile` — `gnupg` w apt

---

## Task 1: Moduł GPG — config, handler, testy

**Files:**
- Create: `services/worker/modules/gpg/__init__.py`
- Create: `services/worker/modules/gpg/config.py`
- Create: `services/worker/modules/gpg/handler.py`
- Create: `services/worker/tests/test_gpg_handler.py`

- [ ] **Step 1: Stwórz katalog i `__init__.py`**

```bash
mkdir -p services/worker/modules/gpg
touch services/worker/modules/gpg/__init__.py
```

- [ ] **Step 2: Napisz testy (RED) — `test_gpg_handler.py`**

```python
# services/worker/tests/test_gpg_handler.py
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.gpg.handler import encrypt_file, GPGEncryptError


class TestEncryptFile:
    def _make_source(self, content=b'secret data'):
        fd, path = tempfile.mkstemp()
        os.write(fd, content)
        os.close(fd)
        return path

    def test_returns_path_on_success(self):
        source = self._make_source()
        try:
            mock_result = MagicMock()
            mock_result.returncode = 0
            with patch('modules.gpg.handler.subprocess.run', return_value=mock_result):
                with patch('builtins.open', MagicMock()):
                    encrypted = encrypt_file(source, 'secret123')
            assert encrypted.endswith('.gpg')
            assert os.path.exists(encrypted)
        finally:
            os.unlink(source)
            if os.path.exists(encrypted):
                os.unlink(encrypted)

    def test_raises_on_gpg_failure(self):
        source = self._make_source()
        try:
            mock_result = MagicMock()
            mock_result.returncode = 2
            mock_result.stderr = 'gpg: invalid passphrase'
            with patch('modules.gpg.handler.subprocess.run', return_value=mock_result):
                with pytest.raises(GPGEncryptError, match='GPG FAILED'):
                    encrypt_file(source, 'wrong')
        finally:
            os.unlink(source)

    def test_raises_when_gpg_not_installed(self):
        source = self._make_source()
        try:
            with patch('modules.gpg.handler.subprocess.run', side_effect=FileNotFoundError):
                with pytest.raises(GPGEncryptError, match='GPG NOT INSTALLED'):
                    encrypt_file(source, 'secret123')
        finally:
            os.unlink(source)

    def test_cleans_up_temp_file_on_failure(self):
        source = self._make_source()
        captured = {}

        original_mkstemp = tempfile.mkstemp

        def mock_mkstemp(**kwargs):
            fd, path = original_mkstemp(**kwargs)
            captured['path'] = path
            return fd, path

        try:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = 'error'
            with patch('modules.gpg.handler.subprocess.run', return_value=mock_result), \
                 patch('modules.gpg.handler.tempfile.mkstemp', side_effect=mock_mkstemp):
                with pytest.raises(GPGEncryptError):
                    encrypt_file(source, 'secret')
            assert not os.path.exists(captured['path'])
        finally:
            os.unlink(source)
```

- [ ] **Step 3: Uruchom testy — upewnij się że FAIL**

```bash
cd services/web && python -m pytest ../worker/tests/test_gpg_handler.py -v
```

Oczekiwane: `ModuleNotFoundError: No module named 'modules.gpg.handler'`

- [ ] **Step 4: Stwórz `config.py`**

```python
# services/worker/modules/gpg/config.py
GPG_CIPHER_ALGO = 'AES256'
GPG_TIMEOUT = 300
```

- [ ] **Step 5: Stwórz `handler.py`**

```python
# services/worker/modules/gpg/handler.py
import os
import subprocess
import tempfile
from pathlib import Path

from .config import GPG_CIPHER_ALGO, GPG_TIMEOUT


class GPGEncryptError(Exception):
    pass


def encrypt_file(source_path: str, passphrase: str) -> str:
    """
    Szyfruje plik symetrycznie AES-256 przez GPG CLI.
    Zwraca ścieżkę do zaszyfrowanego pliku tymczasowego.
    Caller odpowiada za os.unlink() zwróconej ścieżki.
    Rzuca GPGEncryptError przy każdym błędzie i czyści temp plik.
    """
    stem = Path(source_path).stem
    fd, encrypted_path = tempfile.mkstemp(suffix='.gpg', prefix=f'{stem}_')
    os.close(fd)
    try:
        result = subprocess.run(
            [
                'gpg', '--batch', '--yes', '--symmetric',
                '--cipher-algo', GPG_CIPHER_ALGO,
                '--passphrase-fd', '0',
                '--output', encrypted_path,
                source_path,
            ],
            input=passphrase,
            capture_output=True,
            text=True,
            timeout=GPG_TIMEOUT,
        )
        if result.returncode != 0:
            raise GPGEncryptError(f'GPG FAILED — {result.stderr.strip()}')
        return encrypted_path
    except GPGEncryptError:
        os.unlink(encrypted_path)
        raise
    except subprocess.TimeoutExpired:
        os.unlink(encrypted_path)
        raise GPGEncryptError('GPG TIMEOUT — encryption took too long')
    except FileNotFoundError:
        os.unlink(encrypted_path)
        raise GPGEncryptError('GPG NOT INSTALLED — install gnupg package')
    except Exception as e:
        os.unlink(encrypted_path)
        raise GPGEncryptError(f'GPG ERROR — {e}')
```

- [ ] **Step 6: Uruchom testy — upewnij się że PASS**

```bash
cd services/web && python -m pytest ../worker/tests/test_gpg_handler.py -v
```

Oczekiwane: 4 PASSED

- [ ] **Step 7: Commit**

```bash
git add services/worker/modules/gpg/ services/worker/tests/test_gpg_handler.py
git commit -m "feat: add GPG encrypt module with symmetric AES-256 support"
```

---

## Task 2: Zaktualizuj conftest — dodaj `gpg_passphrase` do fixtures

**Files:**
- Modify: `services/worker/conftest.py`

- [ ] **Step 1: Dodaj `gpg_passphrase: None` do obu fixtures**

W `services/worker/conftest.py` zmień oba fixtures tak, by zawierały `gpg_passphrase`:

```python
# services/worker/conftest.py
import pytest


@pytest.fixture
def sftp_params():
    return {
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
    }


@pytest.fixture
def rsync_params():
    return {
        'host': '192.168.1.10',
        'port': 22,
        'username': 'deploy',
        'password': None,
        'ssh_key': '/tmp/id_rsa',
        'source_path': '/data/',
        'destination_path': '/backup/',
        'compress': False,
        'encrypt': False,
        'gpg_passphrase': None,
        'strict_host_key_checking': False,
        'known_host_key': None,
    }
```

- [ ] **Step 2: Upewnij się że istniejące testy nadal przechodzą**

```bash
cd services/web && python -m pytest ../worker/tests/test_sftp_handler.py ../worker/tests/test_rsync_handler.py -v
```

Oczekiwane: wszystkie PASSED (brak zmian w logice)

- [ ] **Step 3: Commit**

```bash
git add services/worker/conftest.py
git commit -m "test: add gpg_passphrase to worker test fixtures"
```

---

## Task 3: SFTPHandler — integracja GPG

**Files:**
- Modify: `services/worker/modules/sftp/handler.py`
- Modify: `services/worker/tests/test_sftp_handler.py`

- [ ] **Step 1: Napisz testy (RED) — dopisz do `TestSFTPHandler`**

Na końcu klasy `TestSFTPHandler` w `services/worker/tests/test_sftp_handler.py` dodaj:

```python
    def test_execute_with_encrypt_uses_encrypted_paths(self, sftp_params):
        sftp_params['encrypt'] = True
        sftp_params['gpg_passphrase'] = 'secret123'
        encrypted_tmp = '/tmp/file_abc.gpg'

        with patch('modules.sftp.handler.encrypt_file', return_value=encrypted_tmp) as mock_encrypt, \
             patch('modules.sftp.handler.os.path.exists', return_value=True), \
             patch('modules.sftp.handler.os.unlink') as mock_unlink, \
             patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)

            SFTPHandler(sftp_params).execute(log_callback=lambda lvl, msg: None)

            mock_encrypt.assert_called_once_with(
                sftp_params['source_path'], sftp_params['gpg_passphrase']
            )
            mock_sftp.put.assert_called_once()
            call_args = mock_sftp.put.call_args[0]
            assert call_args[0] == encrypted_tmp
            assert call_args[1] == sftp_params['destination_path'] + '.gpg'
            mock_unlink.assert_called_once_with(encrypted_tmp)

    def test_cleanup_encrypted_file_even_on_transfer_error(self, sftp_params):
        sftp_params['encrypt'] = True
        sftp_params['gpg_passphrase'] = 'secret123'
        encrypted_tmp = '/tmp/file_abc.gpg'

        with patch('modules.sftp.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.sftp.handler.os.path.exists', return_value=True), \
             patch('modules.sftp.handler.os.unlink') as mock_unlink, \
             patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_sftp.put.side_effect = OSError('No space left on device')
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)

            with pytest.raises(SFTPTransferError):
                SFTPHandler(sftp_params).execute(log_callback=lambda lvl, msg: None)

            mock_unlink.assert_called_once_with(encrypted_tmp)
```

- [ ] **Step 2: Uruchom testy — upewnij się że FAIL**

```bash
cd services/web && python -m pytest ../worker/tests/test_sftp_handler.py::TestSFTPHandler::test_execute_with_encrypt_uses_encrypted_paths ../worker/tests/test_sftp_handler.py::TestSFTPHandler::test_cleanup_encrypted_file_even_on_transfer_error -v
```

Oczekiwane: FAIL (brak importu `encrypt_file` i logiki GPG w handlerze)

- [ ] **Step 3: Zaktualizuj `sftp/handler.py`**

```python
# services/worker/modules/sftp/handler.py
import io
import os
import socket
import time

import paramiko

from .config import SFTP_TIMEOUT, SFTP_MAX_RETRIES, SFTP_RETRY_DELAY
from modules.gpg.handler import encrypt_file, GPGEncryptError


class SFTPTransferError(Exception):
    pass


class SFTPHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_client(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        if self.params.get('strict_host_key_checking') and self.params.get('known_host_key'):
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
                f.write(self.params['known_host_key'])
                tmp_path = f.name
            try:
                client.load_host_keys(tmp_path)
            finally:
                os.unlink(tmp_path)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return client

    def _connect(self, client: paramiko.SSHClient) -> None:
        connect_kwargs = {
            'hostname': self.params['host'],
            'port': self.params['port'],
            'username': self.params['username'],
            'timeout': SFTP_TIMEOUT,
            'look_for_keys': False,
            'allow_agent': False,
        }
        if self.params.get('ssh_key'):
            connect_kwargs['pkey'] = paramiko.PKey.from_private_key(
                io.StringIO(self.params['ssh_key'])
            )
        elif self.params.get('password'):
            connect_kwargs['password'] = self.params['password']
        client.connect(**connect_kwargs)

    def execute(self, log_callback) -> None:
        if not (self.params.get('strict_host_key_checking') and self.params.get('known_host_key')):
            log_callback('warn', 'Host key verification DISABLED — connection is vulnerable to MITM')

        use_gpg = self.params.get('encrypt') and self.params.get('gpg_passphrase')
        encrypted_path = None

        try:
            if use_gpg:
                log_callback('info', 'GPG: szyfrowanie pliku...')
                try:
                    encrypted_path = encrypt_file(
                        self.params['source_path'], self.params['gpg_passphrase']
                    )
                except GPGEncryptError as e:
                    raise SFTPTransferError(str(e))
                source = encrypted_path
                dest = self.params['destination_path'] + '.gpg'
            else:
                source = self.params['source_path']
                dest = self.params['destination_path']

            last_error = None

            for attempt in range(1, SFTP_MAX_RETRIES + 1):
                client = self._build_client()
                try:
                    log_callback('info', f'Connecting to {self.params["host"]}:{self.params["port"]} (attempt {attempt})')
                    self._connect(client)
                    log_callback('info', 'Authentication OK')
                    try:
                        log_callback('info', f'Transferring: {source}')
                        with client.open_sftp() as sftp:
                            def _progress(done: int, total: int) -> None:
                                if total:
                                    log_callback('info', f'Progress: {int(done / total * 100)}%')
                            sftp.put(source, dest, callback=_progress)
                        log_callback('info', 'Transfer complete')
                        return
                    except FileNotFoundError:
                        raise SFTPTransferError(f'SOURCE NOT FOUND: {source}')
                    except OSError as e:
                        if 'No space' in str(e):
                            raise SFTPTransferError('INSUFFICIENT SPACE ON DESTINATION')
                        raise SFTPTransferError(f'TRANSFER ERROR — {e}')
                except paramiko.AuthenticationException:
                    raise SFTPTransferError('AUTH FAILED — check credentials')
                except (socket.timeout, socket.gaierror) as e:
                    last_error = str(e)
                    if attempt < SFTP_MAX_RETRIES:
                        log_callback('warn', f'Connection failed, retrying in {SFTP_RETRY_DELAY}s...')
                        time.sleep(SFTP_RETRY_DELAY)
                except paramiko.SSHException as e:
                    raise SFTPTransferError(f'SSH ERROR — {e}')
                finally:
                    client.close()

            raise SFTPTransferError(f'CONNECTION TIMEOUT — {self.params["host"]} unreachable')
        finally:
            if encrypted_path and os.path.exists(encrypted_path):
                os.unlink(encrypted_path)
```

- [ ] **Step 4: Uruchom wszystkie testy SFTP — upewnij się że PASS**

```bash
cd services/web && python -m pytest ../worker/tests/test_sftp_handler.py -v
```

Oczekiwane: wszystkie PASSED (stare + 2 nowe)

- [ ] **Step 5: Commit**

```bash
git add services/worker/modules/sftp/handler.py services/worker/tests/test_sftp_handler.py
git commit -m "feat: integrate GPG encryption into SFTPHandler"
```

---

## Task 4: RsyncHandler — integracja GPG

**Files:**
- Modify: `services/worker/modules/rsync/handler.py`
- Modify: `services/worker/tests/test_rsync_handler.py`

- [ ] **Step 1: Napisz testy (RED) — dopisz do `TestRsyncHandler`**

Na końcu klasy `TestRsyncHandler` w `services/worker/tests/test_rsync_handler.py` dodaj:

```python
    def test_execute_with_encrypt_uses_encrypted_paths(self):
        params = self._make_params(encrypt=True, gpg_passphrase='secret123')
        encrypted_tmp = '/tmp/data_abc.gpg'

        with patch('modules.rsync.handler.encrypt_file', return_value=encrypted_tmp) as mock_encrypt, \
             patch('modules.rsync.handler.os.path.exists', return_value=True), \
             patch('modules.rsync.handler.os.unlink') as mock_unlink, \
             patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter([])
            mock_proc.wait.return_value = 0
            MockPopen.return_value = mock_proc

            RsyncHandler(params).execute(log_callback=lambda lvl, msg: None)

            mock_encrypt.assert_called_once_with(params['source_path'], params['gpg_passphrase'])
            cmd = MockPopen.call_args[0][0]
            assert encrypted_tmp in cmd
            expected_dest = f'{params["username"]}@{params["host"]}:{params["destination_path"]}.gpg'
            assert expected_dest in cmd
            mock_unlink.assert_called_once_with(encrypted_tmp)

    def test_cleanup_encrypted_file_even_on_transfer_error(self):
        params = self._make_params(encrypt=True, gpg_passphrase='secret123')
        encrypted_tmp = '/tmp/data_abc.gpg'

        with patch('modules.rsync.handler.encrypt_file', return_value=encrypted_tmp), \
             patch('modules.rsync.handler.os.path.exists', return_value=True), \
             patch('modules.rsync.handler.os.unlink') as mock_unlink, \
             patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['Permission denied\n'])
            mock_proc.wait.return_value = 255
            MockPopen.return_value = mock_proc

            with pytest.raises(RsyncTransferError):
                RsyncHandler(params).execute(log_callback=lambda lvl, msg: None)

            mock_unlink.assert_called_once_with(encrypted_tmp)
```

- [ ] **Step 2: Uruchom testy — upewnij się że FAIL**

```bash
cd services/web && python -m pytest ../worker/tests/test_rsync_handler.py::TestRsyncHandler::test_execute_with_encrypt_uses_encrypted_paths ../worker/tests/test_rsync_handler.py::TestRsyncHandler::test_cleanup_encrypted_file_even_on_transfer_error -v
```

Oczekiwane: FAIL

- [ ] **Step 3: Zaktualizuj `rsync/handler.py`**

```python
# services/worker/modules/rsync/handler.py
import os
import shlex
import subprocess
import time
from typing import Callable

from .config import (
    RSYNC_BASE_FLAGS,
    RSYNC_COMPRESS_FLAG,
    RSYNC_MAX_RETRIES,
    RSYNC_RETRY_DELAY,
    RSYNC_TIMEOUT,
)
from modules.gpg.handler import encrypt_file, GPGEncryptError


class RsyncTransferError(Exception):
    pass


class RsyncHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_ssh_options(self) -> str:
        port = int(self.params['port'])
        if not (1 <= port <= 65535):
            raise ValueError(f'Invalid SSH port: {port}')
        opts = [f'-p {port}', '-o BatchMode=yes']
        if not self.params.get('strict_host_key_checking', True):
            opts.append('-o StrictHostKeyChecking=no')
        if self.params.get('ssh_key'):
            opts.append(f'-i {shlex.quote(self.params["ssh_key"])}')
        return ' '.join(opts)

    def _build_command(self, source_override=None, dest_override=None) -> list:
        source = source_override or self.params['source_path']
        dest = dest_override or self.params['destination_path']
        cmd = ['rsync'] + list(RSYNC_BASE_FLAGS)
        if self.params.get('compress'):
            cmd.append(RSYNC_COMPRESS_FLAG)
        ssh_opts = self._build_ssh_options()
        cmd += ['-e', f'ssh {ssh_opts}']
        cmd.append(source)
        cmd.append(f'{self.params["username"]}@{self.params["host"]}:{dest}')
        return cmd

    def execute(self, log_callback: Callable[[str, str], None]) -> None:
        use_gpg = self.params.get('encrypt') and self.params.get('gpg_passphrase')
        encrypted_path = None

        try:
            if use_gpg:
                log_callback('info', 'GPG: szyfrowanie pliku...')
                try:
                    encrypted_path = encrypt_file(
                        self.params['source_path'], self.params['gpg_passphrase']
                    )
                except GPGEncryptError as e:
                    raise RsyncTransferError(str(e))
                source = encrypted_path
                dest = self.params['destination_path'] + '.gpg'
            else:
                source = None
                dest = None

            cmd = self._build_command(source_override=source, dest_override=dest)
            last_exit_code = None

            for attempt in range(1, RSYNC_MAX_RETRIES + 1):
                log_callback('info', f'Starting rsync (attempt {attempt}): {" ".join(cmd)}')
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                output_lines = []
                try:
                    for line in proc.stdout:
                        line = line.rstrip()
                        output_lines.append(line)
                        if line:
                            log_callback('info', line)
                    last_exit_code = proc.wait()
                finally:
                    if hasattr(proc.stdout, 'close'):
                        proc.stdout.close()
                    proc.wait()
                full_output = '\n'.join(output_lines)

                if last_exit_code == 0:
                    log_callback('info', 'Transfer complete')
                    return

                if 'Permission denied' in full_output or last_exit_code == 255:
                    raise RsyncTransferError('AUTH FAILED — check credentials')
                if 'No space left' in full_output:
                    raise RsyncTransferError('INSUFFICIENT SPACE ON DESTINATION')
                if 'No such file' in full_output:
                    raise RsyncTransferError(f'SOURCE NOT FOUND: {self.params["source_path"]}')

                if attempt < RSYNC_MAX_RETRIES:
                    log_callback('warn', f'rsync failed (exit {last_exit_code}), retrying in {RSYNC_RETRY_DELAY}s...')
                    time.sleep(RSYNC_RETRY_DELAY)

            raise RsyncTransferError(
                f'TRANSFER FAILED — rsync failed after {RSYNC_MAX_RETRIES} attempts (last exit code: {last_exit_code})'
            )
        finally:
            if encrypted_path and os.path.exists(encrypted_path):
                os.unlink(encrypted_path)
```

- [ ] **Step 4: Uruchom wszystkie testy rsync — upewnij się że PASS**

```bash
cd services/web && python -m pytest ../worker/tests/test_rsync_handler.py -v
```

Oczekiwane: wszystkie PASSED (stare + 2 nowe)

- [ ] **Step 5: Commit**

```bash
git add services/worker/modules/rsync/handler.py services/worker/tests/test_rsync_handler.py
git commit -m "feat: integrate GPG encryption into RsyncHandler"
```

---

## Task 5: tasks.py — parametr `gpg_passphrase` i WARN dla scheduled

**Files:**
- Modify: `services/worker/tasks.py`
- Modify: `services/worker/tests/test_tasks.py`

- [ ] **Step 1: Napisz test (RED) — dopisz do `TestExecuteTransferTask`**

Na końcu klasy `TestExecuteTransferTask` w `services/worker/tests/test_tasks.py` dodaj:

```python
    def test_scheduled_transfer_logs_warn_when_encrypt_true_but_no_passphrase(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog') as MockLog, \
             patch('tasks._create_job_from_schedule') as MockCreate:
            mock_job = MagicMock()
            mock_job.flow_id = None
            mock_job.connection.protocol = 'sftp'
            mock_job.connection.encrypt = True
            mock_job.pk = 1
            MockCreate.return_value = mock_job
            MockSFTP.return_value.execute.return_value = None

            logged = []
            MockLog.objects.create.side_effect = lambda **kw: logged.append((kw['level'], kw['message']))

            from tasks import execute_transfer
            execute_transfer(job_id=None, scheduled_id=5)

            warn_messages = [msg for lvl, msg in logged if lvl == 'warn']
            assert any('GPG' in msg for msg in warn_messages)

            # gpg_passphrase=None w params przekazanych do handlera
            handler_params = MockSFTP.call_args[0][0]
            assert handler_params.get('gpg_passphrase') is None
```

- [ ] **Step 2: Uruchom test — upewnij się że FAIL**

```bash
cd services/web && python -m pytest ../worker/tests/test_tasks.py::TestExecuteTransferTask::test_scheduled_transfer_logs_warn_when_encrypt_true_but_no_passphrase -v
```

Oczekiwane: FAIL

- [ ] **Step 3: Zaktualizuj `tasks.py` — `_build_params` i `execute_transfer`**

Zmień sygnaturę `_build_params`:

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
    }
```

Zmień sygnaturę `execute_transfer` i blok `else` (gdy `not job.flow_id`):

```python
@app.task(bind=True, name='transfers.execute')
def execute_transfer(self, job_id: int = None, scheduled_id: int = None, gpg_passphrase: str = None):
    # ... (reszta kodu bez zmian aż do bloku else)
    
    # w bloku else (gdy not job.flow_id):
    else:
        if job.connection.encrypt and not gpg_passphrase:
            log_callback('warn', 'GPG: brak hasła — transfer bez szyfrowania')
        params = _build_params(job, gpg_passphrase=gpg_passphrase)
        handler_cls = SFTPHandler if job.connection.protocol == 'sftp' else RsyncHandler
        handler_cls(params).execute(log_callback=log_callback)
```

Pełna zaktualizowana funkcja `execute_transfer` (tylko zmienione fragmenty — zachowaj całą resztę):

```python
@app.task(bind=True, name='transfers.execute')
def execute_transfer(self, job_id: int = None, scheduled_id: int = None, gpg_passphrase: str = None):
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
            if job.connection.encrypt and not gpg_passphrase:
                log_callback('warn', 'GPG: brak hasła — transfer bez szyfrowania')
            params = _build_params(job, gpg_passphrase=gpg_passphrase)
            handler_cls = SFTPHandler if job.connection.protocol == 'sftp' else RsyncHandler
            handler_cls(params).execute(log_callback=log_callback)
        job.mark_done()
        send_notification.delay(job.pk)
    except (SFTPTransferError, RsyncTransferError, RelayTransferError) as e:
        job.mark_failed(str(e))
        send_notification.delay(job.pk)
        log_callback('error', str(e))
        logger.error(f'Transfer job {job.pk} failed: {e}')
    except Exception as e:
        job.mark_failed(f'UNEXPECTED ERROR — {e}')
        send_notification.delay(job.pk)
        log_callback('error', f'UNEXPECTED ERROR — {e}')
        logger.error(f'Transfer job {job.pk} unexpected error: {e}')
        raise
```

- [ ] **Step 4: Uruchom wszystkie testy tasks — upewnij się że PASS**

```bash
cd services/web && python -m pytest ../worker/tests/test_tasks.py -v
```

Oczekiwane: wszystkie PASSED (stare + 1 nowy)

- [ ] **Step 5: Commit**

```bash
git add services/worker/tasks.py services/worker/tests/test_tasks.py
git commit -m "feat: add gpg_passphrase param to execute_transfer task"
```

---

## Task 6: Warstwa web — formularz, widok + Dockerfile

**Files:**
- Modify: `services/web/apps/transfers/forms.py`
- Modify: `services/web/apps/transfers/views.py`
- Modify: `services/worker/Dockerfile`

- [ ] **Step 1: Zaktualizuj `forms.py`**

```python
# services/web/apps/transfers/forms.py
from django import forms
from .models import TransferJob
from apps.connections.models import Connection


class TransferForm(forms.ModelForm):
    gpg_passphrase = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'off'}),
        label='GPG Passphrase',
    )

    class Meta:
        model = TransferJob
        fields = ['connection', 'source_path', 'destination_path']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['connection'].queryset = Connection.objects.filter(owner=user)
```

- [ ] **Step 2: Zaktualizuj `views.py`**

```python
# services/web/apps/transfers/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from .models import TransferJob, STATUS_RUNNING
from .forms import TransferForm
from .tasks import execute_transfer


@login_required
def transfer_create(request):
    form = TransferForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        job = form.save(commit=False)
        job.owner = request.user
        job.save()
        passphrase = form.cleaned_data.get('gpg_passphrase') or None
        execute_transfer.delay(job_id=job.pk, gpg_passphrase=passphrase)
        return redirect('transfers:detail', pk=job.pk)
    return render(request, 'transfers/create.html', {'form': form})


@login_required
def transfer_detail(request, pk):
    job = get_object_or_404(
        TransferJob.objects.select_related('connection', 'flow', 'flow__source_conn', 'flow__dest_conn'),
        pk=pk, owner=request.user,
    )
    return render(request, 'transfers/create.html', {'job': job})


@login_required
def log_fragment(request, pk):
    job = get_object_or_404(TransferJob, pk=pk, owner=request.user)
    logs = job.logs.all()
    still_running = job.status == STATUS_RUNNING
    return render(request, 'transfers/log_fragment.html', {
        'job': job, 'logs': logs, 'still_running': still_running
    })


@login_required
def transfer_logs(request):
    jobs = TransferJob.objects.filter(owner=request.user).select_related('connection', 'flow')
    return render(request, 'logs/list.html', {'jobs': jobs})
```

- [ ] **Step 3: Uruchom testy web — upewnij się że PASS**

```bash
cd services/web && python -m pytest apps/transfers/tests/ -v
```

Oczekiwane: wszystkie PASSED

- [ ] **Step 4: Dodaj `gnupg` do `services/worker/Dockerfile`**

Znajdź linię `apt-get install` w `services/worker/Dockerfile` i dodaj `gnupg`. Przykład (dostosuj do aktualnej zawartości):

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    rsync \
    gnupg \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 5: Uruchom pełny suite testów worker**

```bash
cd services/web && python -m pytest ../worker/tests/ -v
```

Oczekiwane: ~100 PASSED, 0 FAILED

- [ ] **Step 6: Uruchom pełny suite testów web**

```bash
cd services/web && python -m pytest -v
```

Oczekiwane: ~100 PASSED, 0 FAILED

- [ ] **Step 7: Commit końcowy**

```bash
git add services/web/apps/transfers/forms.py \
        services/web/apps/transfers/views.py \
        services/worker/Dockerfile
git commit -m "feat: add GPG passphrase field to transfer form and wire to task"
```
