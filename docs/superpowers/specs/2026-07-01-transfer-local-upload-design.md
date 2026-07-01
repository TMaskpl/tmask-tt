# Upload pliku z lokalnej maszyny w formularzu transferu — Design

**Data:** 2026-07-01
**Status:** zatwierdzony

## Cel

W formularzu „NEW TRANSFER" pole „LOCAL ./TRANSFERS" przestaje być polem
tekstowym (nazwa pliku, który musi już leżeć w `/transfers` na serwerze) i staje
się **wyborem pliku z komputera przeglądającego stronę**. Plik jest uploadowany
przez przeglądarkę, kontener `web` zapisuje go do współdzielonego wolumenu
`/transfers`, a `worker` czyta go bez żadnych zmian w swojej logice.

## Kontekst obecny

- Pole `source_path` w `TransferForm` (label „Local ./transfers") przyjmuje samą
  nazwę pliku i w `clean_source_path` składa `/transfers/<nazwa>`.
- Wolumen `./transfers:/transfers` jest zamontowany **tylko w serwisie `worker`**
  (docker-compose.yml). Kontener `web` go nie widzi.
- Aby wysłać plik, użytkownik musi dziś ręcznie umieścić go w `./transfers` na
  hoście (scp / docker cp), a potem wpisać nazwę w formularzu.
- Nginx: `client_max_body_size 100m` jest już ustawione (`nginx/nginx.conf:6`).

## Decyzje (zatwierdzone)

1. **Tylko upload** — pole tekstowe znika, zostaje wyłącznie wybór pliku
   lokalnego. Bez wariantu „wpisz nazwę pliku na serwerze".
2. **Limit 100 MB** na pojedynczy plik.
3. **Nadpisanie** przy kolizji nazw w `/transfers` (najnowszy upload wygrywa).

## Architektura zmian

### 1. docker-compose.yml
Dodać `- ./transfers:/transfers` do wolumenów serwisu `web`. Enabler całej
funkcji: `web` musi zapisywać do tego samego katalogu, z którego czyta `worker`.

### 2. config/settings/base.py
Stałe:
- `TRANSFERS_DIR = '/transfers'`
- `MAX_UPLOAD_BYTES = 100 * 1024 * 1024`

Django domyślnie strumieniuje pliki > `FILE_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB) do
`TemporaryUploadedFile` na dysku, więc 100 MB nie ląduje w RAM. `source_path` (plik
uploadowany) jest wykluczony z `DATA_UPLOAD_MAX_MEMORY_SIZE`, więc nie trzeba go
podnosić.

### 3. transfers/forms.py
- Usunąć `source_path` z `Meta.fields` i przestać przyjmować go od użytkownika.
- Dodać `upload = forms.FileField(label='Local file')`.
- `clean_upload`:
  - `if uploaded.size > settings.MAX_UPLOAD_BYTES: ValidationError('Plik przekracza 100 MB.')`
  - nazwa pliku (`uploaded.name`) przez istniejące `_validate_source_filename`
    (blokuje `/`, `\`, `..`, znaki kontrolne, wiodący `-`)
- `source_path` NIE jest już polem formularza; ustawiany w widoku na
  `f'{settings.TRANSFERS_DIR}/{nazwa}'`.

### 4. transfers/views.py
W `transfer_create`, po `form.is_valid()`:
- `uploaded = form.cleaned_data['upload']`
- zapis chunkami do `os.path.join(settings.TRANSFERS_DIR, uploaded.name)` w trybie
  `'wb'` (nadpisanie przy kolizji)
- `job.source_path = f'{settings.TRANSFERS_DIR}/{uploaded.name}'`
- reszta bez zmian: `job.owner`, `job.save()`, dispatch `transfers.execute` w
  `transaction.on_commit`.
- Błąd zapisu na dysk → komunikat błędu, brak dispatchu.

### 5. templates/transfers/create.html
- Formularz z `enctype="multipart/form-data"`.
- Pole `upload` renderowane jako file-picker w stylu `.field-with-btn`:
  przycisk `[ WYBIERZ ]` (label dla ukrytego `input[type=file]`), obok pole
  wyświetlające wybraną nazwę (reuse handlera `data-file-display` z `browser.js`,
  dodanego przy imporcie w Profilu).
- `destination_path` z przyciskiem `[BROWSE]` — bez zmian.

## Obsługa błędów

| Sytuacja | Zachowanie |
|----------|-----------|
| Plik > 100 MB | Błąd walidacji formularza, transfer nie startuje |
| Nazwa z `/`, `..`, znakami kontrolnymi | Błąd walidacji (istniejąca funkcja) |
| Kolizja nazw w /transfers | Ciche nadpisanie |
| Błąd zapisu na dysk (I/O) | Komunikat błędu, brak dispatchu |
| Nginx odrzuca > 100m (413) | Odpowiedź serwera WWW zanim dojdzie do Django |

## Testy

**forms.py:**
- upload w granicach limitu → `is_valid()` True, `source_path` = `/transfers/<nazwa>`
- upload > 100 MB → błąd walidacji
- nazwa z `../` / `/` → błąd walidacji (traversal)

**views.py:**
- POST z plikiem → plik zapisany w katalogu, `job.source_path` ustawiony, job
  wysłany (mock `send_task`)
- POST z plikiem o istniejącej nazwie → nadpisanie (nowa zawartość na dysku)

Katalog docelowy w testach: `settings.TRANSFERS_DIR` nadpisany na `tmp_path`
(pytest) — nie zapisujemy do prawdziwego `/transfers`.

## Poza zakresem

- Transfery Flow/relay (używają `flow.source_path`) — bez zmian.
- Izolacja plików per-użytkownik w /transfers — zaakceptowano wspólny katalog z
  nadpisywaniem.
- Automatyczne czyszczenie starych plików z /transfers.
