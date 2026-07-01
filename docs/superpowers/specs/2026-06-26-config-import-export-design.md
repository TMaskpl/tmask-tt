# Design: Import/export konfiguracji (JSON backup)

**Data:** 2026-06-26
**Status:** Zatwierdzony (brainstorming)

## Kontekst i cel

tmask-transporter trzyma konfigurację połączeń (`Connection`) i przepływów relay (`Flow`) w bazie, z sekretami (`password`, `ssh_key`) szyfrowanymi Fernet (`FIELD_ENCRYPTION_KEY`). Brak mechanizmu backupu/migracji — `docker compose down -v` kasuje dane. Funkcja dodaje eksport całej konfiguracji użytkownika do pliku JSON i import z powrotem, z sekretami chronionymi hasłem podanym przez użytkownika (przenośne między instancjami).

## Decyzje projektowe

1. **Sekrety:** szyfrowane passphrasą użytkownika (PBKDF2-HMAC-SHA256 + Fernet, sól w pliku) — przenośne między instancjami, niezależne od `FIELD_ENCRYPTION_KEY`.
2. **Zakres:** Connections + Flows. Flows referują połączenia po **nazwie** (nie PK) — przenośne.
3. **Konflikt importu:** pomiń istniejące po nazwie (idempotentnie), zwróć licznik dodanych/pominiętych.
4. **Granularność szyfrowania:** tylko pola-sekrety (`password`, `ssh_key`) szyfrowane; reszta JSON czytelna (backup można obejrzeć/edytować).
5. **Izolacja per-user:** eksport tylko rekordów `request.user`; import zawsze `owner=request.user`.

## Komponenty

| Plik | Odpowiedzialność |
|------|------------------|
| `apps/connections/portability.py` | Rdzeń: `export_config(user, passphrase) -> dict`, `import_config(user, data, passphrase) -> ImportResult`, helpery `_derive_key`, `_encrypt_secret`, `_decrypt_secret`, wyjątek `PassphraseError`, dataclass `ImportResult` |
| `apps/connections/views.py` | `connection_export` (POST passphrase → download JSON), `connection_import` (POST plik+passphrase → messages) |
| `apps/connections/urls.py` | `connections:export`, `connections:import` |
| `templates/connections/list.html` | Przyciski `[ EXPORT ]` / `[ IMPORT ]` + mini-formularze (passphrase, plik) w stylu CRT |

## Format pliku (JSON; tylko sekrety zaszyfrowane)

```json
{
  "format": "tmask-transporter-config",
  "version": 1,
  "kdf": {"algo": "pbkdf2_sha256", "iterations": 600000, "salt": "<b64>"},
  "check": "<fernet token — szyfruje marker b'tmask-config-v1'>",
  "connections": [
    {"name": "...", "host": "...", "port": 22, "username": "...", "protocol": "sftp",
     "compress": false, "encrypt": false, "strict_host_key_checking": true,
     "known_host_key": "...", "dry_run_before_transfer": false, "verify_checksum": false,
     "password_enc": "<fernet token | null>", "ssh_key_enc": "<fernet token | null>"}
  ],
  "flows": [
    {"name": "...", "source_conn": "<nazwa poł.>", "source_path": "...",
     "dest_conn": "<nazwa poł.>", "dest_path": "...", "verify_checksum": false}
  ]
}
```

`known_host_key` jawne (publiczny klucz hosta, nie sekret).

## Krypto i przepływ

### Krypto (`portability.py`)
- `_derive_key(passphrase, salt, iterations=600000)` — PBKDF2-HMAC-SHA256, 32 bajty → `urlsafe_b64encode` → klucz Fernet.
- `_encrypt_secret(plaintext, fernet)` — `None`/puste → `None`; inaczej `fernet.encrypt(plaintext.encode()).decode()`.
- `_decrypt_secret(token, fernet)` — `None` → `None`; inaczej `fernet.decrypt(token.encode()).decode()` (zły passphrase → `InvalidToken`).
- Pole `check` = `Fernet.encrypt(b"tmask-config-v1")`; na imporcie odszyfrowywane **najpierw** → walidacja hasła zanim cokolwiek dotknie bazy (działa nawet gdy brak sekretów).

### Eksport `export_config(user, passphrase) -> dict`
1. `salt = os.urandom(16)`, wyprowadź klucz, `f = Fernet(key)`.
2. `Connection.objects.filter(owner=user)` → serializuj, `password_enc/ssh_key_enc = _encrypt_secret(...)`.
3. `Flow.objects.filter(owner=user)` → serializuj, `source_conn/dest_conn = <nazwa>`.
4. Zwróć dict + `kdf.salt` (b64) + `check`.

