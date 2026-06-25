# Relay Checksum (SHA-256) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać weryfikację integralności SHA-256 dla transferów relay (Flow, SFTP→SFTP), domykając lukę względem istniejącej weryfikacji SFTP/rsync.

**Architecture:** Nowa funkcja `verify_relay` liczy `sha256sum` na hoście źródłowym i docelowym przez SSH i porównuje. Sterowana nowym polem `verify_checksum` na modelu `Flow`. `RelayHandler` wywołuje ją po każdym przesłanym pliku; rozbieżność → `RelayTransferError` (fail-fast, plik docelowy nie kasowany).

**Tech Stack:** Python 3.12, Django 5.x, paramiko, Celery, pytest. Kod uruchamiany w kontenerach Docker (`worker`, `web`).

## Global Constraints

- Testy uruchamiane w kontenerach: worker → `docker compose exec -T worker python -m pytest ...`, web → `docker compose exec -T web python -m pytest ...`. Stack musi być uruchomiony (`docker compose up -d`).
- Polecenia uruchamiać z katalogu projektu: `/Users/dniemczok/Desktop/TMaskPL/tmask-tt`.
- TDD: najpierw czerwony test, potem minimalna implementacja.
- Commity: prefiks `feat:`/`fix:`/`test:`, opis po polsku, stopka `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Praca na gałęzi `feat/relay-checksum` (już utworzona, spec zacommitowany).
- Zakres SHA-256, fail-fast, brak GPG w relay — zgodnie ze spec `docs/superpowers/specs/2026-06-25-relay-checksum-design.md`.

---

### Task 1: Funkcja `verify_relay` + helper `_remote_sha256` (worker/checksum)

**Files:**
- Modify: `services/worker/modules/checksum/handler.py`
- Test: `services/worker/tests/test_checksum_handler.py`

**Interfaces:**
- Consumes: istniejące `_local_sha256`, `ChecksumVerificationError`, `verify_sftp`.
- Produces:
  - `_remote_sha256(ssh_client, remote_path: str) -> str` — uruchamia `sha256sum` przez `ssh_client.exec_command`, waliduje exit status i pusty output, zwraca sam hash.
  - `verify_relay(src_client, src_path: str, dst_client, dst_path: str, log_callback) -> None` — liczy hash na obu hostach zdalnych, porównuje, rzuca `ChecksumVerificationError` przy rozbieżności.

- [ ] **Step 1: Napisz czerwone testy `TestVerifyRelay`**

Dodaj na końcu `services/worker/tests/test_checksum_handler.py` (helper `_make_client` mirror istniejącego z `TestVerifySftp`):

```python
class TestVerifyRelay:
    def _make_client(self, stdout_content: bytes, stderr_content: bytes = b"", exit_status: int = 0):
        mock_client = MagicMock()
        mock_chan = MagicMock()
        mock_chan.recv_exit_status.return_value = exit_status
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = stdout_content
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = stderr_content
        mock_client.exec_command.return_value = (mock_chan, mock_stdout, mock_stderr)
        return mock_client

    def test_ok_when_hashes_match(self):
        sha = "a" * 64
        src_client = self._make_client(f"{sha}  /src/file.bin\n".encode())
        dst_client = self._make_client(f"{sha}  /dst/file.bin\n".encode())
        logs = []
        from modules.checksum.handler import verify_relay
        verify_relay(src_client, "/src/file.bin", dst_client, "/dst/file.bin",
                     lambda lvl, msg: logs.append(msg))
        assert any("SHA-256 OK" in m for m in logs)

    def test_raises_on_mismatch(self):
        src_client = self._make_client(f"{'a' * 64}  /src/file.bin\n".encode())
        dst_client = self._make_client(f"{'b' * 64}  /dst/file.bin\n".encode())
        from modules.checksum.handler import verify_relay
        with pytest.raises(ChecksumVerificationError, match="MISMATCH"):
            verify_relay(src_client, "/src/file.bin", dst_client, "/dst/file.bin",
                         lambda lvl, msg: None)

    def test_raises_when_source_sha256sum_fails(self):
        src_client = self._make_client(b"", b"sha256sum: not found", exit_status=1)
        dst_client = self._make_client(f"{'a' * 64}  /dst/file.bin\n".encode())
        from modules.checksum.handler import verify_relay
        with pytest.raises(ChecksumVerificationError, match="sha256sum failed"):
            verify_relay(src_client, "/src/file.bin", dst_client, "/dst/file.bin",
                         lambda lvl, msg: None)

    def test_raises_when_dest_sha256sum_fails(self):
        src_client = self._make_client(f"{'a' * 64}  /src/file.bin\n".encode())
        dst_client = self._make_client(b"", b"read error", exit_status=1)
        from modules.checksum.handler import verify_relay
        with pytest.raises(ChecksumVerificationError, match="sha256sum failed"):
            verify_relay(src_client, "/src/file.bin", dst_client, "/dst/file.bin",
                         lambda lvl, msg: None)

    def test_raises_on_empty_output(self):
        src_client = self._make_client(b"", exit_status=0)
        dst_client = self._make_client(f"{'a' * 64}  /dst/file.bin\n".encode())
        from modules.checksum.handler import verify_relay
        with pytest.raises(ChecksumVerificationError, match="sha256sum failed"):
            verify_relay(src_client, "/src/file.bin", dst_client, "/dst/file.bin",
                         lambda lvl, msg: None)
