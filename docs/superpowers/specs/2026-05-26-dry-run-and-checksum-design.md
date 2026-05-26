# Dry-run przed rsync + Weryfikacja SHA-256 — Design Spec

**Data:** 2026-05-26  
**Status:** zatwierdzony  
**Estymacja:** ~4-5h, ~17 nowych testów

## Cel

Dwie niezależne funkcje poprawiające niezawodność transferów:

1. **Dry-run przed rsync** — wykonanie `rsync --dry-run` przed właściwym transferem; anuluje transfer jeśli dry-run zakończy się błędem
2. **Weryfikacja SHA-256 po transferze** — porównanie skrótu SHA-256 pliku źródłowego i docelowego po zakończeniu transferu (sftp + rsync; relay poza zakresem)

## Zakres

- Oba ustawienia per-Connection (toggle boolean)
- Dry-run tylko dla rsync (SFTP i relay ignorują tę flagę)
- SHA-256 dla sftp i rsync; relay poza zakresem tej sesji
- SHA-256 pomijane gdy GPG/encrypt włączone (log warn)

## Model danych

Dwa nowe pola na `apps.connections.Connection` (migracja `0004_dry_run_and_checksum`):

```python
dry_run_before_transfer = models.BooleanField(default=False)
verify_checksum         = models.BooleanField(default=False)
```

`_build_params()` w `services/worker/tasks.py` przekazuje oba do handlerów:

```python
'dry_run':        conn.dry_run_before_transfer,
'verify_checksum': conn.verify_checksum,
```

`_build_relay_params()` pozostaje bez zmian — relay ignoruje oba pola.

## Sekcja 1: Dry-run (RsyncHandler)

### `services/worker/modules/rsync/handler.py`

`_build_command()` dostaje nowy parametr `dry_run: bool = False`:

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

W `execute()`, przed pętlą retry — jeśli `params['dry_run']` jest True:

```python
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
```

**Kolejność z GPG:** GPG encrypt → dry-run (na zaszyfrowanym pliku) → prawdziwy transfer → GPG temp cleanup.

**Retry:** dry-run wykonywany raz, poza pętlą retry. Tylko właściwy rsync ma retry.

## Sekcja 2: SHA-256 (nowy moduł + SFTPHandler + RsyncHandler)

### Nowy moduł `services/worker/modules/checksum/`

**`__init__.py`** — pusty

**`handler.py`:**

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
        raise ChecksumVerificationError(f'Remote sha256sum failed: {result.stderr.strip()}')
    remote_hash = result.stdout.strip().split()[0]
    if local_hash != remote_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: local={local_hash[:16]}... remote={remote_hash[:16]}...'
        )
    log_callback('info', f'SHA-256 OK: {local_hash[:16]}...')
```

### `services/worker/modules/sftp/handler.py` — zmiany

`_transfer_once()` dostaje nowy parametr `use_gpg: bool = False`:

```python
def _transfer_once(self, source: str, dest: str, log_callback, use_gpg: bool = False) -> None:
```

`execute()` przekazuje go przy wywołaniu:

```python
self._transfer_once(source, dest, log_callback, use_gpg=use_gpg)
```

Wewnątrz `_transfer_once()`, po `sftp.put()` (klient jeszcze otwarty):

```python
with client.open_sftp() as sftp:
    sftp.put(source, dest, callback=_progress)

if self.params.get('verify_checksum') and not use_gpg:
    from modules.checksum.handler import verify_sftp, ChecksumVerificationError
    try:
        verify_sftp(source, client, dest, log_callback)
    except ChecksumVerificationError as e:
        raise SFTPTransferError(str(e))
elif self.params.get('verify_checksum') and use_gpg:
    log_callback('warn', 'SHA-256: pomijane — GPG włączone (encrypted file)')
```

### `services/worker/modules/rsync/handler.py` — zmiany

Nowa metoda `_build_ssh_cmd_prefix()`:

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

W `execute()`, wewnątrz pętli retry po `last_exit_code == 0`:

```python
if last_exit_code == 0:
    log_callback('info', 'Transfer complete')
    if self.params.get('verify_checksum') and not use_gpg:
        from modules.checksum.handler import verify_rsync, ChecksumVerificationError
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

## Sekcja 3: Konfiguracja — formularze i szablony

### `services/web/apps/connections/forms.py`

