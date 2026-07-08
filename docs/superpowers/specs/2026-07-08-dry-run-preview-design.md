# Design: Podgląd dry-run rsync przed transferem

**Data:** 2026-07-08
**Status:** Zatwierdzony (brainstorming)

## Kontekst i problem

Roadmapa (`Propozycje rozbudowy.md`, punkt #5) opisuje przycisk `[DRY RUN]`
pokazujący użytkownikowi, co zostanie przesłane/nadpisane, **przed**
wykonaniem transferu. To nie istnieje.

Coś podobnego już jest w kodzie, ale to inny mechanizm: `Connection.dry_run_before_transfer`
(checkbox per-Connection) + logika w `RsyncHandler.execute()`
(`services/worker/modules/rsync/handler.py:121-133`) — gdy włączone, przed
**każdym** realnym transferem przez to połączenie odpala się cichy
pre-flight `rsync --dry-run` (fail-fast, jeśli rsync by się nie powiódł), po
czym **automatycznie** kontynuuje do prawdziwego transferu w tym samym
jobie. Użytkownik widzi tylko log `"Dry-run OK — kontynuuję transfer"`,
nigdy treść dry-run. Ten mechanizm zostaje bez zmian — nowa funkcja to
osobna, interaktywna akcja.

Ograniczenie techniczne odkryte podczas brainstormingu: binarka `rsync`
i cała logika budowania/uruchamiania komendy (`RsyncHandler`) istnieją
wyłącznie w obrazie **workera** (`services/worker/Dockerfile`). Obraz
**web** (`services/web/Dockerfile`) nie ma `rsync`/`openssh-client` — ma
tylko `libpq-dev gcc`. `paramiko` (użyty synchronicznie przez istniejący
przycisk `[TEST]` w `apps/connections/views.py::connection_test`) nie
wystarcza — `rsync --dry-run` to osobny proces uruchamiany przez
`subprocess`, nie operacja SSH-only. Stąd: podgląd **musi** iść przez
Celery/worker, nie może być czysto synchroniczny jak `[TEST]`.

## Cel

Nowy przycisk `[DRY RUN]` na formularzu "New Transfer" — używa dokładnie
tych danych, które użytkownik właśnie wypełnił (połączenie, upload, ścieżka
docelowa), pokazuje output `rsync --dry-run` **bez** wykonania transferu.
Dostępny tylko dla połączeń z `protocol == 'rsync'`.

## Decyzje projektowe

1. **Umiejscowienie:** formularz "New Transfer" (`transfers/create.html`),
   nie strona Connection — bo `Connection` nie przechowuje `source_path`/
   `destination_path` (te są per-transfer), więc podgląd musi operować na
   danych aktualnie wypełnionych w formularzu transferu.
2. **Wykonanie:** asynchroniczne przez Celery, reużywając istniejącej
   logiki `RsyncHandler` (wydzielonej do nowej metody `preview()`) zamiast
   duplikować `rsync`/`openssh-client` w obrazie web. UI polluje wynik
   przez HTMX, korzystając z już skonfigurowanego
   `CELERY_RESULT_BACKEND='django-db'` (`services/web/config/settings/base.py:102`)
   — zero nowego modelu do przechowywania wyniku.
3. **Brak `TransferJob`:** dry-run **nie tworzy** rekordu `TransferJob`.
   Alternatywa (reużycie `TransferJob` z nowym statusem `'preview'`) była
   rozważana i odrzucona — wymagałaby filtrowania preview'ów wszędzie tam,
   gdzie `TransferJob` jest dziś agregowany (dashboard, lista transferów,
   API `GET /api/jobs/<id>/status/`).
4. **Reużycie pliku po dry-run:** brak. `[DRY RUN]` i `[TRANSFER]` to dwa
   niezależne submity tego samego formularza — każdy wysyła własny
   multipart POST z plikiem wybranym w danej chwili w file pickerze. Plik
   zapisany podczas samego dry-run (bez następującego `[TRANSFER]`) zostaje
   w `/transfers` jako zwykły osierocony upload — sprząta go **już
   istniejący** periodic task retencji (`transfers.cleanup_old_transfers`,
   punkt #11 roadmapy), bez żadnego nowego mechanizmu czyszczenia.
5. **Błędy rsync to nie `FAILURE` taska:** `RsyncHandler.preview()` i task
   `dry_run_preview` **nie rzucają** wyjątku przy niezerowym exit code
   rsync (np. connection refused, permission denied) — zwracają
   `{'exit_code': N, 'output': ...}` zawsze. Cały sens podglądu to pokazanie
   problemu *przed* wydaniem zasobów na prawdziwy transfer; task Celery w
   stanie `FAILURE` zgubiłby czytelny tekst błędu rsync na rzecz
   generycznego tracebacku.
6. **GPG:** jeśli `connection.encrypt=True` i podano `gpg_passphrase`,
   podgląd szyfruje plik przed dry-run (spójne z istniejącym zachowaniem
   embedded pre-flight w `execute()`, które robi to samo) — user widzi
   dokładnie to, co faktycznie poszłoby na wire.
7. **Walidacja protokołu:** dwie warstwy — JS chowa/wyłącza przycisk
   `[DRY RUN]` gdy wybrane połączenie ma `protocol != 'rsync'` (ten sam
   wzorzec co istniejący komunikat "tylko rsync" przy
   `dry_run_before_transfer`), plus walidacja server-side w widoku jako
   druga linia obrony (nie w `TransferForm.clean()`, bo `TransferForm` musi
   nadal akceptować SFTP dla zwykłego `[TRANSFER]`).
8. **`log_callback` bez `TransferLog`:** `preview()` przyjmuje `log_callback`
   z tym samym sygnaturą co `execute()` (dla reużycia `_run_attempt` bez
   zmian), ale dry-run nie ma `TransferJob`/`TransferLog`, więc nie ma gdzie
   trwale zapisać logu na żywo. `dry_run_preview` (task) przekazuje
   `log_callback`, który loguje przez `logger.info`/`logger.warning` (log
   workera, do debugowania operacyjnego) — **nie** do bazy. Cały tekst
   istotny dla użytkownika i tak wraca w `output` zwróconym przez
   `_run_attempt` (linia po linii, złączone). Wyjątek: ostrzeżenie "Host key
   verification DISABLED" w `execute()` jest emitowane osobnym wywołaniem
   `log_callback` *przed* zbudowaniem komendy, więc nie trafia do `output`
   z `_run_attempt` automatycznie — `preview()` musi je **jawnie
   dopisać na początek zwracanego `output`**, gdy dotyczy, żeby użytkownik
   zobaczył je w podglądzie, a nie tylko w logu serwera.

## Komponenty i zmiany

| Warstwa | Plik | Zmiana |
|---|---|---|
| Handler | `services/worker/modules/rsync/handler.py` | nowa metoda publiczna `preview(self, log_callback) -> dict` — buduje komendę przez `_build_command(dry_run=True, ...)`, uruchamia przez `_run_attempt`, zwraca `{'exit_code': int, 'output': str}`; nie rzuca `RsyncTransferError` |
| Task | `services/worker/tasks.py` | nowy `@app.task(name='transfers.dry_run_preview')` `dry_run_preview(connection_id, source_path, destination_path, gpg_passphrase=None)` — buduje params z `Connection.objects.get(pk=connection_id)`, łapie `Connection.DoesNotExist`, GPG-enkoduje gdy dotyczy, deleguje do `RsyncHandler(params).preview(...)` |
| Widok | `services/web/apps/transfers/views.py` | `transfer_dry_run(request)` (`@require_role(ROLE_OPERATOR)`, POST) — waliduje `TransferForm`, zapisuje upload do `/transfers` (identyczny kod co `transfer_create`), sprawdza `form.cleaned_data['connection'].protocol == 'rsync'` (błąd formularza jeśli nie), dispatch `dry_run_preview`, zwraca `task_id`; `transfer_dry_run_status(request, task_id)` (`@require_role(ROLE_OPERATOR)`, GET) — `AsyncResult(task_id)`, renderuje fragment wg stanu |
| URL | `services/web/apps/transfers/urls.py` | `path('dry-run/', transfer_dry_run, name='dry_run')`, `path('dry-run/<str:task_id>/status/', transfer_dry_run_status, name='dry_run_status')` |
| Template | `services/web/templates/transfers/create.html` | drugi przycisk submit `[DRY RUN]` (HTMX `hx-post` na `dry_run` URL, `hx-target` na kontener wyniku), JS `protocol != 'rsync'` → `disabled`/hidden na przycisku, kontener HTMX polling (`hx-get` na `dry_run_status`, `hx-trigger="load delay:1s"`, self-referencing dopóki nie `SUCCESS`/`FAILURE`) |
| Fragment | `services/web/templates/transfers/_dry_run_result.html` | nowy — render PENDING (spinner) / SUCCESS `exit_code==0` (zielona ramka, output) / SUCCESS `exit_code!=0` (czerwona ramka, output) / FAILURE (czerwony generyczny komunikat) |

## Testy (TDD)

### Worker — `tests/test_rsync_handler.py` (nowa klasa `TestRsyncHandlerPreview`)

- `test_returns_exit_code_and_output_on_success` — mock `_run_attempt` zwraca `(0, "...")` → `preview()` zwraca `{'exit_code': 0, 'output': "..."}`
- `test_returns_nonzero_exit_code_instead_of_raising` — mock `_run_attempt` zwraca `(23, "rsync error: ...")` → `preview()` zwraca dict z `exit_code=23`, **nie** rzuca `RsyncTransferError`
- `test_uses_dry_run_flag_in_command` — assert `_build_command` wywołane z `dry_run=True`
- `test_does_not_execute_real_transfer` — assert `_run_attempt` (lub `subprocess.run`) wywołane dokładnie raz, z komendą zawierającą `--dry-run`
- `test_prepends_host_key_warning_when_verification_disabled` — `strict_host_key_checking=False` → zwrócony `output` zaczyna się od tekstu ostrzeżenia o wyłączonej weryfikacji host key

### Worker — `tests/test_tasks.py` (nowa klasa `TestDryRunPreviewTask`)

- `test_builds_params_from_connection_and_delegates_to_preview` — mock `Connection`, `RsyncHandler.preview` → assert wywołane z poprawnymi params
- `test_returns_error_dict_when_connection_not_found` — `Connection.DoesNotExist` → zwraca `{'exit_code': None, 'error': '...'}`, nie propaguje wyjątku
- `test_encrypts_file_when_gpg_passphrase_and_connection_encrypt_true` — assert `encrypt_file` wywołane, `preview()` dostaje zaszyfrowaną ścieżkę
- `test_skips_encryption_when_no_passphrase` — `connection.encrypt=True`, brak `gpg_passphrase` → `encrypt_file` niewywołane

### Web — `apps/transfers/tests/test_views.py`

- `test_dry_run_forbidden_for_readonly` — 403
- `test_dry_run_rejects_non_rsync_connection` — błąd formularza, brak dispatch taska
- `test_dry_run_validates_form_same_as_create` — brak pliku/złe rozszerzenie → błąd formularza (reużycie istniejących testów walidacji)
- `test_dry_run_saves_upload_without_creating_transferjob` — plik zapisany do `/transfers`, `TransferJob.objects.count()` bez zmian
- `test_dry_run_dispatches_task_and_returns_task_id` — mock `current_app.send_task`, assert `task_id` w odpowiedzi
- `test_dry_run_status_forbidden_for_readonly` — 403
- `test_dry_run_status_renders_pending` — mock `AsyncResult.state == 'PENDING'` → spinner
- `test_dry_run_status_renders_success_exit_zero` — mock `AsyncResult` `SUCCESS`, `result={'exit_code': 0, ...}` → zielona ramka
- `test_dry_run_status_renders_success_nonzero_exit` — `exit_code != 0` → czerwona ramka
- `test_dry_run_status_renders_failure` — `AsyncResult.state == 'FAILURE'` → generyczny czerwony komunikat

### Kolejność TDD

Czerwone testy `RsyncHandler.preview()` → implementacja → czerwone testy
`dry_run_preview` taska → implementacja → czerwone testy widoku
`transfer_dry_run` → implementacja → czerwone testy `transfer_dry_run_status`
→ implementacja → template/JS (bez automatycznych testów — manualna
weryfikacja w przeglądarce, spójne z tym jak projekt traktuje warstwę
czysto wizualną). Pełny zestaw worker + web zielony przed każdym commitem.

## Poza zakresem (YAGNI)

- Podgląd dla SFTP/relay (rsync `--dry-run` nie ma odpowiednika 1:1 w SFTP;
  ten sam brak funkcjonalny co dziś w `dry_run_before_transfer`, które też
  jest rsync-only)
- Reużycie już wgranego pliku między `[DRY RUN]` a `[TRANSFER]` (patrz
  Decyzja 4 — świadomie odrzucone, dwa niezależne submity)
- Zmiana zachowania istniejącego `dry_run_before_transfer` /
  embedded pre-flight w `execute()` — zostaje bez zmian, to osobny
  mechanizm
- Historia/log poprzednich podglądów (dry-run to efemeryczna operacja,
  wynik żyje tylko w wyniku Celery, nie jest per-user listowany)
