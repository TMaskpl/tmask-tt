# File Browser Modal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an HTMX-driven modal that lets users browse remote SSH filesystems and click-to-insert paths into Transfer Now and Flow forms.

**Architecture:** New `browse_directory` view in `connections/views.py` uses a shared `sftp_utils.py` helper to list a remote directory via paramiko SFTP. HTMX swaps a fragment into a global modal overlay in `base.html`. Three JS functions (`openBrowser`, `selectPath`, `closeBrowser`) handle modal lifecycle. No new libraries.

**Tech Stack:** Django 5.x, paramiko (already in requirements), HTMX 1.9.12 (already loaded in base.html), pytest + pytest-mock.

---

## Files Changed

| File | Action |
|---|---|
| `apps/connections/sftp_utils.py` | Create — SFTP helper: `list_directory`, `build_breadcrumbs` |
| `apps/connections/tests/test_sftp_utils.py` | Create — unit tests for sftp_utils |
| `apps/connections/views.py` | Modify — add `browse_directory` view |
| `apps/connections/urls.py` | Modify — add `browse/` URL pattern |
| `templates/connections/browser_fragment.html` | Create — HTMX fragment with breadcrumbs + file list |
| `apps/connections/tests/test_browser.py` | Create — view tests for browse_directory |
| `templates/base.html` | Modify — add modal overlay HTML + JS |
| `static/css/crt.css` | Modify — add modal + file browser CSS |
| `templates/transfers/create.html` | Modify — [BROWSE] button on destination_path |
| `templates/flows/form.html` | Modify — [BROWSE] buttons on source_path + dest_path |

---

## Task 1: SFTP utilities module

**Files:**
- Create: `services/web/apps/connections/sftp_utils.py`
- Create: `services/web/apps/connections/tests/test_sftp_utils.py`

- [ ] **Step 1: Write the failing unit tests**

Create `services/web/apps/connections/tests/test_sftp_utils.py`:

```python
import stat as stat_module
from types import SimpleNamespace

import pytest

from apps.connections.sftp_utils import build_breadcrumbs, list_directory


def _conn(**kwargs):
    defaults = dict(
        host='localhost', port=22, username='u', password='pass',
        ssh_key=None, strict_host_key_checking=False, known_host_key=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestBuildBreadcrumbs:
    def test_root_returns_single_crumb(self):
        result = build_breadcrumbs('/')
        assert result == [{'label': '/', 'path': '/'}]

    def test_nested_path_returns_all_crumbs(self):
        result = build_breadcrumbs('/home/user')
        assert result == [
            {'label': '/', 'path': '/'},
            {'label': 'home', 'path': '/home'},
            {'label': 'user', 'path': '/home/user'},
        ]

    def test_trailing_slash_ignored(self):
        result = build_breadcrumbs('/home/')
        assert len(result) == 2
        assert result[-1]['path'] == '/home'


class TestListDirectory:
    def test_sorts_dirs_before_files(self, mocker):
        conn = _conn()
        file_attr = SimpleNamespace(
            filename='readme.txt',
            st_mode=stat_module.S_IFREG | 0o644,
            st_size=512,
        )
        dir_attr = SimpleNamespace(
            filename='docs',
            st_mode=stat_module.S_IFDIR | 0o755,
            st_size=4096,
        )
        mock_client = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mock_client)
        mock_sftp = mocker.MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.listdir_attr.return_value = [file_attr, dir_attr]

        result = list_directory(conn, '/')

        assert result[0].name == 'docs'
        assert result[0].is_dir is True
        assert result[1].name == 'readme.txt'
        assert result[1].is_dir is False

    def test_full_path_constructed_correctly(self, mocker):
        conn = _conn()
        attr = SimpleNamespace(
            filename='archive.tar',
            st_mode=stat_module.S_IFREG | 0o644,
            st_size=1024,
        )
        mock_client = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mock_client)
        mock_sftp = mocker.MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.listdir_attr.return_value = [attr]

        result = list_directory(conn, '/home/user')

        assert result[0].full_path == '/home/user/archive.tar'

    def test_empty_directory_returns_empty_list(self, mocker):
        conn = _conn()
        mock_client = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mock_client)
        mock_sftp = mocker.MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.listdir_attr.return_value = []

        result = list_directory(conn, '/')

        assert result == []

    def test_uses_ssh_key_when_provided(self, mocker):
        conn = _conn(ssh_key='--- FAKE KEY ---', password=None)
        mock_client = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mock_client)
        mock_pkey = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.PKey.from_private_key', return_value=mock_pkey)
        mock_sftp = mocker.MagicMock()
        mock_client.open_sftp.return_value = mock_sftp
        mock_sftp.listdir_attr.return_value = []

        list_directory(conn, '/')

        call_kwargs = mock_client.connect.call_args.kwargs
        assert call_kwargs['pkey'] == mock_pkey
        assert 'password' not in call_kwargs

    def test_raises_when_no_credentials(self, mocker):
        conn = _conn(password=None, ssh_key=None)
        mock_client = mocker.MagicMock()
        mocker.patch('apps.connections.sftp_utils.paramiko.SSHClient', return_value=mock_client)

        with pytest.raises(ValueError, match='Brak danych uwierzytelniania'):
            list_directory(conn, '/')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/web
pytest apps/connections/tests/test_sftp_utils.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'apps.connections.sftp_utils'`

