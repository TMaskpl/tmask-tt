# Design: GPG encrypt=True

**Data:** 2026-05-23  
**Status:** zatwierdzony  
**Dotyczy:** tmask-transporter Post-MVP

---

## Cel

Szyfrowanie symetryczne pliku lokalnie przez GPG (AES-256) tuż przed transferem SSH. Hasło podawane ręcznie przy każdym transferze manualnym — nie jest zapisywane w bazie ani logach. Odbiorca odszyfrowuje plik standardowym `gpg --decrypt`.

## Zasięg

- Protokoły: SFTP i rsync (oba)
- Transfery manualne: szyfrowanie aktywne gdy `connection.encrypt=True` i podano passphrase
- Transfery zaplanowane (Celery Beat): brak passphrase → transfer bez szyfrowania + WARN w logu
- Relay flow (Flow): poza zasięgiem — brak single source of truth dla passphrase

## Architektura

```
[source_path] → GPG encrypt → [/tmp/<name>.gpg] → SFTP/rsync → [dest_path.gpg] → cleanup /tmp
```

Szyfrowanie zachodzi na workerze. Plik tymczasowy tworzony przez `tempfile.mkstemp()`, usuwany w bloku `finally` — zawsze, nawet przy błędzie transferu.

## Nowe komponenty

### `services/worker/modules/gpg/`

```
modules/gpg/
├── __init__.py
├── config.py      # GPG_CIPHER_ALGO = 'AES256', GPG_TIMEOUT = 300
└── handler.py     # encrypt_file(source_path, passphrase) -> str
```

**Interfejs `encrypt_file`:**

```python
class GPGEncryptError(Exception):
    pass

def encrypt_file(source_path: str, passphrase: str) -> str:
    """
    Szyfruje plik symetrycznie AES-256.
    Zwraca ścieżkę do zaszyfrowanego pliku tymczasowego.
    Caller odpowiada za os.unlink() zwróconej ścieżki.
    Rzuca GPGEncryptError przy błędzie.
    """
```

**Wywołanie GPG CLI:**

```
gpg --batch --yes --symmetric
    --cipher-algo AES256
    --passphrase-fd 0
    --output /tmp/<stem>_<uuid>.gpg
    <source_path>
```

Passphrase przekazywana przez `stdin` (`--passphrase-fd 0`) — nigdy jako argument procesu.

### `services/worker/Dockerfile`

Dodanie `gnupg` do istniejącej linii `apt-get install`:

```dockerfile
RUN apt-get install -y ... gnupg
```

## Zmodyfikowane komponenty

### `services/worker/tasks.py`

`execute_transfer` przyjmuje nowy opcjonalny parametr:

```python
@app.task(bind=True, name='transfers.execute')
def execute_transfer(self, job_id=None, scheduled_id=None, gpg_passphrase=None):
```

`_build_params()` rozszerzony o `gpg_passphrase`:

```python
def _build_params(job, gpg_passphrase=None) -> dict:
    ...
    'gpg_passphrase': gpg_passphrase,
```

Scheduled transfer z `encrypt=True` i brak passphrase:

```python
if conn.encrypt and not gpg_passphrase:
    log_callback('warn', 'GPG: brak hasła — transfer bez szyfrowania')
```

### `services/worker/modules/sftp/handler.py`

Wzorzec GPG w `execute()`:

```python
def execute(self, log_callback):
    encrypt = self.params.get('encrypt') and self.params.get('gpg_passphrase')
    encrypted_path = None
    try:
        if encrypt:
            log_callback('info', 'GPG: szyfrowanie pliku...')
            encrypted_path = encrypt_file(
                self.params['source_path'], self.params['gpg_passphrase']
            )
            source = encrypted_path
            dest = self.params['destination_path'] + '.gpg'
        else:
            source = self.params['source_path']
            dest = self.params['destination_path']
        # ... istniejąca logika sftp.put(source, dest)
    finally:
        if encrypted_path and os.path.exists(encrypted_path):
            os.unlink(encrypted_path)
```

`RsyncHandler` — ten sam wzorzec: GPG krok przed budowaniem komendy rsync, cleanup w `finally`.

### `services/web/apps/transfers/forms.py`

Nowe pole (nie model field):

```python
gpg_passphrase = forms.CharField(
    required=False,
    widget=forms.PasswordInput(attrs={'autocomplete': 'off'}),
    label='GPG Passphrase',
)
```

### `services/web/apps/transfers/views.py`

Pobranie passphrase z formularza i przekazanie do taska:

```python
passphrase = form.cleaned_data.get('gpg_passphrase') or None
job = form.save(commit=False)
job.owner = request.user
job.save()
execute_transfer.delay(job.pk, gpg_passphrase=passphrase)
```

### `services/web/templates/transfers/create.html`

Brak zmian — pole `gpg_passphrase` renderuje się przez istniejącą pętlę `{% for field in form %}` i otrzymuje styling CRT automatycznie.

## Bezpieczeństwo

| Ryzyko | Mitygacja |
|--------|-----------|
| Passphrase widoczna w `ps aux` | `--passphrase-fd 0` — stdin, nie arg |
| Passphrase w logach | Nie logujemy `gpg_passphrase` nigdzie |
| Temp plik pozostaje po błędzie | `finally: os.unlink()` zawsze |
| Temp plik z szerokimi uprawnieniami | `tempfile.mkstemp()` tworzy plik 600 |
| Passphrase w Redis (Celery args) | Akceptowalne — Redis lokalny, szyfrowany transport wewnętrzny |

## Testy

### Nowy plik: `services/worker/tests/test_gpg_handler.py`

| Test | Co weryfikuje |
|------|---------------|
| `test_encrypt_file_success` | Zaszyfrowany plik istnieje, ma > 0 bajtów |
| `test_encrypted_file_is_not_plaintext` | Zawartość != oryginał |
| `test_missing_source_raises` | `GPGEncryptError` gdy plik źródłowy nie istnieje |
| `test_cleanup_on_error` | Temp plik usunięty gdy GPG zwróci błąd |

### Rozszerzenia: `test_sftp_handler.py`

| Test | Co weryfikuje |
|------|---------------|
| `test_execute_with_encrypt` | `encrypt_file` wywołane, source/dest zmienione na `.gpg` |
| `test_cleanup_called_on_transfer_error` | `os.unlink` wywołany nawet gdy `sftp.put` rzuca |

### Rozszerzenia: `test_rsync_handler.py`

| Test | Co weryfikuje |
|------|---------------|
| `test_execute_with_encrypt` | `encrypt_file` wywołane, komenda rsync używa `.gpg` ścieżek |
| `test_cleanup_called_on_transfer_error` | `os.unlink` wywołany nawet gdy rsync zwróci błąd |

### Rozszerzenia: `test_tasks.py`

| Test | Co weryfikuje |
|------|---------------|
| `test_scheduled_transfer_skips_gpg_with_warn` | Scheduled + encrypt=True + brak passphrase → WARN, brak `encrypt_file` |

**Oczekiwany wynik:** ~100 passing (obecnie 91).

## Ograniczenia znane

- Passphrase przechodzi przez Redis jako argument Celery — akceptowalne dla środowiska lokalnego
- Relay flow (Flow) nie obsługuje GPG w tej wersji
- Scheduled transfers z `encrypt=True` wykonują transfer bez szyfrowania (WARN w logu)
- Brak weryfikacji czy GPG jest zainstalowane — `GPGEncryptError` z czytelnym komunikatem przy braku
