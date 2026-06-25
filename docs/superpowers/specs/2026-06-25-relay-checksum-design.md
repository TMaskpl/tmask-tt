# Design: Weryfikacja SHA-256 dla transferów relay (Flow)

**Data:** 2026-06-25
**Status:** Zatwierdzony (brainstorming)
**Powiązane:** `2026-05-26-dry-run-and-checksum-design.md` (weryfikacja SHA-256 dla SFTP/rsync)

## Kontekst i problem

Weryfikacja integralności SHA-256 jest zaimplementowana i działa dla transferów **SFTP** i **rsync** (moduł `worker/modules/checksum/`, pole `Connection.verify_checksum`, integracja w handlerach, UI, 58 testów). Jedyną luką są transfery **relay (Flow)** — SFTP→SFTP bez pliku lokalnego — które nie weryfikują sumy kontrolnej.

Relay przesyła plik między dwoma hostami zdalnymi: małe pliki strumieniowo przez `BytesIO`, duże przez tymczasowy plik lokalny. `RelayHandler` trzyma jednocześnie otwarte dwa połączenia SSH (`source_client`, `dest_client`), co umożliwia policzenie `sha256sum` na obu hostach i porównanie.

## Cel

Po przesłaniu pliku w transferze relay (gdy włączone) policzyć SHA-256 na hoście źródłowym i docelowym, porównać i zgłosić błąd przy rozbieżności — analogicznie do istniejącej weryfikacji SFTP/rsync.

## Decyzje projektowe

1. **Sterowanie:** nowe pole `verify_checksum` na modelu `Flow` (jawny checkbox per-Flow). Flow ma dwa połączenia, więc reużycie `Connection.verify_checksum` byłoby niejednoznaczne; własne pole jest najczytelniejsze i niezależne od konfiguracji połączeń.
2. **Mechanizm:** `sha256sum` na obu hostach zdalnych przez SSH (`exec_command`), porównanie hashy. Spójne z istniejącymi `verify_sftp`/`verify_rsync`. Zero lokalnego I/O.
3. **Mismatch:** rzuca `RelayTransferError` → transfer = failed. Plik docelowy **nie** jest kasowany (spójne z SFTP/rsync).
4. **Katalog (wiele plików):** fail-fast — przerwanie na pierwszej rozbieżności (spójne z obecną propagacją `RelayTransferError` w pętli katalogu).
5. **GPG:** nie dotyczy relay (brak modułu GPG w ścieżce relay) — brak gałęzi pomijania.

## Komponenty i zmiany

| Warstwa | Plik | Zmiana |
|---|---|---|
| Model | `apps/flows/models.py` | nowe pole `verify_checksum = BooleanField(default=False)` |
| Migracja | `apps/flows/migrations/000X_...` | dodanie pola |
| Formularz | `apps/flows/forms.py` | `verify_checksum` w `fields` |
| UI | `templates/flows/form.html` | checkbox (styl CRT, jak per-Connection) |
| Task | `worker/tasks.py` `_build_relay_params` | `'verify_checksum': flow.verify_checksum` do `source_params` |
| Checksum | `worker/modules/checksum/handler.py` | nowa funkcja `verify_relay(...)` + wydzielony helper `_remote_sha256(client, path)` |
| Handler | `worker/modules/relay/handler.py` | weryfikacja po każdym pliku, gdy flaga włączona |

## Przepływ i logika

### `verify_relay` (checksum/handler.py)

Analogiczna do `verify_sftp`, ale liczy hash na dwóch hostach zdalnych zamiast local+remote:

```python
def verify_relay(src_client, src_path, dst_client, dst_path, log_callback) -> None:
    src_hash = _remote_sha256(src_client, src_path)
    dst_hash = _remote_sha256(dst_client, dst_path)
    if src_hash != dst_hash:
        raise ChecksumVerificationError(
            f'SHA-256 MISMATCH: source={src_hash[:16]}... dest={dst_hash[:16]}...')
    log_callback('info', f'SHA-256 OK: {src_hash[:16]}...')
```

Wspólny helper `_remote_sha256(client, path)` — `exec_command('sha256sum <quoted path>')`, sprawdzenie exit status i pustego outputu, zwraca hash. `verify_sftp` zostaje zrefaktoryzowane, by też z niego korzystać (usuwa duplikację, bez zmiany zachowania).

### Sterowanie flagą

1. `_build_relay_params` dokłada `'verify_checksum': flow.verify_checksum` do `source_params` (jedno źródło prawdy).
2. `RelayHandler.execute()` zapisuje na `self`: `self._verify = source_params.get('verify_checksum')` oraz referencje `self._src_client`/`self._dst_client` (dziś zmienne lokalne — wyniesione na `self`, bo `exec_command` wymaga `SSHClient`, nie `SFTPClient`).

### Punkt integracji

W `_transfer_file`, po udanym `dst_sftp.put/putfo`, w bloku `try` przed `finally`:

```python
if self._verify:
    try:
        verify_relay(self._src_client, src_path, self._dst_client, dst_path, log_callback)
    except ChecksumVerificationError as e:
        raise RelayTransferError(str(e))
```

Działa identycznie dla pojedynczego pliku i każdego pliku w katalogu (oba przechodzą przez `_transfer_file`).

### Obsługa błędów / fail-fast

Rozbieżność → `RelayTransferError` → propaguje w górę; pętla `_transfer_directory` przerywa się na pierwszym pliku z mismatch. Job = failed, log wskazuje plik. Plik docelowy nie jest kasowany.

## Testy (TDD)

### Worker — `test_checksum_handler.py` (nowa klasa `TestVerifyRelay`)

- `test_ok_when_hashes_match` — zgodne hashe → bez wyjątku, log `SHA-256 OK`
- `test_raises_on_mismatch` — różne hashe → `ChecksumVerificationError`
- `test_raises_when_source_sha256sum_fails` — exit ≠ 0 na źródle
- `test_raises_when_dest_sha256sum_fails` — exit ≠ 0 na destynacji
- `test_raises_on_empty_output` — pusty stdout
- (regresja) istniejące `TestVerifySftp` zielone po wydzieleniu `_remote_sha256`

### Worker — `test_relay_handler.py` (rozszerzenie `TestRelayHandler`)

- `test_verify_called_when_enabled` — `verify_checksum=True`, zgodne hashe → OK, `verify_relay` wywołane raz
- `test_verify_skipped_when_disabled` — flaga `False` → brak `exec_command('sha256sum...')`
- `test_mismatch_raises_relay_error_single_file` — rozbieżność → `RelayTransferError`
- `test_mismatch_directory_fail_fast` — katalog 3 plików, mismatch na 1. → pętla przerwana, pozostałe nie transferowane (asercja na liczbie `put`/`putfo`)

### Web — `apps/flows/tests/`

- `test_models.py` — `Flow.verify_checksum` default `False`
- `test_forms.py` — pole obecne w formularzu, zapisuje wartość
- migracja stosuje się czysto (`migrate --check` zielone)

### Kolejność TDD

Czerwone testy `verify_relay` → implementacja funkcji → czerwone testy integracji relay → integracja w handlerze → model/form/UI. Po całości: pełny zestaw worker + web zielony przed commitem.

## Poza zakresem (YAGNI)

- Weryfikacja zbiorcza z kontynuacją po mismatch (świadomie odrzucone na rzecz fail-fast)
- Algorytmy inne niż SHA-256
- Weryfikacja przy GPG w relay (relay nie używa GPG)
