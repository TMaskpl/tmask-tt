# Transfers — Manualne transfery plików

> Funkcja ręcznego uruchamiania transferu pliku z lokalnego wolumenu na zdalny host SSH.

## Jak uruchomić transfer

1. Zaloguj się do panelu → `[ NEW TRANSFER ]`
2. **LOCAL ./TRANSFERS** — wpisz tylko **nazwę pliku** (bez ścieżki), np. `backup.tar.gz`
   - Plik musi znajdować się w katalogu `./transfers/` na hoście Docker
   - Katalog montowany do kontenera workera jako `/transfers/`
   - Podanie pełnej ścieżki `/transfers/plik.tar` też działa — prefix zostanie ujednolicony
3. **CONNECTION** — wybierz skonfigurowane połączenie SSH (SFTP lub rsync)
4. **DESTINATION PATH** — docelowa ścieżka na serwerze zdalnym, np. `/backup/archiwum.tar.gz`
5. **GPG PASSPHRASE** (opcjonalnie) — hasło do szyfrowania pliku przed wysłaniem
6. Kliknij `[ EXECUTE TRANSFER ]`

## Jak umieścić plik do transferu

Na hoście Docker skopiuj plik do katalogu `./transfers/` (obok `docker-compose.yml`):

```bash
cp /sciezka/do/pliku.tar.gz /home/user/tmask-transporter/transfers/
```

W formularzu wpisz tylko `plik.tar.gz`.

## Statusy transferu

| Status    | Opis                                               |
|-----------|----------------------------------------------------|
| `PENDING` | Zadanie w kolejce Redis, czeka na worker           |
| `RUNNING` | Worker aktywnie przesyła plik                      |
| `DONE`    | Transfer zakończony sukcesem                       |
| `FAILED`  | Transfer nie powiódł się (szczegóły w logach)      |

## Szyfrowanie GPG (opcjonalne)

Gdy w polu **GPG PASSPHRASE** podasz hasło:

1. Worker szyfruje plik symetrycznie algorytmem **AES-256** przez GPG przed wysłaniem
2. Zaszyfrowany plik `.gpg` jest przesyłany na zdalny host (w miejscu wskazanym w DESTINATION PATH)
3. Oryginalny plik w `/transfers/` pozostaje nienaruszony
4. Plik tymczasowy `.gpg` na workerze jest usuwany po transferze (w bloku `finally`)

**Hasło nigdy nie trafia do logów ani do `ps aux`** — przekazywane przez stdin GPG (`--passphrase-fd 0`).

## Jak rozszyfrować plik na hoście docelowym

Po przesłaniu zaszyfrowanego pliku `.gpg` na serwer docelowy:

```bash
# Instalacja GPG (jeśli brak)
apt install gnupg          # Debian/Ubuntu
yum install gnupg2         # RHEL/CentOS

# Odszyfrowanie — GPG zapyta o hasło interaktywnie
gpg --output plik.tar.gz --decrypt plik.tar.gz.gpg

# Hasło przez stdin (bezpieczne w skryptach — nie widoczne w ps aux)
echo 'twoje-haslo' | gpg --batch --yes \
    --passphrase-fd 0 \
    --output plik.tar.gz \
    --decrypt plik.tar.gz.gpg
```

## Walidacja ścieżek

Formularz odrzuca niebezpieczne dane wejściowe:

| Wejście                       | Wynik                                             |
|-------------------------------|---------------------------------------------------|
| `backup.tar.gz`               | ✅ OK — zapisane jako `/transfers/backup.tar.gz`  |
| `/transfers/backup.tar.gz`    | ✅ OK — prefix ujednolicony                        |
| `/data/plik.tar`              | ❌ Błąd — niedozwolony `/` w nazwie pliku          |
| `-rf plik.tar`                | ❌ Błąd — niedozwolone `-` na początku             |
| `../etc/passwd` (dest)        | ❌ Błąd — sekwencja `..` niedozwolona              |
| `plik\x00.tar`                | ❌ Błąd — znaki kontrolne niedozwolone             |

## Kod źródłowy

| Zasób          | Ścieżka                                                    |
|----------------|------------------------------------------------------------|
| Model          | `services/web/apps/transfers/models.py`                    |
| Formularz      | `services/web/apps/transfers/forms.py`                     |
| Widoki         | `services/web/apps/transfers/views.py`                     |
| Celery task    | `services/worker/tasks.py` — `execute_transfer`            |
| GPG handler    | `services/worker/modules/gpg/handler.py` — `encrypt_file()`|
| Testy          | `services/web/apps/transfers/tests/`                       |
| Testy GPG      | `services/worker/tests/test_gpg_handler.py`                |