- [ ] **Step 3: Create `sftp_utils.py`**

Create `services/web/apps/connections/sftp_utils.py`:

```python
import io
import os
import stat
import tempfile
from types import SimpleNamespace

import paramiko


def _build_client(connection):
    client = paramiko.SSHClient()
    if connection.strict_host_key_checking and connection.known_host_key:
        with tempfile.NamedTemporaryFile(mode='w', suffix='_known_hosts', delete=False) as f:
            f.write(connection.known_host_key)
            tmp_path = f.name
        try:
            client.load_host_keys(tmp_path)
        finally:
            os.unlink(tmp_path)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def list_directory(connection, path):
    """List remote directory entries via SFTP, sorted: dirs first then files."""
    if not connection.password and not connection.ssh_key:
        raise ValueError('Brak danych uwierzytelniania')

    client = _build_client(connection)
    try:
        connect_kwargs = {
            'hostname': connection.host,
            'port': connection.port,
            'username': connection.username,
            'timeout': 10,
            'look_for_keys': False,
            'allow_agent': False,
        }
        if connection.ssh_key:
            connect_kwargs['pkey'] = paramiko.PKey.from_private_key(io.StringIO(connection.ssh_key))
        else:
            connect_kwargs['password'] = connection.password

        client.connect(**connect_kwargs)
        sftp = client.open_sftp()
        try:
            attrs = sftp.listdir_attr(path)
        finally:
            sftp.close()
    finally:
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
    return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))


def build_breadcrumbs(path):
    """Return list of {'label', 'path'} dicts for each component of path."""
    parts = [p for p in path.split('/') if p]
    crumbs = [{'label': '/', 'path': '/'}]
    for i, part in enumerate(parts):
        crumbs.append({
            'label': part,
            'path': '/' + '/'.join(parts[:i + 1]),
        })
    return crumbs
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/web
pytest apps/connections/tests/test_sftp_utils.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/connections/sftp_utils.py \
        services/web/apps/connections/tests/test_sftp_utils.py
git commit -m "feat: add sftp_utils with list_directory and build_breadcrumbs"
```

---

## Task 2: Browse directory view + URL

**Files:**
- Create: `services/web/apps/connections/tests/test_browser.py`
- Modify: `services/web/apps/connections/views.py` (add `browse_directory`)
- Modify: `services/web/apps/connections/urls.py` (add `browse/` pattern)
- Create: `services/web/templates/connections/browser_fragment.html`

- [ ] **Step 1: Write the failing view tests**

Create `services/web/apps/connections/tests/test_browser.py`:

```python
import pytest
from django.urls import reverse

from apps.connections.models import Connection


@pytest.mark.django_db
class TestBrowseDirectory:
    def _url(self, pk, path='/', field_id='id_destination_path'):
        return reverse('connections:browse', args=[pk]) + f'?path={path}&field_id={field_id}'

    def test_requires_login(self, client, regular_user, make_connection):
        conn = make_connection(regular_user)
        resp = client.get(self._url(conn.pk))
        assert resp.status_code == 302
        assert '/login/' in resp['Location']

    def test_returns_fragment_for_valid_path(self, auth_client, regular_user, make_connection, mocker):
        conn = make_connection(regular_user)
        from types import SimpleNamespace
        entries = [
            SimpleNamespace(name='docs', is_dir=True, full_path='/docs', size=None),
            SimpleNamespace(name='file.txt', is_dir=False, full_path='/file.txt', size=512),
        ]
        mocker.patch('apps.connections.views.list_directory', return_value=entries)

        resp = auth_client.get(self._url(conn.pk))

        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'docs' in content
        assert 'file.txt' in content

    def test_returns_404_for_other_users_connection(self, auth_client, admin_user, make_connection):
        conn = make_connection(admin_user)
        resp = auth_client.get(self._url(conn.pk))
        assert resp.status_code == 404

    def test_renders_error_message_on_ssh_failure(self, auth_client, regular_user, make_connection, mocker):
        conn = make_connection(regular_user)
        mocker.patch(
            'apps.connections.views.list_directory',
            side_effect=Exception('Connection refused'),
        )

        resp = auth_client.get(self._url(conn.pk))

        assert resp.status_code == 200
        assert 'Connection refused' in resp.content.decode()

    def test_empty_directory_shows_empty_message(self, auth_client, regular_user, make_connection, mocker):
        conn = make_connection(regular_user)
        mocker.patch('apps.connections.views.list_directory', return_value=[])

        resp = auth_client.get(self._url(conn.pk))

        assert resp.status_code == 200
        assert 'pusty katalog' in resp.content.decode()

    def test_field_id_passed_through_to_fragment(self, auth_client, regular_user, make_connection, mocker):
        conn = make_connection(regular_user)
        mocker.patch('apps.connections.views.list_directory', return_value=[])

        resp = auth_client.get(self._url(conn.pk, field_id='id_dest_path'))

        assert resp.status_code == 200
        assert 'id_dest_path' in resp.content.decode()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/web
pytest apps/connections/tests/test_browser.py -v
```

Expected: `ERROR` — `NoReverseMatch: Reverse for 'browse' not found`

- [ ] **Step 3: Add `browse_directory` view**

In `services/web/apps/connections/views.py`, add at the top with existing imports:

```python
from .sftp_utils import list_directory, build_breadcrumbs
```

Then add at the end of the file:

```python
@login_required
def browse_directory(request, pk):
    connection = get_object_or_404(Connection, pk=pk, owner=request.user)
    path = request.GET.get('path', '/')
    field_id = request.GET.get('field_id', '')
    try:
        entries = list_directory(connection, path)
        error = None
    except Exception as e:
        entries = []
        error = str(e)
    return render(request, 'connections/browser_fragment.html', {
        'entries': entries,
        'breadcrumbs': build_breadcrumbs(path),
        'error': error,
        'conn_pk': pk,
        'current_path': path,
        'field_id': field_id,
    })
```

- [ ] **Step 4: Add URL pattern**

In `services/web/apps/connections/urls.py`, add to `urlpatterns`:

```python
path('<int:pk>/browse/', views.browse_directory, name='browse'),
```

Full file after change:

```python
from django.urls import path
from . import views

app_name = 'connections'

urlpatterns = [
    path('', views.connection_list, name='list'),
    path('new/', views.connection_create, name='create'),
    path('<int:pk>/edit/', views.connection_edit, name='edit'),
    path('<int:pk>/delete/', views.connection_delete, name='delete'),
    path('<int:pk>/test/', views.connection_test, name='test'),
    path('<int:pk>/browse/', views.browse_directory, name='browse'),
]
```

- [ ] **Step 5: Create fragment template**

Create `services/web/templates/connections/browser_fragment.html`:

