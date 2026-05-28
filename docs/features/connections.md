# Connections — Połączenia SSH

> Zarządzanie konfiguracjami połączeń SSH używanych przez transfery, harmonogram i Flows.

## Tworzenie połączenia

Panel → `[ NEW CONNECTION ]`. Każde połączenie należy do zalogowanego użytkownika — inni użytkownicy go nie widzą.

## Pola konfiguracyjne

| Pole                         | Opis                                                      | Domyślnie   |
|------------------------------|-----------------------------------------------------------|-------------|
| **NAME**                     | Etykieta wyświetlana w listach                            | —           |
| **HOST**                     | Adres hosta (IP lub FQDN)                                 | —           |
| **PORT**                     | Port SSH                                                  | `22`        |
| **USERNAME**                 | Login SSH                                                 | —           |
| **PASSWORD**                 | Hasło SSH (szyfrowane Fernet w DB)                        | opcjonalne  |
| **SSH KEY**                  | Klucz prywatny PEM (Ed25519, RSA, ECDSA — szyfrowany w DB)| opcjonalne  |
| **PROTOCOL**                 | `SFTP/SCP` lub `rsync`                                    | `SFTP/SCP`  |
| **COMPRESS**                 | Kompresja SSH (`-C` w rsync)                              | ❌          |
| **ENCRYPT**                  | GPG szyfrowanie transferów z tego połączenia              | ❌          |
| **STRICT HOST KEY CHECKING** | Weryfikacja klucza hosta (zabezpiecza przed MITM)         | ✅          |
| **KNOWN HOST KEY**           | Klucz hosta w formacie `known_hosts`                      | opcjonalne  |
| **DRY RUN BEFORE TRANSFER**  | rsync `--dry-run` przed właściwym transferem              | ❌          |
| **VERIFY CHECKSUM**          | rsync `--checksum` (dokładne porównanie treści)           | ❌          |

## Weryfikacja klucza hosta (STRICT HOST KEY)

Gdy `STRICT HOST KEY CHECKING = True` (zalecane):

1. W trybie edycji połączenia kliknij `[ SCAN HOST KEY ]`
2. Aplikacja łączy się SSH i zwraca klucz hosta w formacie `known_hosts`
3. Skopiowany klucz pojawia się w polu `KNOWN HOST KEY` — zweryfikuj go manualnie
4. Po zapisaniu worker weryfikuje klucz przy każdym transferze (`-o StrictHostKeyChecking=yes`)

> Gdy `STRICT = True` ale brak klucza → transfer nie zostanie wykonany (fail-closed, CWE-295).
> Gdy `STRICT = False` → worker loguje ostrzeżenie MITM, ale transfer wykonuje.

## Testowanie połączenia

Przed zapisem lub w dowolnym momencie kliknij `[ TEST CONNECTION ]`:
- Próba połączenia SSH z podanymi danymi uwierzytelniającymi
- Wynik: `CONNECTION SUCCESSFUL` lub szczegółowy błąd SSH

## Protokoły transferu

### SFTP/SCP (domyślny)

- Biblioteka **Paramiko** — `PKey.from_private_key()` auto-detekcja formatu klucza
- Obsługuje: password auth, key auth (RSA, Ed25519, ECDSA)
- Retry: `SFTP_MAX_RETRIES=3`, `SFTP_RETRY_DELAY`, `SFTP_TIMEOUT` (konfig w `sftp/config.py`)

### rsync

- Wywołanie systemowego `rsync` przez SSH (`subprocess`)
- `shlex.quote()` na ścieżce klucza SSH — ochrona przed shell injection
- `UserKnownHostsFile` przez temp plik gdy strict_host_key=True
- Flagi bazowe konfigurowane w `modules/rsync/config.py`

## Bezpieczeństwo przechowywania danych

- Hasła i klucze SSH szyfrowane **Fernet AES-256** (`django-encrypted-model-fields`)
- Klucz Fernet w `.env` jako `FIELD_ENCRYPTION_KEY` — nigdy w repozytorium
- Baza przechowuje zaszyfrowany blob, nie plaintext

## Kod źródłowy

| Zasób          | Ścieżka                                              |
|----------------|------------------------------------------------------|
| Model          | `services/web/apps/connections/models.py`            |
| Formularz      | `services/web/apps/connections/forms.py`             |
| Widoki         | `services/web/apps/connections/views.py`             |
| SFTP handler   | `services/worker/modules/sftp/handler.py`            |
| rsync handler  | `services/worker/modules/rsync/handler.py`           |
| Relay handler  | `services/worker/modules/relay/handler.py`           |
| Testy          | `services/web/apps/connections/tests/`               |
