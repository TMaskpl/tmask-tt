# File Browser Modal — Design Spec

## Goal

Allow users to browse remote SSH filesystems via a modal when entering file paths in Transfer Now and Flow forms, instead of typing paths manually.

## Scope

- **Transfer Now** form: `destination_path` only (source_path is a local worker path, not browseable via SSH)
- **Flow** form: both `source_path` (via `source_conn`) and `dest_path` (via `dest_conn`)

## Approach: HTMX-driven modal

Single global modal overlay in `base.html`. Navigation triggers HTMX GET requests that swap the modal content fragment — same pattern as the live transfer log polling already in the project.

No new JS libraries. No full-page reloads.

---

## Section 1: Backend

### New endpoint

`GET /connections/<pk>/browse/?path=/`

Added to `apps/connections/views.py`:

```python
@login_required
def browse_directory(request, pk):
    connection = get_object_or_404(Connection, pk=pk, owner=request.user)
    path = request.GET.get('path', '/')
    try:
        entries = list_directory(connection, path)
        error = None
    except Exception as e:
        entries = []
        error = str(e)
    breadcrumbs = build_breadcrumbs(path)
    return render(request, 'connections/browser_fragment.html', {
        'entries': entries,
        'breadcrumbs': breadcrumbs,
        'error': error,
        'conn_pk': pk,
        'current_path': path,
    })
```

### New URL

Added to `apps/connections/urls.py`:

```python
path('<int:pk>/browse/', views.browse_directory, name='browse'),
```

### SFTP helper

New file `apps/connections/sftp_utils.py` — extracted from view to keep it testable:

```python
def list_directory(connection, path):
    """Returns sorted list of entries: dirs first, then files."""
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        connection.host,
        port=connection.port,
        username=connection.username,
        password=connection.password,
    )
    sftp = client.open_sftp()
    attrs = sftp.listdir_attr(path)
    sftp.close()
    client.close()
    entries = []
    for attr in attrs:
        is_dir = stat.S_ISDIR(attr.st_mode)
        entries.append(SimpleNamespace(
            name=attr.filename,
            is_dir=is_dir,
            full_path=path.rstrip('/') + '/' + attr.filename,
            size=attr.st_size if not is_dir else None,
        ))
    return sorted(entries, key=lambda e: (not e.is_dir, e.name))

def build_breadcrumbs(path):
    parts = [p for p in path.split('/') if p]
    crumbs = [{'label': '/', 'path': '/'}]
    for i, part in enumerate(parts):
        crumbs.append({
            'label': part,
            'path': '/' + '/'.join(parts[:i+1]),
        })
    return crumbs
```

### New template: `connections/browser_fragment.html`

```html
{% if error %}
<p class="msg-error">> {{ error }}</p>
{% else %}
<div class="breadcrumbs">
  {% for crumb in breadcrumbs %}
  <a href="#" onclick="openBrowser('{{ field_id }}', {{ conn_pk }}, '{{ crumb.path }}')">{{ crumb.label }}</a> /
  {% endfor %}
</div>
<ul class="file-list">
  {% for entry in entries %}
  <li>
    {% if entry.is_dir %}
    <a href="#" onclick="openBrowser('{{ field_id }}', {{ conn_pk }}, '{{ entry.full_path }}')">[DIR] {{ entry.name }}</a>
    {% else %}
    <a href="#" onclick="selectPath('{{ entry.full_path }}')">{{ entry.name }}</a>
    {% endif %}
  </li>
  {% empty %}
  <li>> (pusty katalog)</li>
  {% endfor %}
</ul>
{% endif %}
```

---

## Section 2: Modal + JS

### Modal overlay in `base.html`

Added before `</body>`:

```html
<div id="file-browser-overlay" style="display:none">
  <div id="file-browser-modal">
    <div id="file-browser-content"></div>
    <button onclick="closeBrowser()">[ ZAMKNIJ ]</button>
  </div>
</div>
```

### JS (inline in `base.html` or `crt.css` companion script)