```

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose exec -T worker python -m pytest tests/test_checksum_handler.py::TestVerifyRelay -q`
Expected: FAIL — `ImportError: cannot import name 'verify_relay'`

- [ ] **Step 3: Wydziel `_remote_sha256` i dodaj `verify_relay`**

W `services/worker/modules/checksum/handler.py` zastąp obecną funkcję `verify_sftp` (linie 21-33) poniższym blokiem (dodaje helper, refaktoryzuje `verify_sftp`, dodaje `verify_relay`):

```python
def _remote_sha256(ssh_client, remote_path: str) -> str:
    chan, stdout, stderr = ssh_client.exec_command(f'sha256sum {shlex.quote(remote_path)}')
    output = stdout.read().decode().strip()
    exit_status = chan.recv_exit_status()
    if exit_status != 0 or not output:
        raise ChecksumVerificationError(f'sha256sum failed: {stderr.read().decode().strip()}')
    return output.split()[0]


def verify_sftp(source_path: str, ssh_client, remote_path: str, log_callback) -> None:
    local_hash = _local_sha256(source_path)
    remote_hash = _remote_sha256(ssh_client, remote_path)
    if local_hash != remote_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: local={local_hash[:16]}... remote={remote_hash[:16]}...'
        )
    log_callback('info', f'SHA-256 OK: {local_hash[:16]}...')


def verify_relay(src_client, src_path: str, dst_client, dst_path: str, log_callback) -> None:
    src_hash = _remote_sha256(src_client, src_path)
    dst_hash = _remote_sha256(dst_client, dst_path)
    if src_hash != dst_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: source={src_hash[:16]}... dest={dst_hash[:16]}...'
        )
    log_callback('info', f'SHA-256 OK: {src_hash[:16]}...')
```

- [ ] **Step 4: Uruchom testy modułu checksum — wszystkie zielone (regresja `verify_sftp`)**

Run: `docker compose exec -T worker python -m pytest tests/test_checksum_handler.py -q`
Expected: PASS — wszystkie testy `TestVerifyRelay` + niezmienione `TestVerifySftp`/`TestVerifyRsync`/`TestLocalSha256`

- [ ] **Step 5: Commit**

