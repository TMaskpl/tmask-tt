# Retencja i auto-cleanup `/transfers` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wolumen `/transfers` przestaje rosnąć bezterminowo — plik znika natychmiast po udanym transferze, a wszystko co zostanie (failed/cancelled/sieroty) sprząta periodic task po przekroczeniu progu wieku.

**Architecture:** Dwa niezależne mechanizmy w `services/worker/tasks.py`: (1) `_cleanup_source_file(job)` wywoływana w `execute_transfer` tuż po `job.mark_done()`, usuwa `job.source_path` gdy `job.connection_id` jest ustawione (nie dla flow/relay) i ścieżka leży pod `settings.TRANSFERS_DIR`; (2) nowy periodic task `transfers.cleanup_old_transfers` skanujący `TRANSFERS_DIR` po `mtime`, zarejestrowany przez migrację Django (wzorem istniejącego `cleanup-orphan-jobs`).

**Tech Stack:** Python 3.12, Django 5.x, Celery + django-celery-beat, python-decouple, pytest (worker: `tests/test_tasks.py`, web: `apps/transfers/tests/`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-06-transfers-retention-design.md` — wszystkie decyzje projektowe stamtąd obowiązują (m.in. usuwanie każdego pliku pod `/transfers` niezależnie od pochodzenia, retencja po `mtime` a nie po statusie DB, błędy `unlink` → `logger.warning`, nigdy nie zmieniają statusu joba).
- Praca na gałęzi `feat/transfers-retention` (już utworzona, spec zacommitowany na `main` w `5b84f95`).
- Polecenia uruchamiać z katalogu projektu: `/Users/dniemczok/Desktop/TMaskPL/tmask-tt`.
- **TDD dev-loop (szybkie iteracje, bez rebuildu obrazu):**
  - Worker: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/ -v`
  - Web: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/ -v`
- **Weryfikacja końcowa (rebuild, dokładnie jak CI w `.github/workflows/*.yml`):**
  - `docker compose build worker && docker compose run --rm worker python -m pytest tests/ -v`
  - `docker compose --profile test build web-test && docker compose --profile test run --rm web-test python -m pytest apps/ -v`
- **Bezpieczeństwo danych:** `postgres`, `redis`, `web`, `worker`, `beat`, `nginx` to **żywe kontenery produkcyjne** (`docker compose ps` potwierdza — to nie jest środowisko testowe). `web-test`/`web`/`worker` w testach pytest-django tworzą efemeryczną bazę `test_<POSTGRES_DB>` (Django test runner) — realna baza produkcyjna nie jest dotykana. Żaden krok tego planu nie uruchamia `manage.py migrate` bezpośrednio na żywym stacku ani nie zapisuje/usuwa plików w realnym zamontowanym `/transfers` — wszystkie testy plikowe używają fixtury `tmp_path` + `patch('tasks.settings.TRANSFERS_DIR', str(tmp_path))`, nigdy prawdziwej ścieżki `/transfers`.
- Commity: prefiks `feat:`/`test:`, opis po polsku, stopka `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Kolejność commitów w tasku: najpierw testy (czerwone), potem implementacja (zielone) — osobne pliki w tym samym commicie na końcu taska (jak w poprzednich planach tego projektu).

---

### Task 1: Ustawienie `TRANSFERS_RETENTION_DAYS`

**Files:**
- Modify: `services/web/config/settings/base.py`
- Modify: `.env.example`
- Test: `services/web/apps/transfers/tests/test_settings_upload.py`

**Interfaces:**
- Produces: `settings.TRANSFERS_RETENTION_DAYS: int`, domyślnie `1`, czytane z `.env` przez `python-decouple`. Współdzielone przez `web` i `worker` (worker kopiuje `services/web/config` w Dockerfile — ten sam moduł ustawień).

- [ ] **Step 1: Napisz czerwony test**

Dodaj na końcu `services/web/apps/transfers/tests/test_settings_upload.py`:

```python
def test_transfers_retention_days_default():
    assert settings.TRANSFERS_RETENTION_DAYS == 1
```

- [ ] **Step 2: Uruchom test — sprawdź że pada**

Run: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/transfers/tests/test_settings_upload.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'TRANSFERS_RETENTION_DAYS'`

- [ ] **Step 3: Dodaj ustawienie**

W `services/web/config/settings/base.py`, zaraz po linii 124 (`MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB, matches nginx client_max_body_size`), dodaj:

```python
TRANSFERS_RETENTION_DAYS = config('TRANSFERS_RETENTION_DAYS', default=1, cast=int)
```

- [ ] **Step 4: Udokumentuj w `.env.example`**

Na końcu `.env.example` dodaj:

```
# Retencja plików w /transfers (dni) — periodic task cleanup_old_transfers
TRANSFERS_RETENTION_DAYS=1
```

- [ ] **Step 5: Uruchom test — zielony**

Run: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/transfers/tests/test_settings_upload.py -v`
Expected: PASS (2 testy: `test_transfers_dir_setting`, `test_max_upload_bytes_is_100mb`, `test_transfers_retention_days_default`)

- [ ] **Step 6: Commit**

```bash
git add services/web/config/settings/base.py .env.example services/web/apps/transfers/tests/test_settings_upload.py
git commit -m "$(cat <<'EOF'
feat: dodaj ustawienie TRANSFERS_RETENTION_DAYS

Próg retencji (domyślnie 1 dzień) dla periodic taska sprzątającego
stare pliki w /transfers.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Usuwanie pliku źródłowego po udanym transferze

**Files:**
- Modify: `services/worker/tasks.py`
- Modify: `services/worker/tests/conftest.py`
- Test: `services/worker/tests/test_tasks.py`

**Interfaces:**
- Consumes: `settings.TRANSFERS_DIR` (istniejące), `settings.TRANSFERS_RETENTION_DAYS` (Task 1 — nieużywane w tym tasku, ale dodawane do testowego `configure()` teraz, żeby Task 3 nie musiał już tego robić).
- Produces: `_cleanup_source_file(job) -> None` — prywatny helper, wywoływany wyłącznie z `execute_transfer`.

- [ ] **Step 1: Dodaj `TRANSFERS_DIR`/`TRANSFERS_RETENTION_DAYS` do testowego `configure()`**

W `services/worker/tests/conftest.py`, w bloku `_dj_settings.configure(...)` (linie 30-36), zmień na:

```python
    _dj_settings.configure(
        INSTALLED_APPS=[],
        DATABASES={},
        CELERY_TASK_ALWAYS_EAGER=True,
        CELERY_BROKER_URL='memory://',
        CELERY_RESULT_BACKEND='cache+memory://',
        TRANSFERS_DIR='/transfers',
        TRANSFERS_RETENTION_DAYS=1,
    )
```

- [ ] **Step 2: Napisz czerwone testy `TestCleanupSourceFileOnSuccess`**

Dodaj na końcu `services/worker/tests/test_tasks.py` (te testy używają wyłącznie `tmp_path`/`pathlib`, żadnych nowych importów na górze pliku nie trzeba dodawać — `import os`/`import time` trafią dopiero w Task 3):

```python
class TestCleanupSourceFileOnSuccess:
    def test_deletes_source_file_after_success_when_connection_job(self, tmp_path):
        source = tmp_path / "upload.txt"
        source.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection_id = 5
            mock_job.connection.protocol = 'sftp'
            mock_job.source_path = str(source)
            mock_job.pk = 1
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            assert not source.exists()

    def test_does_not_delete_when_flow_job(self, tmp_path):
        source = tmp_path / "upload.txt"
        source.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.RelayHandler') as MockRelay, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = 99
            mock_job.connection_id = None
            mock_job.source_path = str(source)
            mock_job.pk = 1
            MockRelay.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            assert source.exists()

    def test_does_not_delete_path_outside_transfers_dir(self, tmp_path):
        transfers_dir = tmp_path / "transfers"
        transfers_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        source = outside_dir / "upload.txt"
        source.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(transfers_dir)), \
             patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection_id = 5
            mock_job.connection.protocol = 'sftp'
            mock_job.source_path = str(source)
            mock_job.pk = 1
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            assert source.exists()

    def test_success_survives_missing_file(self, tmp_path):
        missing = tmp_path / "gone.txt"
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection_id = 5
            mock_job.connection.protocol = 'sftp'
            mock_job.source_path = str(missing)
            mock_job.pk = 1
            MockSFTP.return_value.execute.return_value = None
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            mock_job.mark_done.assert_called_once()

    def test_does_not_delete_on_failed_transfer(self, tmp_path):
        source = tmp_path / "upload.txt"
        source.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob, \
             patch('tasks.TransferLog'):
            from modules.sftp.handler import SFTPTransferError
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.flow_id = None
            mock_job.connection_id = 5
            mock_job.connection.protocol = 'sftp'
            mock_job.source_path = str(source)
            mock_job.pk = 1
            MockSFTP.return_value.execute.side_effect = SFTPTransferError('AUTH FAILED')
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            assert source.exists()
```

- [ ] **Step 3: Uruchom testy — sprawdź że padają**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/test_tasks.py::TestCleanupSourceFileOnSuccess -v`
Expected: FAIL na wszystkich 5 (`NameError`/`AttributeError` na `tasks.settings` — moduł `settings` jeszcze nie zaimportowany w `tasks.py`; pierwszy test wywali się na `patch('tasks.settings.TRANSFERS_DIR', ...)`)

- [ ] **Step 4: Dodaj import `settings` w `tasks.py`**

W `services/worker/tasks.py`, w bloku importów na górze (linie 1-14), zmień:

```python
import os
import django

from celery import Celery
from celery.utils.log import get_task_logger

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from apps.transfers.models import TransferJob, TransferLog  # noqa: E402
from modules.sftp.handler import SFTPHandler, SFTPTransferError  # noqa: E402
from modules.rsync.handler import RsyncHandler, RsyncTransferError  # noqa: E402
from modules.relay.handler import RelayHandler, RelayTransferError  # noqa: E402
from notifications import send_email_notification, send_webhook_notification, send_telegram_notification  # noqa: E402
```

na:

```python
import os
import django

from celery import Celery
from celery.utils.log import get_task_logger

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from django.conf import settings  # noqa: E402
from apps.transfers.models import TransferJob, TransferLog  # noqa: E402
from modules.sftp.handler import SFTPHandler, SFTPTransferError  # noqa: E402
from modules.rsync.handler import RsyncHandler, RsyncTransferError  # noqa: E402
from modules.relay.handler import RelayHandler, RelayTransferError  # noqa: E402
from notifications import send_email_notification, send_webhook_notification, send_telegram_notification  # noqa: E402
```

- [ ] **Step 5: Dodaj `_cleanup_source_file` i wywołanie w `execute_transfer`**

W `services/worker/tasks.py`, tuż przed `@app.task(bind=True, name='transfers.execute')` (definicja `execute_transfer`), dodaj nową funkcję:

```python
def _cleanup_source_file(job) -> None:
    if job.connection_id is None:
        return  # flow/relay — source_path na zdalnym hoście, nie dotykamy
    path = job.source_path
    if not path or not path.startswith(settings.TRANSFERS_DIR):
        return
    try:
        os.unlink(path)
    except OSError as e:
        logger.warning(f'Nie udało się usunąć {path} po transferze: {e}')
```

Następnie w `execute_transfer`, w bloku `try`, zmień:

```python
    try:
        _run_transfer(job, gpg_passphrase, log_callback)
        job.mark_done()
        send_notification.delay(job.pk)
        send_webhook.delay(job.pk)
        send_telegram.delay(job.pk)
```

na:

```python
    try:
        _run_transfer(job, gpg_passphrase, log_callback)
        job.mark_done()
        _cleanup_source_file(job)
        send_notification.delay(job.pk)
        send_webhook.delay(job.pk)
        send_telegram.delay(job.pk)
```

- [ ] **Step 6: Uruchom testy — zielone**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/test_tasks.py::TestCleanupSourceFileOnSuccess -v`
Expected: PASS (5 testów)

- [ ] **Step 7: Pełny zestaw testów worker — brak regresji**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/ -v`
Expected: PASS — wszystkie dotychczasowe testy (m.in. `TestExecuteTransferTask`, `TestExecuteTransferDispatchesNotification/Webhook`) nadal zielone.

- [ ] **Step 8: Commit**

```bash
git add services/worker/tasks.py services/worker/tests/conftest.py services/worker/tests/test_tasks.py
git commit -m "$(cat <<'EOF'
feat: usuwaj plik źródłowy z /transfers po udanym transferze

Dotyczy wyłącznie jobów connection-based (nie flow/relay) i ścieżek
pod TRANSFERS_DIR. Błąd unlink loguje ostrzeżenie, nie zmienia statusu
joba.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Periodic task `cleanup_old_transfers`

**Files:**
- Modify: `services/worker/tasks.py`
- Test: `services/worker/tests/test_tasks.py`

**Interfaces:**
- Consumes: `settings.TRANSFERS_DIR`, `settings.TRANSFERS_RETENTION_DAYS` (oba już dostępne w testach po Task 2 Step 1).
- Produces: `cleanup_old_transfers()` — Celery task zarejestrowany jako `'transfers.cleanup_old_transfers'` (nazwa używana przez migrację w Task 4).

- [ ] **Step 1: Napisz czerwone testy `TestCleanupOldTransfers`**

Dodaj na górze `services/worker/tests/test_tasks.py` (obok istniejących `import pytest` / `from unittest.mock import patch, MagicMock`) nowe importy:

```python
import os
import time
```

Dodaj na końcu pliku:

```python
class TestCleanupOldTransfers:
    def test_removes_files_older_than_threshold(self, tmp_path):
        old_file = tmp_path / "old.txt"
        old_file.write_text("dummy")
        old_time = time.time() - 2 * 86400
        os.utime(old_file, (old_time, old_time))
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.settings.TRANSFERS_RETENTION_DAYS', 1):
            from tasks import cleanup_old_transfers
            cleanup_old_transfers()
            assert not old_file.exists()

    def test_keeps_files_newer_than_threshold(self, tmp_path):
        new_file = tmp_path / "new.txt"
        new_file.write_text("dummy")
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.settings.TRANSFERS_RETENTION_DAYS', 1):
            from tasks import cleanup_old_transfers
            cleanup_old_transfers()
            assert new_file.exists()

    def test_empty_directory_no_error(self, tmp_path):
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.settings.TRANSFERS_RETENTION_DAYS', 1):
            from tasks import cleanup_old_transfers
            cleanup_old_transfers()

    def test_single_file_error_does_not_abort_loop(self, tmp_path):
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("dummy")
        file_b.write_text("dummy")
        old_time = time.time() - 2 * 86400
        os.utime(file_a, (old_time, old_time))
        os.utime(file_b, (old_time, old_time))
        with patch('tasks.settings.TRANSFERS_DIR', str(tmp_path)), \
             patch('tasks.settings.TRANSFERS_RETENTION_DAYS', 1), \
             patch('tasks.os.unlink') as mock_unlink:
            mock_unlink.side_effect = [OSError('permission denied'), None]
            from tasks import cleanup_old_transfers
            cleanup_old_transfers()
            assert mock_unlink.call_count == 2
```

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/test_tasks.py::TestCleanupOldTransfers -v`
Expected: FAIL — `ImportError: cannot import name 'cleanup_old_transfers' from 'tasks'`

- [ ] **Step 3: Dodaj task `cleanup_old_transfers`**

W `services/worker/tasks.py`, zaraz po istniejącym `cleanup_orphan_jobs` (po linii `logger.info(f'Cleaned up {count} orphaned jobs')`), dodaj:

```python
@app.task(name='transfers.cleanup_old_transfers')
def cleanup_old_transfers():
    import time
    cutoff = time.time() - settings.TRANSFERS_RETENTION_DAYS * 86400
    removed = 0
    for name in os.listdir(settings.TRANSFERS_DIR):
        path = os.path.join(settings.TRANSFERS_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.unlink(path)
                removed += 1
        except OSError as e:
            logger.warning(f'Retention: nie udało się usunąć {path}: {e}')
    logger.info(f'Retention: usunięto {removed} plików z {settings.TRANSFERS_DIR}')
```

- [ ] **Step 4: Uruchom testy — zielone**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/test_tasks.py::TestCleanupOldTransfers -v`
Expected: PASS (4 testy)

- [ ] **Step 5: Pełny zestaw testów worker — brak regresji**

Run: `docker compose run --rm -v $PWD/services/worker:/app worker python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/worker/tasks.py services/worker/tests/test_tasks.py
git commit -m "$(cat <<'EOF'
feat: dodaj periodic task cleanup_old_transfers

Skanuje TRANSFERS_DIR po mtime, usuwa pliki starsze niż
TRANSFERS_RETENTION_DAYS — siatka bezpieczeństwa dla plików po
failed/cancelled transferach i sierot bez powiązanego joba.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Migracja rejestrująca periodic task

**Files:**
- Create: `services/web/apps/transfers/migrations/0005_transfers_retention_periodic_task.py`

**Interfaces:**
- Consumes: nazwa taska `'transfers.cleanup_old_transfers'` (Task 3 — string, brak zależności importowej).

- [ ] **Step 1: Utwórz migrację wzorem `0002_cleanup_periodic_task.py`**

Utwórz `services/web/apps/transfers/migrations/0005_transfers_retention_periodic_task.py`:

```python
from django.db import migrations


def create_retention_task(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=1, period='hours'
        )
        PeriodicTask.objects.get_or_create(
            name='cleanup-old-transfers',
            defaults={
                'interval': schedule,
                'task': 'transfers.cleanup_old_transfers',
                'enabled': True,
            }
        )
    except Exception:  # nosec B110 — django_celery_beat tables may not exist yet on first migrate
        pass


def remove_retention_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='cleanup-old-transfers').delete()
    except Exception:  # nosec B110 — safe: only deletes if table exists
        pass


class Migration(migrations.Migration):
    dependencies = [
        ('transfers', '0004_transferjob_cancelled_status'),
        ('django_celery_beat', '0001_initial'),
    ]
    operations = [migrations.RunPython(create_retention_task, remove_retention_task)]
```

- [ ] **Step 2: Zweryfikuj migrację — pełny zestaw testów web**

Run: `docker compose --profile test run --rm -v $PWD/services/web:/app web-test python -m pytest apps/ -v`
Expected: PASS — pytest-django tworzy efemeryczną bazę testową i stosuje wszystkie migracje (w tym nową `0005`) od zera; błąd w migracji ujawniłby się jako failure całej sesji testowej, nie pojedynczego testu.

- [ ] **Step 3: Commit**

```bash
git add services/web/apps/transfers/migrations/0005_transfers_retention_periodic_task.py
git commit -m "$(cat <<'EOF'
feat: zarejestruj periodic task cleanup-old-transfers (co 1h)

Analogicznie do istniejącego cleanup-orphan-jobs (5 min) — retencja
plikowa nie wymaga tej częstotliwości przy progu 1-dniowym.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Weryfikacja końcowa całej gałęzi

**Files:** brak zmian — tylko weryfikacja.

- [ ] **Step 1: Rebuild + pełny zestaw testów worker (dokładnie jak CI)**

Run:
```bash
docker compose build worker
docker compose run --rm worker python -m pytest tests/ -v
```
Expected: PASS — potwierdza, że obraz zbudowany dokładnie tak jak w CI/deploy (bez bind-mounta z Global Constraints) zawiera całą zmianę i przechodzi testy.

- [ ] **Step 2: Rebuild + pełny zestaw testów web (dokładnie jak CI)**

Run:
```bash
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/ -v
```
Expected: PASS

- [ ] **Step 3: Przegląd całej gałęzi**

Użyj `superpowers:requesting-code-review` (whole-branch review) na `feat/transfers-retention` względem `main` przed ewentualnym mergem/PR.

---

## Po wdrożeniu (poza planem TDD)

- Rebuild i redeploy produkcyjny (`docker compose build worker web && docker compose up -d`) uruchomi `manage.py migrate` przez `entrypoint.sh` na **żywej** bazie — dopiero to realnie zarejestruje `cleanup-old-transfers` w produkcyjnym Celery Beat. Zrobić świadomie, nie przypadkiem przy okazji testów.
- Aktualizacja dokumentacji w vault Obsidian: `11-Apps/CSCS/tmask-transporter/Projekt-tmask-transporter.md` (nowy punkt #16 lub rozszerzenie istniejącego zestawu) oraz `Propozycje rozbudowy.md` (oznaczyć #11 jako zrealizowane). Wpis do `LOG.md`.