```javascript
let _browserTargetField = null;
let _browserConnPk = null;

function openBrowser(fieldId, connPk, path) {
  path = path || '/';
  if (!connPk) {
    alert('Wybierz najpierw połączenie.');
    return;
  }
  _browserTargetField = fieldId;
  _browserConnPk = connPk;
  var url = '/connections/' + connPk + '/browse/?path=' + encodeURIComponent(path)
          + '&field_id=' + encodeURIComponent(fieldId);
  htmx.ajax('GET', url, {target: '#file-browser-content', swap: 'innerHTML'})
    .catch(function() {
      document.getElementById('file-browser-content').innerHTML =
        '<p class="msg-error">> BŁĄD: Brak dostępu do połączenia.</p>';
    });
  document.getElementById('file-browser-overlay').style.display = 'flex';
}

function selectPath(path) {
  document.getElementById(_browserTargetField).value = path;
  closeBrowser();
}

function closeBrowser() {
  document.getElementById('file-browser-overlay').style.display = 'none';
}
```

`field_id` is passed as query param so the backend includes it in the fragment context, enabling navigation links inside the fragment to call `openBrowser` with the correct target field.

---

## Section 3: Form Integration

### Transfer Now (`transfers/create.html`) — `destination_path` only

```html
<label>DESTINATION PATH</label>
<div class="field-with-btn">
  {{ form.destination_path }}
  <button type="button"
    onclick="openBrowser('id_destination_path', document.getElementById('id_connection').value)">
    [BROWSE]
  </button>
</div>
```

### Flow (`flows/create.html` and `flows/edit.html`) — both path fields

```html
<label>SOURCE PATH</label>
<div class="field-with-btn">
  {{ form.source_path }}
  <button type="button"
    onclick="openBrowser('id_source_path', document.getElementById('id_source_conn').value)">
    [BROWSE]
  </button>
</div>

<label>DEST PATH</label>
<div class="field-with-btn">
  {{ form.dest_path }}
  <button type="button"
    onclick="openBrowser('id_dest_path', document.getElementById('id_dest_conn').value)">
    [BROWSE]
  </button>
</div>
```

Buttons are `type="button"` — do not submit the form.

---

## Section 4: Error Handling

| Scenario | Handling |
|---|---|
| Connection not owned by user | `get_object_or_404` → 404; JS `.catch()` shows error in modal |
| SSH failure (timeout, auth error) | `except Exception` in view → fragment with `error` message (HTTP 200) |
| Path does not exist | `IOError` caught same as SSH failure |
| Empty directory | `entries = []` → fragment shows `> (pusty katalog)` |
| No connection selected | JS guard: `if (!connPk) { alert(...); return; }` |

All error states are rendered inside the modal — no full-page errors.

---

## Section 5: Testing

New file: `apps/connections/tests/test_browser.py`

### View tests (6 tests)

```python
@pytest.mark.django_db
class TestBrowseDirectory:
    def test_returns_fragment_for_valid_path(self, client, django_user_model, mocker): ...
    def test_requires_login(self, client): ...
    def test_returns_404_for_other_users_connection(self, client, django_user_model): ...
    def test_renders_error_on_ssh_failure(self, client, django_user_model, mocker): ...
    def test_empty_directory_renders_empty_message(self, client, django_user_model, mocker): ...
    def test_field_id_passed_through_to_fragment(self, client, django_user_model, mocker): ...
```

### Unit tests for `sftp_utils.py` (2 tests)

```python
def test_list_directory_sorts_dirs_first(mocker): ...
def test_build_breadcrumbs_returns_correct_crumbs(): ...
```

All SFTP calls mocked via `mocker.patch` — no real SSH connections in tests.

---

## Files Changed

| File | Action |
|---|---|
| `apps/connections/views.py` | Add `browse_directory` view |
| `apps/connections/urls.py` | Add `browse/` URL pattern |
| `apps/connections/sftp_utils.py` | New — SFTP helper functions |
| `templates/connections/browser_fragment.html` | New — HTMX fragment |
| `templates/base.html` | Add modal overlay + JS |
| `templates/transfers/create.html` | Add [BROWSE] button for destination_path |
| `templates/flows/create.html` | Add [BROWSE] buttons for source/dest paths |
| `templates/flows/edit.html` | Add [BROWSE] buttons for source/dest paths |
| `apps/connections/tests/test_browser.py` | New — 8 tests |