```html
{% if error %}
<p class="msg-error">&gt; {{ error }}</p>
{% else %}
<div class="breadcrumbs">
  {% for crumb in breadcrumbs %}<a href="#" onclick="openBrowser('{{ field_id }}', {{ conn_pk }}, '{{ crumb.path }}'); return false;">{{ crumb.label }}</a>{% if not forloop.last %} / {% endif %}{% endfor %}
</div>
<ul class="file-list">
  {% for entry in entries %}
  <li>
    {% if entry.is_dir %}
    <a href="#" onclick="openBrowser('{{ field_id }}', {{ conn_pk }}, '{{ entry.full_path }}'); return false;">[DIR] {{ entry.name }}</a>
    {% else %}
    <a href="#" onclick="selectPath('{{ entry.full_path }}'); return false;">{{ entry.name }}</a>
    {% endif %}
  </li>
  {% empty %}
  <li>&gt; (pusty katalog)</li>
  {% endfor %}
</ul>
{% endif %}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd services/web
pytest apps/connections/tests/test_browser.py -v
```

Expected: `6 passed`

- [ ] **Step 7: Run full test suite**

```bash
cd services/web
pytest -v
```

Expected: all previously passing tests still pass (no regressions).

- [ ] **Step 8: Commit**

```bash
git add services/web/apps/connections/views.py \
        services/web/apps/connections/urls.py \
        services/web/templates/connections/browser_fragment.html \
        services/web/apps/connections/tests/test_browser.py
git commit -m "feat: add browse_directory view and HTMX fragment template"
```

---

## Task 3: Modal overlay, CSS, and JS

**Files:**
- Modify: `services/web/templates/base.html`
- Modify: `services/web/static/css/crt.css`

No automated tests — verify manually after Task 4.

- [ ] **Step 1: Add CSS for modal and file browser**

In `services/web/static/css/crt.css`, append after the last line (line 181, after `.msg-success`):

```css

/* File Browser Modal */
#file-browser-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

#file-browser-modal {
  background: var(--bg);
  border: 1px solid var(--border);
  padding: 1.5rem;
  width: min(700px, 90vw);
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  position: relative;
}

#file-browser-content {
  overflow-y: auto;
  flex: 1;
  min-height: 200px;
}

.breadcrumbs {
  font-size: 0.85rem;
  color: var(--amber);
  margin-bottom: 0.5rem;
  word-break: break-all;
}

.breadcrumbs a { color: var(--amber); text-decoration: none; }
.breadcrumbs a:hover { color: var(--green-bright); }

.file-list { list-style: none; padding: 0; }
.file-list li { padding: 0.25rem 0; border-bottom: 1px solid var(--dim); }
.file-list a { color: var(--green); text-decoration: none; }
.file-list a:hover { color: var(--green-bright); }

.field-with-btn { display: flex; gap: 0.5rem; align-items: center; }
.field-with-btn input,
.field-with-btn select { flex: 1; }
.btn-small { padding: 0.4rem 0.6rem; letter-spacing: 1px; font-size: 0.8rem; white-space: nowrap; }
```

- [ ] **Step 2: Add modal HTML and JS to `base.html`**

In `services/web/templates/base.html`, replace the closing `</body>` tag with:

```html
  <div id="file-browser-overlay" style="display:none">
    <div id="file-browser-modal">
      <span class="box-title">FILE BROWSER</span>
      <div id="file-browser-content"></div>
      <button type="button" class="btn btn-danger" onclick="closeBrowser()">[ ZAMKNIJ ]</button>
    </div>
  </div>
  <script>
    var _browserTargetField = null;

    function openBrowser(fieldId, connPk, path) {
      if (!connPk) {
        alert('Wybierz najpierw połączenie.');
        return;
      }
      path = path || '/';
      _browserTargetField = fieldId;
      var url = '/connections/' + connPk + '/browse/?path=' + encodeURIComponent(path)
              + '&field_id=' + encodeURIComponent(fieldId);
      htmx.ajax('GET', url, {target: '#file-browser-content', swap: 'innerHTML'})
        .catch(function () {
          document.getElementById('file-browser-content').innerHTML =
            '<p class="msg-error">&gt; BŁĄD: Brak dostępu do połączenia.</p>';
        });
      document.getElementById('file-browser-overlay').style.display = 'flex';
    }

    function selectPath(path) {
      document.getElementById(_browserTargetField).value = path;
      closeBrowser();
    }

    function closeBrowser() {
      document.getElementById('file-browser-overlay').style.display = 'none';
      document.getElementById('file-browser-content').innerHTML = '';
    }
  </script>
</body>
```