```bash
git add services/worker/modules/checksum/handler.py services/worker/tests/test_checksum_handler.py
git commit -m "$(cat <<'EOF'
feat: verify_relay liczący sha256sum na dwóch hostach zdalnych

Wydziela _remote_sha256, refaktoryzuje verify_sftp bez zmiany zachowania.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Integracja weryfikacji w `RelayHandler` (worker/relay)

**Files:**
- Modify: `services/worker/modules/relay/handler.py`
- Test: `services/worker/tests/test_relay_handler.py`

**Interfaces:**
- Consumes: `verify_relay`, `ChecksumVerificationError` z Task 1; `RelayTransferError`.
- Produces: `RelayHandler` weryfikuje każdy plik po transferze gdy `source_params['verify_checksum']` jest prawdziwe; rozbieżność → `RelayTransferError` (fail-fast w pętli katalogu).

- [ ] **Step 1: Napisz czerwone testy integracji**

Dodaj do klasy `TestRelayHandler` w `services/worker/tests/test_relay_handler.py` (używa istniejących helperów `_setup_two_clients`, fixture `relay_params`):

```python
    def test_verify_called_when_enabled(self, relay_params):
        relay_params[0]['verify_checksum'] = True
        sha = "a" * 64
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.verify_relay') as mock_verify:
            mock_src_client, mock_dst_client, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)
            mock_src_sftp.stat.return_value = _file_stat(size=10)
            from modules.relay.handler import RelayHandler
            RelayHandler(*relay_params).execute(log_callback=lambda lvl, msg: None)
            mock_verify.assert_called_once()

    def test_verify_skipped_when_disabled(self, relay_params):
        relay_params[0]['verify_checksum'] = False
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.verify_relay') as mock_verify:
            mock_src_client, mock_dst_client, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)
            mock_src_sftp.stat.return_value = _file_stat(size=10)
            from modules.relay.handler import RelayHandler
            RelayHandler(*relay_params).execute(log_callback=lambda lvl, msg: None)
            mock_verify.assert_not_called()

    def test_mismatch_raises_relay_error_single_file(self, relay_params):
        relay_params[0]['verify_checksum'] = True
        from modules.checksum.handler import ChecksumVerificationError
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.verify_relay',
                   side_effect=ChecksumVerificationError('SHA-256 MISMATCH: ...')):
            mock_src_client, mock_dst_client, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)
            mock_src_sftp.stat.return_value = _file_stat(size=10)
            from modules.relay.handler import RelayHandler, RelayTransferError
            with pytest.raises(RelayTransferError, match="MISMATCH"):
                RelayHandler(*relay_params).execute(log_callback=lambda lvl, msg: None)

    def test_mismatch_directory_fail_fast(self, relay_params):
        relay_params[0]['verify_checksum'] = True
        from modules.checksum.handler import ChecksumVerificationError
        with patch('modules.relay.handler.paramiko.SSHClient') as MockSSH, \
             patch('modules.relay.handler.verify_relay',
                   side_effect=ChecksumVerificationError('SHA-256 MISMATCH: ...')):
            mock_src_client, mock_dst_client, mock_src_sftp, mock_dst_sftp = _setup_two_clients(MockSSH)
            # źródło to katalog z 3 plikami
            mock_src_sftp.stat.return_value = _dir_stat()
            entries = []
            for i in range(3):
                e = _file_stat(size=10)
                e.filename = f'file{i}.bin'
                entries.append(e)
            mock_src_sftp.listdir_attr.return_value = entries
            from modules.relay.handler import RelayHandler, RelayTransferError
            with pytest.raises(RelayTransferError, match="MISMATCH"):
                RelayHandler(*relay_params).execute(log_callback=lambda lvl, msg: None)
            # fail-fast: tylko pierwszy plik przesłany przed przerwaniem
            assert mock_dst_sftp.putfo.call_count + mock_dst_sftp.put.call_count == 1
```

> Helpery `_file_stat(size=10)` (zwraca MagicMock z `st_mode=stat_module.S_IFREG`, `st_size`) oraz `_dir_stat()` (`st_mode=stat_module.S_IFDIR`) już istnieją w pliku (linie 41-51), podobnie fixture `relay_params` (zwraca krotkę `(source, dest)` — `relay_params[0]` to mutowalny dict źródła). Nie trzeba ich tworzyć.

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose exec -T worker python -m pytest tests/test_relay_handler.py -q -k "verify or mismatch"`
Expected: FAIL — `verify_relay` niezaimportowane w `modules.relay.handler` (`AttributeError`/`ImportError`)

- [ ] **Step 3: Dodaj import i flagę w `RelayHandler`**

W `services/worker/modules/relay/handler.py` dodaj import po linii 6 (`import paramiko`):

```python
from modules.checksum.handler import verify_relay, ChecksumVerificationError
```

Na początku metody `execute` (zaraz po `def execute(self, log_callback) -> None:`, przed `source_client = self._build_client(...)`) wstaw zapis flagi i referencji klientów. Zamień linie:

```python
        source_client = self._build_client(self.source_params)
        dest_client = self._build_client(self.dest_params)
```

na:

```python
        self._verify = bool(self.source_params.get('verify_checksum'))
        source_client = self._build_client(self.source_params)
        dest_client = self._build_client(self.dest_params)
        self._src_client = source_client
        self._dst_client = dest_client
```

- [ ] **Step 4: Dodaj weryfikację w `_transfer_file`**

W `services/worker/modules/relay/handler.py`, w metodzie `_transfer_file`, wewnątrz bloku `try`, bezpośrednio po bloku `if size > ... / else` (po `dst_sftp.putfo(buf, dst_path)`), a przed `except RelayTransferError:` — dodaj:

```python
            if getattr(self, '_verify', False):
                try:
                    verify_relay(self._src_client, src_path, self._dst_client, dst_path, log_callback)
                except ChecksumVerificationError as e:
                    raise RelayTransferError(str(e))
```

> `getattr(..., False)` chroni przed wywołaniem `_transfer_file` bez wcześniejszej inicjalizacji w `execute` (np. w izolowanych testach jednostkowych metody).

- [ ] **Step 5: Uruchom testy relay — zielone**

Run: `docker compose exec -T worker python -m pytest tests/test_relay_handler.py -q`
Expected: PASS — nowe testy weryfikacji + niezmienione istniejące testy relay

- [ ] **Step 6: Commit**

```bash
git add services/worker/modules/relay/handler.py services/worker/tests/test_relay_handler.py
git commit -m "$(cat <<'EOF'
feat: weryfikacja SHA-256 po transferze w RelayHandler

Wywołuje verify_relay po każdym pliku gdy verify_checksum włączone.
Fail-fast: rozbieżność przerywa transfer katalogu.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Pole `verify_checksum` na modelu `Flow` + migracja + formularz + UI (web)

**Files:**
- Modify: `services/web/apps/flows/models.py`
- Create: `services/web/apps/flows/migrations/0002_flow_verify_checksum.py` (przez `makemigrations`)
- Modify: `services/web/apps/flows/forms.py:10`
- Modify: `services/web/templates/flows/form.html`
- Test: `services/web/apps/flows/tests/test_models.py`

**Interfaces:**
- Consumes: model `Flow`, fixtures `regular_user`, `make_connection`.
- Produces: `Flow.verify_checksum` (BooleanField, default False); pole w `FlowForm`; checkbox w UI.

- [ ] **Step 1: Napisz czerwony test domyślnej wartości pola**

Dodaj do klasy `TestFlowModel` w `services/web/apps/flows/tests/test_models.py`:

```python
    def test_verify_checksum_defaults_false(self, regular_user, make_connection):
        src = make_connection(regular_user, name='S', host='10.0.0.1')
        dst = make_connection(regular_user, name='D', host='10.0.0.2')
        flow = Flow.objects.create(
            owner=regular_user, name='Flow',
            source_conn=src, source_path='/a',
            dest_conn=dst, dest_path='/b',
        )
        assert flow.verify_checksum is False
```

- [ ] **Step 2: Uruchom test — sprawdź że pada**

Run: `docker compose exec -T web python -m pytest apps/flows/tests/test_models.py::TestFlowModel::test_verify_checksum_defaults_false -q`
Expected: FAIL — `AttributeError: 'Flow' object has no attribute 'verify_checksum'`

- [ ] **Step 3: Dodaj pole do modelu**

W `services/web/apps/flows/models.py` dodaj pole po linii `dest_path` (linia 14), przed `created_at`:

```python
    verify_checksum = models.BooleanField(default=False)
```

- [ ] **Step 4: Wygeneruj i zastosuj migrację**

Run:
```bash
docker compose exec -T web python manage.py makemigrations flows
docker compose exec -T web python manage.py migrate flows
```
Expected: utworzony `0002_flow_verify_checksum.py`, migracja zastosowana OK.

- [ ] **Step 5: Uruchom test modelu — zielony**

Run: `docker compose exec -T web python -m pytest apps/flows/tests/test_models.py -q`
Expected: PASS — wszystkie testy `TestFlowModel`

- [ ] **Step 6: Dodaj pole do formularza**

W `services/web/apps/flows/forms.py` zamień linię 10:

```python
        fields = ['name', 'source_conn', 'source_path', 'dest_conn', 'dest_path']
```

na:

```python
        fields = ['name', 'source_conn', 'source_path', 'dest_conn', 'dest_path', 'verify_checksum']
```

- [ ] **Step 7: Dodaj checkbox do UI**

W `services/web/templates/flows/form.html` wstaw przed blokiem przycisków (przed `<div style="display:flex;gap:1rem;margin-top:1.5rem;">`, ~linia 60):

```html
    <div class="field" style="margin-top:1.2rem;">
      <label>WERYFIKACJA SHA-256:</label>
      {{ form.verify_checksum }}
      <span style="font-size:0.75rem;color:var(--dim);">Po transferze porównuje sha256sum na hoście źródłowym i docelowym. Transfer = błąd przy rozbieżności.</span>
      {% if form.verify_checksum.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.verify_checksum.errors }}</div>{% endif %}
    </div>