```python
fields = [
    'name', 'host', 'port', 'username', 'password', 'ssh_key',
    'protocol', 'compress', 'encrypt', 'strict_host_key_checking',
    'known_host_key',
    'dry_run_before_transfer',
    'verify_checksum',
]
labels = {
    ...
    'dry_run_before_transfer': 'Dry-run przed transferem (tylko rsync)',
    'verify_checksum':         'Weryfikuj integralność SHA-256 po transferze',
}
```

### Template połączenia

Nowa sekcja `[ OPCJE ZAAWANSOWANE ]` poniżej `compress` / `encrypt`:

```
[ OPCJE ZAAWANSOWANE ]
☐ DRY-RUN PRZED TRANSFEREM (tylko rsync)
   > Sprawdza listę plików bez kopiowania; transfer anulowany jeśli dry-run zakończy się błędem

☐ WERYFIKUJ INTEGRALNOŚĆ SHA-256 PO TRANSFERZE
   > Po transferze porównuje skrót SHA-256 pliku źródłowego i docelowego
   > Wymaga sha256sum na zdalnym hoście; ignorowane gdy GPG włączone
```

## Obsługa błędów

| Scenariusz | Zachowanie |
|-----------|------------|
| Dry-run exit != 0 | `RsyncTransferError` — transfer anulowany, job marked failed |
| `dry_run=True` na SFTP | Flaga zignorowana — transfer wykonywany normalnie |
| SHA-256 mismatch | `SFTPTransferError` / `RsyncTransferError` — job marked failed |
| `sha256sum` niedostępne na zdalnym hoście | `ChecksumVerificationError` → `TransferError` — job marked failed |
| GPG + verify_checksum | Log warn "SHA-256: pomijane — GPG włączone", transfer OK |
| Relay + oba pola | Oba pola ignorowane (relay params nie zawierają tych kluczy) |

## Testy

### `services/worker/tests/test_rsync_handler.py` — klasa `TestRsyncDryRun`

| Test | Opis |
|------|------|
| `test_dry_run_command_includes_flag` | `_build_command(dry_run=True)` zawiera `--dry-run` |
| `test_dry_run_runs_before_real_transfer` | Mock `_run_attempt` — 2 wywołania, pierwsze z `--dry-run` |
| `test_dry_run_failure_aborts_transfer` | Dry-run exit=1 → `RsyncTransferError`, drugi `_run_attempt` nie wywołany |
| `test_dry_run_skipped_when_disabled` | `dry_run=False` → `_run_attempt` wywołany raz |

### `services/worker/tests/test_checksum_handler.py` — nowy plik

| Test | Opis |
|------|------|
| `test_local_sha256_returns_correct_hash` | Znany content → znany SHA-256 |
| `test_local_sha256_reads_in_chunks` | Mock `open` — wielokrotne `read()` |
| `test_verify_sftp_ok_when_hashes_match` | Mock `exec_command` → zgodny hash, log "SHA-256 OK" |
| `test_verify_sftp_raises_on_mismatch` | Inny hash zdalny → `ChecksumVerificationError` |
| `test_verify_sftp_raises_when_sha256sum_missing` | Puste stdout → `ChecksumVerificationError` |
| `test_verify_rsync_ok_when_hashes_match` | Mock `subprocess.run` returncode=0, zgodny hash |
| `test_verify_rsync_raises_on_mismatch` | Inny hash → `ChecksumVerificationError` |
| `test_verify_rsync_raises_on_nonzero_exit` | returncode=1 → `ChecksumVerificationError` |

### `services/worker/tests/test_sftp_handler.py` — klasa `TestSFTPChecksumVerification`

| Test | Opis |
|------|------|
| `test_calls_verify_sftp_after_transfer` | `verify_checksum=True` → `verify_sftp` wywołany |
| `test_skips_verify_when_disabled` | `verify_checksum=False` → `verify_sftp` nie wywołany |
| `test_raises_transfer_error_on_mismatch` | `verify_sftp` rzuca → `SFTPTransferError` |
| `test_skips_verify_when_gpg_enabled` | `encrypt=True` + `verify_checksum=True` → log warn, brak weryfikacji |

### `services/web/apps/connections/tests/test_models.py` — rozszerzenie

| Test | Opis |
|------|------|
| `test_dry_run_default_false` | Nowe połączenie ma `dry_run_before_transfer=False` |
| `test_verify_checksum_default_false` | Nowe połączenie ma `verify_checksum=False` |

## Wdrożenie

```bash
docker compose run --rm web python manage.py migrate
docker compose restart worker beat
```
