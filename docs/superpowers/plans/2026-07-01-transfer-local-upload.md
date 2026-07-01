# Transfer Local Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zamienić pole „LOCAL ./TRANSFERS" (nazwa pliku obecnego na serwerze) na upload pliku z lokalnej maszyny przeglądarki; `web` zapisuje plik do współdzielonego `/transfers`, `worker` czyta bez zmian.

**Architecture:** Django `FileField` w `TransferForm` zastępuje `source_path` jako pole wejściowe. Widok zapisuje uploadowany plik chunkami do `settings.TRANSFERS_DIR` i ustawia `job.source_path`. Wolumen `./transfers:/transfers` montowany także w kontenerze `web` (dziś tylko `worker`).

**Tech Stack:** Django 5.x, pytest + pytest-django, Docker Compose, HTMX/CRT frontend.

## Global Constraints

- Limit uploadu: dokładnie `100 * 1024 * 1024` bajtów (100 MB). Nginx już ma `client_max_body_size 100m` — NIE zmieniać.
- Kolizja nazw w `/transfers`: ciche nadpisanie (tryb `'wb'`).
- Katalog docelowy: `settings.TRANSFERS_DIR` = `'/transfers'`. Nigdy nie hardcodować ścieżki w widoku/formularzu — zawsze przez `settings`.
- Sanityzacja nazwy pliku wyłącznie przez istniejącą funkcję `_validate_source_filename` (blokuje `/`, `\`, `..`, znaki kontrolne `\x00-\x1f`, wiodący `-`).
- Tylko upload — żadnego pola tekstowego „wpisz nazwę pliku na serwerze".
- Transfery Flow/relay bez zmian (używają `flow.source_path`).
- W testach NIGDY nie zapisywać do prawdziwego `/transfers` — nadpisać `settings.TRANSFERS_DIR` na katalog tymczasowy pytest.
- Język komunikatów błędów: polski.

---

### Task 1: Ustawienia i wolumen Docker

**Files:**
- Modify: `services/web/config/settings/base.py` (dodać stałe na końcu pliku)
- Modify: `docker-compose.yml:34-35` (wolumeny serwisu `web`)
- Test: `services/web/apps/transfers/tests/test_settings_upload.py` (Create)

**Interfaces:**
- Produces: `settings.TRANSFERS_DIR` (str, `'/transfers'`), `settings.MAX_UPLOAD_BYTES` (int, `104857600`). Task 2 i Task 3 czytają obie stałe przez `from django.conf import settings`.

- [ ] **Step 1: Write the failing test**

Create `services/web/apps/transfers/tests/test_settings_upload.py`:

```python
from django.conf import settings


def test_transfers_dir_setting():
    assert settings.TRANSFERS_DIR == '/transfers'


def test_max_upload_bytes_is_100mb():
    assert settings.MAX_UPLOAD_BYTES == 100 * 1024 * 1024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm web pytest apps/transfers/tests/test_settings_upload.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'TRANSFERS_DIR'`

- [ ] **Step 3: Add the settings constants**

Append to `services/web/config/settings/base.py`:

```python
# Transfer file uploads — shared volume read by the worker container.
TRANSFERS_DIR = '/transfers'
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB, matches nginx client_max_body_size
```

- [ ] **Step 4: Add the volume mount to the web service**

In `docker-compose.yml`, the `web:` service `volumes:` block currently reads:

```yaml
    volumes:
      - static_files:/app/staticfiles
```

Change it to:

```yaml
    volumes:
      - static_files:/app/staticfiles
      - ./transfers:/transfers
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm web pytest apps/transfers/tests/test_settings_upload.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Verify the volume mount landed**

Run: `grep -A3 'static_files:/app/staticfiles' docker-compose.yml`
Expected: output includes the line `- ./transfers:/transfers` directly under the `web` service's static_files line.

- [ ] **Step 7: Commit**

```bash
git add services/web/config/settings/base.py docker-compose.yml services/web/apps/transfers/tests/test_settings_upload.py
git commit -m "feat: settings + web volume mount for transfer uploads"
```

---

### Task 2: Formularz — FileField zamiast source_path

**Files:**
- Modify: `services/web/apps/transfers/forms.py`
- Test: `services/web/apps/transfers/tests/test_transfer_form.py` (rewrite the `source_path`-based tests)

**Interfaces:**
- Consumes: `settings.TRANSFERS_DIR`, `settings.MAX_UPLOAD_BYTES` (Task 1); existing `_validate_source_filename(value: str) -> None`.
- Produces: `TransferForm` with field `upload = forms.FileField(...)`; after `is_valid()`, `form.cleaned_data['source_path'] == f'{settings.TRANSFERS_DIR}/{uploaded.name}'`. `source_path` is NOT in `Meta.fields`. `form.cleaned_data['upload']` holds the `UploadedFile`. Task 3 reads both keys.

- [ ] **Step 1: Replace the source_path form tests with upload tests**

Replace the entire class `TestTransferFormSourcePath` (lines 8–66) in `services/web/apps/transfers/tests/test_transfer_form.py` with:

```python
@pytest.mark.django_db
class TestTransferFormUpload:
    """The form accepts an uploaded file and derives source_path as
    /transfers/<filename> so the worker can resolve the volume-mounted path."""

    def _form(self, filename, user, conn, content=b'data', size=None):
        upload = SimpleUploadedFile(filename, content)
        if size is not None:
            upload.size = size
        return TransferForm(
            {'connection': conn.pk, 'destination_path': '/dst/'},
            {'upload': upload},
            user=user,
        )

    def test_valid_upload_derives_source_path(self, regular_user, make_connection):
        form = self._form('backup.tar', regular_user, make_connection(regular_user))
        assert form.is_valid(), form.errors
        assert form.cleaned_data['source_path'] == f'{settings.TRANSFERS_DIR}/backup.tar'

    def test_upload_over_limit_rejected(self, regular_user, make_connection):
        form = self._form('big.tar', regular_user, make_connection(regular_user),
                          size=settings.MAX_UPLOAD_BYTES + 1)
        assert not form.is_valid()
        assert 'upload' in form.errors

    def test_upload_at_limit_accepted(self, regular_user, make_connection):
        form = self._form('exact.tar', regular_user, make_connection(regular_user),
                          size=settings.MAX_UPLOAD_BYTES)
        assert form.is_valid(), form.errors

    def test_rejects_filename_with_slash(self, regular_user, make_connection):
        form = self._form('sub/evil.tar', regular_user, make_connection(regular_user))
        assert not form.is_valid()
        assert 'upload' in form.errors

    def test_rejects_filename_with_traversal(self, regular_user, make_connection):
        form = self._form('..', regular_user, make_connection(regular_user))
        assert not form.is_valid()
        assert 'upload' in form.errors

    def test_missing_upload_rejected(self, regular_user, make_connection):
        form = TransferForm(
            {'connection': make_connection(regular_user).pk, 'destination_path': '/dst/'},
            {},
            user=regular_user,
        )
        assert not form.is_valid()
        assert 'upload' in form.errors

    def test_upload_label_mentions_local(self, regular_user):
        form = TransferForm(user=regular_user)
        assert 'local' in form.fields['upload'].label.lower()
```

Update the imports at the top of the file (lines 1–5) to:

```python
import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from apps.transfers.forms import TransferForm, _validate_source_filename
from apps.transfers.models import TransferJob
from django.core.exceptions import ValidationError
```

Note: `SimpleUploadedFile` reports `.size` from its byte content. For the over/at-limit tests we override `.size` directly to avoid allocating 100 MB in memory. `SimpleUploadedFile('..', b'data')` has `.name == '..'`, which `_validate_source_filename` rejects (contains `..` segment). Filenames with `/` are collapsed by Django's upload handling to the basename, but `_validate_source_filename` still runs on `uploaded.name`; a form field value `'sub/evil.tar'` arrives as name `'sub/evil.tar'` in `SimpleUploadedFile` (it does not strip), so the slash check fires.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm web pytest apps/transfers/tests/test_transfer_form.py::TestTransferFormUpload -v`
Expected: FAIL — `upload` field does not exist / KeyError on `source_path`.

- [ ] **Step 3: Rewrite the form**

Replace the whole body of `services/web/apps/transfers/forms.py` from the `class TransferForm` line to the end of the file with:

```python
class TransferForm(forms.ModelForm):
    upload = forms.FileField(label='Local file')
    gpg_passphrase = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'off'}),
        label='GPG Passphrase',
    )

    class Meta:
        model = TransferJob
        fields = ['connection', 'destination_path']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['connection'].queryset = Connection.objects.filter(owner=user)

    def clean_upload(self):
        uploaded = self.cleaned_data['upload']
        if uploaded.size > settings.MAX_UPLOAD_BYTES:
            raise ValidationError('Plik przekracza limit 100 MB.')
        _validate_source_filename(uploaded.name)
        return uploaded

    def clean(self):
        cleaned = super().clean()
        uploaded = cleaned.get('upload')
        if uploaded is not None:
            cleaned['source_path'] = f'{settings.TRANSFERS_DIR}/{uploaded.name}'
        return cleaned

    def clean_destination_path(self):
        value = self.cleaned_data['destination_path']
        _validate_transfer_path(value)
        return value
```

Update the imports/top of `forms.py` (lines 1–8) to:

```python
import re

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from .models import TransferJob
from apps.connections.models import Connection
```

Remove the now-unused `TRANSFERS_MOUNT` constant and the old `clean_source_path` method. Keep `_validate_transfer_path` unchanged.

Strengthen `_validate_source_filename` so a bare `.`/`..`/empty name is rejected (the existing function only blocks `/`, `\`, leading `-`, and control chars — a standalone `..` slips through). Add as the FIRST check inside the function:

```python
    if value in ('', '.', '..'):
        raise ValidationError('Nieprawidłowa nazwa pliku.')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm web pytest apps/transfers/tests/test_transfer_form.py::TestTransferFormUpload apps/transfers/tests/test_transfer_form.py::TestValidateSourceFilename -v`
Expected: PASS (all TestTransferFormUpload + TestValidateSourceFilename tests green).

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/transfers/forms.py services/web/apps/transfers/tests/test_transfer_form.py
git commit -m "feat: TransferForm accepts uploaded file instead of server filename"
```

---

### Task 3: Widok — zapis pliku do /transfers + dispatch

**Files:**
- Modify: `services/web/apps/transfers/views.py:9-22` (`transfer_create`)
- Test: `services/web/apps/transfers/tests/test_views.py`, and the `TestTransferCreateWithGPG` class in `services/web/apps/transfers/tests/test_transfer_form.py`

**Interfaces:**
- Consumes: `TransferForm` (Task 2) with `cleaned_data['upload']` and `cleaned_data['source_path']`; `settings.TRANSFERS_DIR`.
- Produces: on valid POST, writes the uploaded file to `os.path.join(settings.TRANSFERS_DIR, uploaded.name)` (mode `'wb'`, overwrite), sets `job.source_path`, dispatches `transfers.execute` unchanged.

- [ ] **Step 1: Rewrite the create-view tests**

In `services/web/apps/transfers/tests/test_views.py`, replace `test_create_transfer_dispatches_celery_task` (lines 14–27) with:

```python
    def test_create_transfer_writes_file_and_dispatches(
        self, auth_client, regular_user, make_connection, mocker,
        django_capture_on_commit_callbacks, settings, tmp_path,
    ):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        upload = SimpleUploadedFile('file.tar', b'payload-bytes')
        with django_capture_on_commit_callbacks(execute=True):
            response = auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'destination_path': '/backup/',
                'upload': upload,
            })
        assert response.status_code == 302
        job = TransferJob.objects.get(owner=regular_user)
        assert job.status == STATUS_PENDING
        assert job.source_path == f'{tmp_path}/file.tar'
        assert (tmp_path / 'file.tar').read_bytes() == b'payload-bytes'
        mock_delay.assert_called_once_with(
            'transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': None})

    def test_create_transfer_overwrites_existing_file(
        self, auth_client, regular_user, make_connection, mocker,
        django_capture_on_commit_callbacks, settings, tmp_path,
    ):
        settings.TRANSFERS_DIR = str(tmp_path)
        (tmp_path / 'file.tar').write_bytes(b'old-content')
        mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        upload = SimpleUploadedFile('file.tar', b'new-content')
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'destination_path': '/backup/',
                'upload': upload,
            })
        assert (tmp_path / 'file.tar').read_bytes() == b'new-content'
```

Update the imports at the top of `test_views.py` (lines 1–5) to add:

```python
from django.core.files.uploadedfile import SimpleUploadedFile
```

- [ ] **Step 2: Rewrite the GPG-wiring tests to post an upload**

In `services/web/apps/transfers/tests/test_transfer_form.py`, replace the whole `TestTransferCreateWithGPG` class (lines 93–147) with:

```python
@pytest.mark.django_db
class TestTransferCreateWithGPG:
    """GPG passphrase is wired through the form to Celery dispatch."""

    def _post(self, auth_client, conn, passphrase, tmp_path):
        return auth_client.post(reverse('transfers:create'), {
            'connection': conn.pk,
            'destination_path': '/backup/',
            'upload': SimpleUploadedFile('secret.tar', b'x'),
            'gpg_passphrase': passphrase,
        })

    def test_gpg_passphrase_passed_to_delay(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            self._post(auth_client, conn, 'mypassword123', tmp_path)
        job = TransferJob.objects.get(owner=regular_user)
        mock_delay.assert_called_once_with('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': 'mypassword123'})

    def test_empty_passphrase_passed_as_none(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            self._post(auth_client, conn, '', tmp_path)
        job = TransferJob.objects.get(owner=regular_user)
        mock_delay.assert_called_once_with('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': None})

    def test_whitespace_passphrase_treated_as_none(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            self._post(auth_client, conn, '   ', tmp_path)
        job = TransferJob.objects.get(owner=regular_user)
        mock_delay.assert_called_once_with('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': None})

    def test_source_path_stored_from_upload(self, auth_client, regular_user, make_connection, mocker, django_capture_on_commit_callbacks, settings, tmp_path):
        settings.TRANSFERS_DIR = str(tmp_path)
        mock_delay = mocker.patch('apps.transfers.views.current_app.send_task')
        conn = make_connection(regular_user)
        with django_capture_on_commit_callbacks(execute=True):
            auth_client.post(reverse('transfers:create'), {
                'connection': conn.pk,
                'destination_path': '/remote/archive.tar.gz',
                'upload': SimpleUploadedFile('archive.tar.gz', b'x'),
            })
        job = TransferJob.objects.get(owner=regular_user)
        assert job.source_path == f'{tmp_path}/archive.tar.gz'
        mock_delay.assert_called_once()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker compose run --rm web pytest apps/transfers/tests/test_views.py::TestTransferCreateView apps/transfers/tests/test_transfer_form.py::TestTransferCreateWithGPG -v`
Expected: FAIL — view does not write the file / `source_path` not set from upload.

- [ ] **Step 4: Rewrite the view**

Replace `transfer_create` (lines 9–22) in `services/web/apps/transfers/views.py` with:

```python
@login_required
def transfer_create(request):
    form = TransferForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        uploaded = form.cleaned_data['upload']
        dest = os.path.join(settings.TRANSFERS_DIR, uploaded.name)
        try:
            with open(dest, 'wb') as fh:
                for chunk in uploaded.chunks():
                    fh.write(chunk)
        except OSError as exc:
            form.add_error(None, f'Nie udało się zapisać pliku: {exc}')
            return render(request, 'transfers/create.html', {'form': form})
        with transaction.atomic():
            job = form.save(commit=False)
            job.owner = request.user
            job.source_path = form.cleaned_data['source_path']
            job.save()
            passphrase = (form.cleaned_data.get('gpg_passphrase') or '').strip() or None
            transaction.on_commit(
                lambda: current_app.send_task('transfers.execute', kwargs={'job_id': job.pk, 'gpg_passphrase': passphrase})
            )
        return redirect('transfers:detail', pk=job.pk)
    return render(request, 'transfers/create.html', {'form': form})
```

Update the imports at the top of `views.py` (lines 1–6) to add `os` and `settings`:

```python
import os

from celery import current_app
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from .models import TransferJob, STATUS_RUNNING
from .forms import TransferForm
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm web pytest apps/transfers/tests/test_views.py apps/transfers/tests/test_transfer_form.py -v`
Expected: PASS (all transfer view + form tests green).

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/transfers/views.py services/web/apps/transfers/tests/test_views.py services/web/apps/transfers/tests/test_transfer_form.py
git commit -m "feat: transfer view saves uploaded file to /transfers volume"
```

---

### Task 4: Szablon — kontrolka wyboru pliku

**Files:**
- Modify: `services/web/templates/transfers/create.html:7-29`
- Verify (read only): `services/web/static/js/browser.js` — the `input[type="file"][data-file-display]` change handler already exists (added for Profil import). Reuse it; do not duplicate.
- Test: `services/web/apps/transfers/tests/test_views.py` (add a render assertion to `TestTransferCreateView`)

**Interfaces:**
- Consumes: `TransferForm` with fields `upload`, `connection`, `destination_path`, `gpg_passphrase` (Task 2); the `data-file-display` JS handler in `browser.js`.
- Produces: create page renders `<form ... enctype="multipart/form-data">` containing `<input type="file" ...>` for the `upload` field and the styled `[ WYBIERZ ]` button.

- [ ] **Step 1: Write the failing render test**

Add to `TestTransferCreateView` in `services/web/apps/transfers/tests/test_views.py`:

```python
    def test_create_form_has_file_input_and_multipart(self, auth_client):
        response = auth_client.get(reverse('transfers:create'))
        assert response.status_code == 200
        body = response.content.decode()
        assert 'enctype="multipart/form-data"' in body
        assert 'type="file"' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm web pytest "apps/transfers/tests/test_views.py::TestTransferCreateView::test_create_form_has_file_input_and_multipart" -v`
Expected: FAIL — no `enctype`/`type="file"` in the rendered page.

- [ ] **Step 3: Confirm the browser.js handler exists**

Run: `grep -n 'data-file-display' services/web/static/js/browser.js`
Expected: a `change` listener that reads `input.files[0].name` and writes it into the element named by `data-file-display`. If the grep returns nothing, add this handler at the end of `browser.js`:

```javascript
document.addEventListener('change', function (e) {
  var input = e.target;
  if (input.matches && input.matches('input[type="file"][data-file-display]')) {
    var target = document.getElementById(input.getAttribute('data-file-display'));
    if (target && input.files.length) { target.textContent = input.files[0].name; }
  }
});
```

- [ ] **Step 4: Rewrite the form block in the template**

Replace lines 7–29 of `services/web/templates/transfers/create.html` with:

```html
    <form method="post" enctype="multipart/form-data">
      {% csrf_token %}
      {% for field in form %}
      <div class="field">
        <label>{{ field.label|upper }}:</label>
        {% if field.html_name == 'upload' %}
        <div class="field-with-btn">
          <label for="{{ field.auto_id }}" class="btn btn-small">[ WYBIERZ ]</label>
          <span id="upload-file-name" class="file-name">— brak pliku —</span>
          <div class="file-hidden">{{ field }}</div>
        </div>
        {% elif field.html_name == 'destination_path' %}
        <div class="field-with-btn">
          {{ field }}
          <button type="button" class="btn btn-small"
            data-browse-open
            data-browse-field="{{ field.auto_id }}"
            data-browse-conn-sel="#id_connection">
            [BROWSE]
          </button>
        </div>
        {% else %}
        {{ field }}
        {% endif %}
        {% if field.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ field.errors }}</div>{% endif %}
      </div>
      {% endfor %}
      <button type="submit" class="btn">[ EXECUTE TRANSFER ]</button>
    </form>
```

- [ ] **Step 5: Add `data-file-display` to the upload widget**

In `services/web/apps/transfers/forms.py`, give the `upload` field a widget that wires the display span. Change the field definition:

```python
    upload = forms.FileField(
        label='Local file',
        widget=forms.ClearableFileInput(attrs={'data-file-display': 'upload-file-name'}),
    )
```

- [ ] **Step 6: Run the render test to verify it passes**

Run: `docker compose run --rm web pytest "apps/transfers/tests/test_views.py::TestTransferCreateView::test_create_form_has_file_input_and_multipart" -v`
Expected: PASS.

- [ ] **Step 7: Bump the CSS/JS cache-bust if needed**

Verify `.file-name` and `.file-hidden` exist in `services/web/static/css/crt.css`:

Run: `grep -nE '\.file-name|\.file-hidden' services/web/static/css/crt.css`
Expected: both classes present (added for Profil import). If missing, no change needed here — they were introduced in the import/export feature; if the grep is empty, add:

```css
.file-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.file-name { color: var(--green); font-size: 0.85rem; }
```

- [ ] **Step 8: Run the full transfers suite**

Run: `docker compose run --rm web pytest apps/transfers/ -v`
Expected: PASS (all transfers tests green).

- [ ] **Step 9: Commit**

```bash
git add services/web/templates/transfers/create.html services/web/apps/transfers/forms.py services/web/apps/transfers/tests/test_views.py services/web/static/js/browser.js services/web/static/css/crt.css
git commit -m "feat: file-picker UI for local upload in transfer form"
```

---

### Task 5: Weryfikacja end-to-end i pełny build

**Files:** none (integration verification)

- [ ] **Step 1: Rebuild web (no bind-mount for app code)**

Run: `docker compose build web && docker compose up -d web`
Expected: build succeeds, web container healthy.

- [ ] **Step 2: Run the full web suite**

Run: `docker compose run --rm web pytest`
Expected: all tests pass (previous baseline: 253 passed; expect ≥ that minus removed source_path tests, plus new upload tests).

- [ ] **Step 3: Confirm the web container sees the transfers volume**

Run: `docker compose exec web sh -c 'test -d /transfers && echo MOUNTED'`
Expected: `MOUNTED`.

- [ ] **Step 4: Manual smoke (report to controller)**

Log in, open `/transfers/create/`, pick a local file, choose a connection + destination, execute. Confirm the file appears in host `./transfers/` and the job dispatches. Report the outcome.