```

- [ ] **Step 8: Uruchom pełny zestaw testów flows — zielony**

Run: `docker compose exec -T web python -m pytest apps/flows/ -q`
Expected: PASS — testy modeli i widoków flows niezmienione + nowy test

- [ ] **Step 9: Commit**

```bash
git add services/web/apps/flows/models.py services/web/apps/flows/migrations/0002_flow_verify_checksum.py services/web/apps/flows/forms.py services/web/templates/flows/form.html services/web/apps/flows/tests/test_models.py
git commit -m "$(cat <<'EOF'
feat: pole verify_checksum na modelu Flow + formularz + UI

Checkbox per-Flow włączający weryfikację SHA-256 dla transferów relay.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Przekazanie flagi do paramów relay + pełny zestaw testów (worker/tasks)

**Files:**
- Modify: `services/worker/tasks.py:42-57`
- Test: `services/worker/tests/test_tasks.py`

**Interfaces:**
- Consumes: `Flow.verify_checksum` (Task 3), `_build_relay_params`.
- Produces: `source_params` zwracane przez `_build_relay_params` zawierają klucz `verify_checksum` = `flow.verify_checksum`.

- [ ] **Step 1: Napisz czerwony test wiring**

Dodaj do `services/worker/tests/test_tasks.py` (mirror istniejącego stylu testów `_build_relay_params`; jeśli plik nie testuje jeszcze tej funkcji, dodaj nową klasę):

```python
class TestBuildRelayParamsVerifyChecksum:
    def test_verify_checksum_passed_to_source_params(self):
        from unittest.mock import MagicMock
        from tasks import _build_relay_params
        flow = MagicMock()
        flow.verify_checksum = True
        flow.source_path = '/src/a'
        flow.dest_path = '/dst/b'
        for conn in (flow.source_conn, flow.dest_conn):
            conn.port = 22
            conn.strict_host_key_checking = False
            conn.known_host_key = ''
        source_params, dest_params = _build_relay_params(flow)
        assert source_params['verify_checksum'] is True
```

- [ ] **Step 2: Uruchom test — sprawdź że pada**

Run: `docker compose exec -T worker python -m pytest tests/test_tasks.py::TestBuildRelayParamsVerifyChecksum -q`
Expected: FAIL — `KeyError: 'verify_checksum'`

- [ ] **Step 3: Przekaż flagę w `_build_relay_params`**

W `services/worker/tasks.py` zmień `_build_relay_params` tak, by `source_params` niosło flagę. Po linii `source_params = _conn_params(flow.source_conn, flow.source_path, flow.source_path)` (linia 55) dodaj:

```python
    source_params['verify_checksum'] = flow.verify_checksum
```

(Wynikowy fragment:)

```python
    source_params = _conn_params(flow.source_conn, flow.source_path, flow.source_path)
    dest_params = _conn_params(flow.dest_conn, flow.source_path, flow.dest_path)
    source_params['verify_checksum'] = flow.verify_checksum
    return source_params, dest_params
```

- [ ] **Step 4: Uruchom test wiring — zielony**

Run: `docker compose exec -T worker python -m pytest tests/test_tasks.py::TestBuildRelayParamsVerifyChecksum -q`
Expected: PASS

- [ ] **Step 5: Pełny zestaw testów worker + web — wszystko zielone**

Run:
```bash
docker compose exec -T worker python -m pytest -q
docker compose exec -T web python -m pytest -q
```
Expected: PASS — brak regresji w obu serwisach.

- [ ] **Step 6: Commit**

```bash
git add services/worker/tasks.py services/worker/tests/test_tasks.py
git commit -m "$(cat <<'EOF'
feat: przekaż flow.verify_checksum do paramów relay

Domyka end-to-end weryfikację SHA-256 dla transferów Flow.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Po wdrożeniu (poza planem TDD)

- Rebuild obrazów wymagany dla worker (zmiana kodu) i web (zmiana modeli/templatek/migracji) przed testem manualnym: `docker compose build worker web && docker compose up -d && docker compose exec -T web python manage.py migrate`.
- Aktualizacja dokumentacji w vault Obsidian: `11-Apps/CSCS/tmask-transporter/Projekt-tmask-transporter.md` (oznaczyć SHA-256 dla relay + odnotować, że SFTP/rsync było już zrobione) oraz `Propozycje rozbudowy.md` (status #6). Wpis do `LOG.md`.