### Import `import_config(user, data, passphrase) -> ImportResult` (w `transaction.atomic()`)
1. Walidacja `format == "tmask-transporter-config"` i obsługiwanej `version`; wyprowadź klucz z `salt` z pliku; **odszyfruj `check`** → `InvalidToken` ⇒ `PassphraseError` (rollback).
2. `existing = {nazwy połączeń usera}`. Dla każdego connection: nazwa w `existing` → `conn_skipped++`; inaczej odszyfruj sekrety, `Connection.objects.create(owner=user, ...)`, dodaj nazwę do `existing`, `conn_added++`.
3. Zbuduj mapę `nazwa → Connection` (usera, z nowymi). `existing_flows = {nazwy flows usera}`. Dla każdego flow: nazwa w `existing_flows` → `flow_skipped++`; rozwiąż `source_conn`/`dest_conn` po nazwie — brak referencji ⇒ `flow_unresolved++` (pomiń); inaczej `Flow.objects.create(owner=user, ...)`, `flow_added++`.
4. Zwróć `ImportResult(conn_added, conn_skipped, flow_added, flow_skipped, flow_unresolved)`.

### Obsługa błędów (widok import)
- `PassphraseError` → „Błędne hasło lub uszkodzony plik".
- `json.JSONDecodeError` / zły `format`/`version` → „Nieprawidłowy plik konfiguracji".
- Limit rozmiaru pliku (1 MB) — większy → komunikat błędu.
- Flow z brakującą referencją → `unresolved`, nie błąd.
- Sukces → `messages.success`: „Dodano X połączeń (pominięto Y), Z flows (pominięto W, nierozwiązanych V)".

### Widoki
- `connection_export` — `@login_required @require_POST`; puste hasło → `messages.error` + redirect. Inaczej `JsonResponse(export_config(...))` z `Content-Disposition: attachment; filename=tmask-config-YYYY-MM-DD.json`.
- `connection_import` — `@login_required @require_POST`; czyta `request.FILES['file']` + `request.POST['passphrase']`; parsuje JSON, woła `import_config`, mapuje wynik/wyjątki na messages, redirect na `connections:list`. Passphrase nigdy nie logowany.

## Testy (TDD)

### `apps/connections/tests/test_portability.py`
- `test_export_has_format_version_and_kdf` (`format`/`version`/`kdf.salt`/`check`)
- `test_export_secrets_not_plaintext` (hasło/ssh_key nie jawnie; `password_enc` to token)
- `test_export_only_owners_records` (izolacja — eksport A pomija rekordy B)
- `test_roundtrip_restores_secrets` (export → import do świeżego usera z tym hasłem → `password`/`ssh_key` zgodne)
- `test_flow_references_resolved_by_name` (eksport ma nazwy; import wskazuje właściwe Connection)
- `test_import_wrong_passphrase_raises` (`PassphraseError`, nic nie utworzone)
- `test_import_skips_existing_by_name` (istniejąca nazwa pominięta, licznik poprawny)
- `test_flow_with_missing_connection_unresolved` (flow bez referencji → `unresolved`, pominięty)

### `apps/connections/tests/test_portability_views.py`
- `test_export_requires_login`, `test_import_requires_login`
- `test_export_returns_json_attachment` (200, `application/json`, `attachment`, body z `format`)
- `test_export_requires_passphrase` (puste hasło → błąd)
- `test_import_creates_records` (upload + hasło → rekordy z `owner=request.user`, success z licznikami)
- `test_import_wrong_passphrase_shows_error` (komunikat, brak rekordów)
- `test_import_malformed_file_shows_error` (zły JSON → komunikat)

### Kolejność TDD
Krypto + `export_config` → `import_config` (skip/resolve/passphrase) → widoki export/import → przyciski w `list.html` → weryfikacja manualna (download + re-upload na świeżym koncie).

## Poza zakresem (YAGNI)

- Selektywny eksport (wybrane połączenia) — zawsze cała konfiguracja usera
- Tryby nadpisz/duplikuj przy imporcie — tylko skip
- Eksport harmonogramów (`scheduler`), API tokenów, webhooków — tylko Connections + Flows
- Wersjonowanie/migracja starszych formatów — tylko `version: 1`