- [ ] **Step 3: Run full test suite to confirm no regressions**

```bash
cd services/web
pytest -v
```

Expected: all tests still pass.

- [ ] **Step 4: Commit**

```bash
git add services/web/templates/base.html \
        services/web/static/css/crt.css
git commit -m "feat: add file browser modal overlay and JS"
```

---

## Task 4: Transfer Now form — [BROWSE] on destination_path

**Files:**
- Modify: `services/web/templates/transfers/create.html`

The current template loops `{% for field in form %}` and renders all fields identically. We add a conditional inside the loop to render `destination_path` with a [BROWSE] button.

- [ ] **Step 1: Modify `transfers/create.html`**

Replace the `{% for field in form %}` block (lines 9–15) with:

```html
      {% for field in form %}
      <div class="field">
        <label>{{ field.label|upper }}:</label>
        {% if field.html_name == 'destination_path' %}
        <div class="field-with-btn">
          {{ field }}
          <button type="button" class="btn btn-small"
            onclick="openBrowser('id_destination_path', document.getElementById('id_connection').value)">
            [BROWSE]
          </button>
        </div>
        {% else %}
        {{ field }}
        {% endif %}
        {% if field.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ field.errors }}</div>{% endif %}
      </div>
      {% endfor %}
```

- [ ] **Step 2: Start dev server and verify manually**

```bash
cd /path/to/tmask-tt
docker compose up web -d
```

Open `http://localhost:8000/transfers/create/` and confirm:
- [BROWSE] button appears next to DESTINATION PATH field
- SOURCE PATH and CONNECTION fields render without buttons
- Clicking [BROWSE] with no connection selected shows `alert('Wybierz najpierw połączenie.')`
- After selecting a connection and clicking [BROWSE], the modal opens and lists the remote directory
- Clicking a file inserts its path into the DESTINATION PATH field and closes the modal
- Clicking a directory navigates into it (breadcrumbs update)
- [ZAMKNIJ] closes the modal without inserting anything

- [ ] **Step 3: Run test suite**

```bash
cd services/web
pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add services/web/templates/transfers/create.html
git commit -m "feat: add [BROWSE] button for destination_path in Transfer Now form"
```

---

## Task 5: Flow form — [BROWSE] on source_path and dest_path

**Files:**
- Modify: `services/web/templates/flows/form.html`

This template already renders each field individually (not a loop), so we add buttons inline next to the path fields.

- [ ] **Step 1: Modify `flows/form.html`**

Replace the SOURCE PATH field block (lines 24–28):

```html
        <div class="field">
          <label>PATH:</label>
          <div class="field-with-btn">
            {{ form.source_path }}
            <button type="button" class="btn btn-small"
              onclick="openBrowser('id_source_path', document.getElementById('id_source_conn').value)">
              [BROWSE]
            </button>
          </div>
          {% if form.source_path.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.source_path.errors }}</div>{% endif %}
        </div>
```

Replace the DESTINATION PATH field block (lines 37–41):

```html
        <div class="field">
          <label>PATH:</label>
          <div class="field-with-btn">
            {{ form.dest_path }}
            <button type="button" class="btn btn-small"
              onclick="openBrowser('id_dest_path', document.getElementById('id_dest_conn').value)">
              [BROWSE]
            </button>
          </div>
          {% if form.dest_path.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ form.dest_path.errors }}</div>{% endif %}
        </div>
```

- [ ] **Step 2: Verify manually**

Open `http://localhost:8000/flows/new/` (and an existing flow edit page) and confirm:
- [BROWSE] appears next to SOURCE PATH, linked to the SOURCE CONNECTION dropdown
- [BROWSE] appears next to DEST PATH, linked to the DEST CONNECTION dropdown
- Both buttons open the correct modal with the correct connection's filesystem
- Clicking a file inserts path into the correct field and closes the modal
- Clicking [BROWSE] before selecting a connection shows alert

- [ ] **Step 3: Run full test suite**

```bash
cd services/web
pytest -v
```

Expected: all tests pass (no regressions in flow tests).

- [ ] **Step 4: Commit**

```bash
git add services/web/templates/flows/form.html
git commit -m "feat: add [BROWSE] buttons to Flow form source and dest path fields"
```
