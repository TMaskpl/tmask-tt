# Import/export konfiguracji (JSON backup) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eksport konfiguracji użytkownika (Connections + Flows) do pliku JSON z sekretami szyfrowanymi passphrasą, oraz idempotentny import z powrotem.

**Architecture:** Czysty moduł `apps/connections/portability.py` (serializacja + krypto PBKDF2/Fernet, testowalny bez HTTP), zasilający dwa cienkie widoki `@login_required @require_POST`. Sekrety (`password`, `ssh_key`) szyfrowane kluczem wyprowadzonym z hasła; reszta JSON czytelna. Flows referują połączenia po nazwie; import pomija istniejące nazwy.

**Tech Stack:** Python 3.12, Django 5.x, `cryptography` (Fernet + PBKDF2HMAC), pytest. Kontener Docker `web`.

## Global Constraints

- Web NIE ma bind-mountu — po zmianie kodu rebuild: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1` PRZED testami.
- Testy: `docker compose exec -T web python -m pytest apps/connections/ -q`. Stack musi działać.
- Polecenia z `/Users/dniemczok/Desktop/TMaskPL/tmask-tt`.
- `cryptography` jest dostępne (zweryfikowane). Importy: `from cryptography.fernet import Fernet, InvalidToken`, `from cryptography.hazmat.primitives.hashes import SHA256`, `from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC`.
- Izolacja per-user: eksport wyłącznie `Connection/Flow.objects.filter(owner=user)`; import zawsze `owner=user`.
- Stałe: `FORMAT="tmask-transporter-config"`, `VERSION=1`, `KDF_ITERATIONS=600000`, `CHECK_MARKER=b"tmask-config-v1"`.
- Konflikt importu = skip po nazwie (idempotentnie). Tylko Connections + Flows.
- TDD: czerwony test przed implementacją. Commity: prefiks `feat:`, opis po polsku, stopka `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Gałąź `feat/config-import-export` (utworzona, spec zacommitowany).
- Fixtures (w `services/web/conftest.py`): `regular_user`, `admin_user`, `auth_client` (zalogowany jako regular_user), `make_connection(user, **kwargs)` (defaults: name='Test', host='localhost', port=22, username='u', password='p', protocol='sftp'), `make_flow(user, **kwargs)` (tworzy połączenia 'FlowSrc'/'FlowDst' + Flow 'Test Flow').

---

### Task 1: Krypto + `export_config` (portability.py)

**Files:**
- Create: `services/web/apps/connections/portability.py`
- Test: `services/web/apps/connections/tests/test_portability.py`

**Interfaces:**
- Consumes: `Connection` (`.models`), `Flow` (`apps.flows.models`).
- Produces:
  - Stałe `FORMAT`, `VERSION`, `KDF_ITERATIONS`, `CHECK_MARKER`, lista `CONNECTION_FIELDS`.
  - `_derive_key(passphrase: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes` (klucz Fernet, b64).
  - `_encrypt_secret(plaintext, fernet) -> str | None`, `_decrypt_secret(token, fernet) -> str | None`.
  - `export_config(user, passphrase: str) -> dict` (struktura z `format`/`version`/`kdf`/`check`/`connections`/`flows`).

- [ ] **Step 1: Napisz czerwone testy `TestExportConfig`**

Utwórz `services/web/apps/connections/tests/test_portability.py`:

```python
import pytest
from apps.connections import portability
from apps.connections.models import Connection


@pytest.mark.django_db
class TestExportConfig:
    def test_export_has_format_version_and_kdf(self, regular_user, make_connection):
        make_connection(regular_user, name='C1')
        data = portability.export_config(regular_user, 'pass123')
        assert data['format'] == 'tmask-transporter-config'
        assert data['version'] == 1
        assert 'salt' in data['kdf']
        assert data['check']

    def test_export_secrets_not_plaintext(self, regular_user, make_connection):
        make_connection(regular_user, name='C1', password='supersecret', ssh_key='PRIVATEKEY')
        data = portability.export_config(regular_user, 'pass123')
        blob = str(data)
        assert 'supersecret' not in blob
        assert 'PRIVATEKEY' not in blob
        row = data['connections'][0]
        assert row['password_enc'] and row['password_enc'] != 'supersecret'

    def test_export_only_owners_records(self, regular_user, admin_user, make_connection):
        make_connection(regular_user, name='Mine')
        make_connection(admin_user, name='Theirs')
        data = portability.export_config(regular_user, 'pass123')
        assert [c['name'] for c in data['connections']] == ['Mine']
```

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/connections/tests/test_portability.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.connections.portability'`

- [ ] **Step 3: Zaimplementuj krypto + `export_config`**

Utwórz `services/web/apps/connections/portability.py`:

```python
import base64
import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from apps.flows.models import Flow
from .models import Connection

FORMAT = "tmask-transporter-config"
VERSION = 1
KDF_ITERATIONS = 600000
CHECK_MARKER = b"tmask-config-v1"

CONNECTION_FIELDS = [
    'name', 'host', 'port', 'username', 'protocol', 'compress', 'encrypt',
    'strict_host_key_checking', 'known_host_key', 'dry_run_before_transfer',
    'verify_checksum',
]


class PassphraseError(Exception):
    pass


@dataclass
class ImportResult:
    conn_added: int = 0
    conn_skipped: int = 0
    flow_added: int = 0
    flow_skipped: int = 0
    flow_unresolved: int = 0


def _derive_key(passphrase: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=iterations)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def _encrypt_secret(plaintext, fernet: Fernet):
    if not plaintext:
        return None
    return fernet.encrypt(plaintext.encode()).decode()


def _decrypt_secret(token, fernet: Fernet):
    if token is None:
        return None
    return fernet.decrypt(token.encode()).decode()


def export_config(user, passphrase: str) -> dict:
    salt = os.urandom(16)
    fernet = Fernet(_derive_key(passphrase, salt))
    connections = []
    for c in Connection.objects.filter(owner=user):
        row = {f: getattr(c, f) for f in CONNECTION_FIELDS}
        row['password_enc'] = _encrypt_secret(c.password, fernet)
        row['ssh_key_enc'] = _encrypt_secret(c.ssh_key, fernet)
        connections.append(row)
    flows = []
    for fl in Flow.objects.filter(owner=user):
        flows.append({
            'name': fl.name,
            'source_conn': fl.source_conn.name,
            'source_path': fl.source_path,
            'dest_conn': fl.dest_conn.name,
            'dest_path': fl.dest_path,
            'verify_checksum': fl.verify_checksum,
        })
    return {
        'format': FORMAT,
        'version': VERSION,
        'kdf': {
            'algo': 'pbkdf2_sha256',
            'iterations': KDF_ITERATIONS,
            'salt': base64.b64encode(salt).decode(),
        },
        'check': fernet.encrypt(CHECK_MARKER).decode(),
        'connections': connections,
        'flows': flows,
    }
```

- [ ] **Step 4: Uruchom testy — zielone**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/connections/tests/test_portability.py -q`
Expected: PASS — 3 testy

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/connections/portability.py services/web/apps/connections/tests/test_portability.py
git commit -m "$(cat <<'EOF'
feat: portability.py — krypto PBKDF2/Fernet + export_config

Eksport Connections + Flows do dict; sekrety szyfrowane passphrasą,
flows referują połączenia po nazwie.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `import_config` (skip / resolve / passphrase)

**Files:**
- Modify: `services/web/apps/connections/portability.py`
- Test: `services/web/apps/connections/tests/test_portability.py`

**Interfaces:**
- Consumes: `_derive_key`, `_decrypt_secret`, `CHECK_MARKER`, `CONNECTION_FIELDS`, `ImportResult`, `PassphraseError`, `FORMAT`, `VERSION` z Task 1; `Connection`, `Flow`.
- Produces: `import_config(user, data: dict, passphrase: str) -> ImportResult` (rzuca `PassphraseError` przy złym haśle, `ValueError` przy złym formacie).

- [ ] **Step 1: Napisz czerwone testy `TestImportConfig`**

Dodaj do `services/web/apps/connections/tests/test_portability.py`:

```python
@pytest.mark.django_db
class TestImportConfig:
    def test_roundtrip_restores_secrets(self, regular_user, admin_user, make_connection):
        make_connection(regular_user, name='Prod', host='1.2.3.4',
                        password='topsecret', ssh_key='KEYDATA')
        data = portability.export_config(regular_user, 'pw')
        result = portability.import_config(admin_user, data, 'pw')
        assert result.conn_added == 1
        c = Connection.objects.get(owner=admin_user, name='Prod')
        assert c.host == '1.2.3.4'
        assert c.password == 'topsecret'
        assert c.ssh_key == 'KEYDATA'

    def test_import_wrong_passphrase_raises(self, regular_user, admin_user, make_connection):
        make_connection(regular_user, name='Prod', password='x')
        data = portability.export_config(regular_user, 'right')
        with pytest.raises(portability.PassphraseError):
            portability.import_config(admin_user, data, 'wrong')
        assert Connection.objects.filter(owner=admin_user).count() == 0

    def test_import_skips_existing_by_name(self, regular_user, admin_user, make_connection):
        make_connection(regular_user, name='Dup', host='orig')
        data = portability.export_config(regular_user, 'pw')
        make_connection(admin_user, name='Dup', host='local')
        result = portability.import_config(admin_user, data, 'pw')
        assert result.conn_added == 0
        assert result.conn_skipped == 1
        assert Connection.objects.get(owner=admin_user, name='Dup').host == 'local'

    def test_flow_references_resolved_by_name(self, regular_user, admin_user, make_flow):
        make_flow(regular_user, name='Relay1')
        data = portability.export_config(regular_user, 'pw')
        result = portability.import_config(admin_user, data, 'pw')
        assert result.flow_added == 1
        from apps.flows.models import Flow
        fl = Flow.objects.get(owner=admin_user, name='Relay1')
        assert fl.source_conn.owner == admin_user
        assert fl.source_conn.name == 'FlowSrc'
        assert fl.dest_conn.name == 'FlowDst'

    def test_flow_with_missing_connection_unresolved(self, regular_user, admin_user, make_flow):
        make_flow(regular_user, name='Relay1')
        data = portability.export_config(regular_user, 'pw')
        data['connections'] = []  # usuń połączenia, flow nie ma czego rozwiązać
        result = portability.import_config(admin_user, data, 'pw')
        assert result.flow_added == 0
        assert result.flow_unresolved == 1
```

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/connections/tests/test_portability.py::TestImportConfig -q`
Expected: FAIL — `AttributeError: module 'apps.connections.portability' has no attribute 'import_config'`

- [ ] **Step 3: Dodaj `import_config`**

Dodaj na końcu `services/web/apps/connections/portability.py` import transakcji u góry pliku (po istniejących importach `from .models import Connection`):

```python
from django.db import transaction
```

oraz funkcję na końcu pliku:

```python
def import_config(user, data: dict, passphrase: str) -> ImportResult:
    if data.get('format') != FORMAT or data.get('version') != VERSION:
        raise ValueError('Nieprawidłowy format pliku')
    salt = base64.b64decode(data['kdf']['salt'])
    iterations = data['kdf'].get('iterations', KDF_ITERATIONS)
    fernet = Fernet(_derive_key(passphrase, salt, iterations))
    try:
        fernet.decrypt(data['check'].encode())
    except InvalidToken:
        raise PassphraseError('Błędne hasło lub uszkodzony plik')

    result = ImportResult()
    with transaction.atomic():
        existing = set(
            Connection.objects.filter(owner=user).values_list('name', flat=True)
        )
        for row in data.get('connections', []):
            if row['name'] in existing:
                result.conn_skipped += 1
                continue
            conn = Connection(owner=user)
            for f in CONNECTION_FIELDS:
                setattr(conn, f, row.get(f))
            conn.password = _decrypt_secret(row.get('password_enc'), fernet)
            conn.ssh_key = _decrypt_secret(row.get('ssh_key_enc'), fernet)
            conn.save()
            existing.add(row['name'])
            result.conn_added += 1

        conn_map = {c.name: c for c in Connection.objects.filter(owner=user)}
        existing_flows = set(
            Flow.objects.filter(owner=user).values_list('name', flat=True)
        )
        for row in data.get('flows', []):
            if row['name'] in existing_flows:
                result.flow_skipped += 1
                continue
            src = conn_map.get(row['source_conn'])
            dst = conn_map.get(row['dest_conn'])
            if src is None or dst is None:
                result.flow_unresolved += 1
                continue
            Flow.objects.create(
                owner=user, name=row['name'],
                source_conn=src, source_path=row['source_path'],
                dest_conn=dst, dest_path=row['dest_path'],
                verify_checksum=row.get('verify_checksum', False),
            )
            existing_flows.add(row['name'])
            result.flow_added += 1
    return result
```

- [ ] **Step 4: Uruchom testy — całość portability zielona**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/connections/tests/test_portability.py -q`
Expected: PASS — 8 testów (3 export + 5 import)

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/connections/portability.py services/web/apps/connections/tests/test_portability.py
git commit -m "$(cat <<'EOF'
feat: import_config — idempotentny import z walidacją hasła

Walidacja przez pole check (rollback przy złym haśle), skip istniejących
nazw, rozwiązywanie referencji flow po nazwie połączenia.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Widoki export/import + URL

**Files:**
- Modify: `services/web/apps/connections/views.py`
- Modify: `services/web/apps/connections/urls.py`
- Test: `services/web/apps/connections/tests/test_portability_views.py`

**Interfaces:**
- Consumes: `export_config`, `import_config`, `PassphraseError` z portability; fixtures `auth_client`, `regular_user`, `admin_user`, `make_connection`.
- Produces: URL `connections:export`, `connections:import`; widoki `connection_export`, `connection_import`.

- [ ] **Step 1: Napisz czerwone testy widoków**

Utwórz `services/web/apps/connections/tests/test_portability_views.py`:

```python
import json
import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.connections import portability
from apps.connections.models import Connection


@pytest.mark.django_db
class TestExportView:
    def test_export_requires_login(self, client):
        r = client.post(reverse('connections:export'), {'passphrase': 'x'})
        assert r.status_code == 302
        assert '/accounts/login' in r.url

    def test_export_returns_json_attachment(self, auth_client, regular_user, make_connection):
        make_connection(regular_user, name='C1')
        r = auth_client.post(reverse('connections:export'), {'passphrase': 'pw'})
        assert r.status_code == 200
        assert r['Content-Type'] == 'application/json'
        assert 'attachment' in r['Content-Disposition']
        assert json.loads(r.content)['format'] == 'tmask-transporter-config'

    def test_export_requires_passphrase(self, auth_client):
        r = auth_client.post(reverse('connections:export'), {'passphrase': ''})
        assert r.status_code == 302


@pytest.mark.django_db
class TestImportView:
    def test_import_requires_login(self, client):
        r = client.post(reverse('connections:import'))
        assert r.status_code == 302
        assert '/accounts/login' in r.url

    def test_import_creates_records(self, auth_client, regular_user, admin_user, make_connection):
        make_connection(admin_user, name='Imported', host='9.9.9.9', password='sek')
        data = portability.export_config(admin_user, 'pw')
        upload = SimpleUploadedFile('cfg.json', json.dumps(data).encode(), content_type='application/json')
        r = auth_client.post(reverse('connections:import'), {'passphrase': 'pw', 'file': upload})
        assert r.status_code == 302
        c = Connection.objects.get(owner=regular_user, name='Imported')
        assert c.password == 'sek'

    def test_import_wrong_passphrase_shows_error(self, auth_client, regular_user, admin_user, make_connection):
        make_connection(admin_user, name='X', password='s')
        data = portability.export_config(admin_user, 'right')
        upload = SimpleUploadedFile('cfg.json', json.dumps(data).encode(), content_type='application/json')
        r = auth_client.post(reverse('connections:import'), {'passphrase': 'wrong', 'file': upload}, follow=True)
        assert Connection.objects.filter(owner=regular_user).count() == 0
        assert any('Błędne hasło' in str(m) for m in r.context['messages'])

    def test_import_malformed_file_shows_error(self, auth_client, regular_user):
        upload = SimpleUploadedFile('cfg.json', b'not json', content_type='application/json')
        r = auth_client.post(reverse('connections:import'), {'passphrase': 'pw', 'file': upload}, follow=True)
        assert any('Nieprawidłowy' in str(m) for m in r.context['messages'])
```

- [ ] **Step 2: Uruchom testy — sprawdź że padają**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/connections/tests/test_portability_views.py -q`
Expected: FAIL — `django.urls.exceptions.NoReverseMatch: Reverse for 'export' not found`

- [ ] **Step 3: Dodaj widoki**

W `services/web/apps/connections/views.py` dodaj importy po istniejących (po `from django.views.decorators.http import require_POST`):

```python
import json
from datetime import date
from django.contrib import messages
from .portability import export_config, import_config, PassphraseError

_MAX_IMPORT_BYTES = 1024 * 1024
```

Dodaj dwa widoki na końcu pliku:

```python
@login_required
@require_POST
def connection_export(request):
    passphrase = request.POST.get('passphrase', '')
    if not passphrase:
        messages.error(request, 'Podaj hasło do zaszyfrowania eksportu.')
        return redirect(_CONNECTIONS_LIST)
    data = export_config(request.user, passphrase)
    response = JsonResponse(data)
    response['Content-Disposition'] = (
        f'attachment; filename=tmask-config-{date.today().isoformat()}.json'
    )
    return response


@login_required
@require_POST
def connection_import(request):
    passphrase = request.POST.get('passphrase', '')
    upload = request.FILES.get('file')
    if not passphrase or upload is None:
        messages.error(request, 'Wybierz plik i podaj hasło.')
        return redirect(_CONNECTIONS_LIST)
    if upload.size > _MAX_IMPORT_BYTES:
        messages.error(request, 'Plik jest za duży (limit 1 MB).')
        return redirect(_CONNECTIONS_LIST)
    try:
        data = json.loads(upload.read().decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        messages.error(request, 'Nieprawidłowy plik konfiguracji.')
        return redirect(_CONNECTIONS_LIST)
    try:
        result = import_config(request.user, data, passphrase)
    except PassphraseError:
        messages.error(request, 'Błędne hasło lub uszkodzony plik.')
        return redirect(_CONNECTIONS_LIST)
    except (ValueError, KeyError):
        messages.error(request, 'Nieprawidłowy plik konfiguracji.')
        return redirect(_CONNECTIONS_LIST)
    messages.success(
        request,
        f'Dodano {result.conn_added} połączeń (pominięto {result.conn_skipped}), '
        f'{result.flow_added} flows (pominięto {result.flow_skipped}, '
        f'nierozwiązanych {result.flow_unresolved}).'
    )
    return redirect(_CONNECTIONS_LIST)
```

- [ ] **Step 4: Dodaj URL-e**

W `services/web/apps/connections/urls.py` dodaj do `urlpatterns` (po linii `path('<int:pk>/browse/', ...)`):

```python
    path('export/', views.connection_export, name='export'),
    path('import/', views.connection_import, name='import'),
```

- [ ] **Step 5: Uruchom testy — zielone**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/connections/tests/test_portability_views.py -q`
Expected: PASS — 7 testów

- [ ] **Step 6: Commit**

```bash
git add services/web/apps/connections/views.py services/web/apps/connections/urls.py services/web/apps/connections/tests/test_portability_views.py
git commit -m "$(cat <<'EOF'
feat: widoki export/import konfiguracji + URL-e

connection_export (download JSON), connection_import (upload + messages),
limit 1 MB, mapowanie wyjątków na komunikaty.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Przyciski EXPORT/IMPORT w UI + weryfikacja

**Files:**
- Modify: `services/web/templates/connections/list.html`

**Interfaces:**
- Consumes: URL-e `connections:export`, `connections:import` z Task 3.
- Produces: formularze EXPORT/IMPORT w stylu CRT.

> Brak testów jednostkowych (zmiana template). Kończy się pełnym zestawem `apps/connections/` zielonym + weryfikacją manualną.

- [ ] **Step 1: Dodaj przyciski do `list.html`**

W `services/web/templates/connections/list.html` zamień blok:

```html
  <div style="margin-bottom:1rem;">
    <a href="{% url 'connections:create' %}" class="btn">[ + NEW CONNECTION ]</a>
  </div>
```

na:

```html
  <div style="margin-bottom:1rem;display:flex;gap:1rem;flex-wrap:wrap;align-items:center;">
    <a href="{% url 'connections:create' %}" class="btn">[ + NEW CONNECTION ]</a>
    <form method="post" action="{% url 'connections:export' %}" style="display:inline-flex;gap:0.4rem;align-items:center;">
      {% csrf_token %}
      <input type="password" name="passphrase" placeholder="hasło eksportu" required style="width:auto;">
      <button type="submit" class="btn">[ EXPORT ]</button>
    </form>
    <form method="post" action="{% url 'connections:import' %}" enctype="multipart/form-data" style="display:inline-flex;gap:0.4rem;align-items:center;">
      {% csrf_token %}
      <input type="file" name="file" accept="application/json,.json" required style="width:auto;">
      <input type="password" name="passphrase" placeholder="hasło importu" required style="width:auto;">
      <button type="submit" class="btn">[ IMPORT ]</button>
    </form>
  </div>
```

- [ ] **Step 2: Pełny zestaw connections + rebuild**

Run: `docker compose build web >/dev/null 2>&1 && docker compose up -d web >/dev/null 2>&1 && docker compose exec -T web python -m pytest apps/connections/ -q`
Expected: PASS — testy connections (w tym 8 portability + 7 widoków) zielone, brak regresji

- [ ] **Step 3: Weryfikacja manualna**

1. Otwórz `http://localhost/connections/` (zaloguj się). Widoczne przyciski `[ EXPORT ]` i `[ IMPORT ]` obok `[ + NEW CONNECTION ]`.
2. Wpisz hasło eksportu, kliknij `[ EXPORT ]` → pobiera się `tmask-config-YYYY-MM-DD.json`. Otwórz plik: `password_enc`/`ssh_key_enc` to tokeny (nie plaintext), reszta czytelna.
3. (Opcjonalnie) Usuń jedno połączenie, kliknij `[ IMPORT ]`, wybierz pobrany plik + to samo hasło → komunikat „Dodano N połączeń...", połączenie wraca.
4. Import z błędnym hasłem → komunikat „Błędne hasło lub uszkodzony plik", brak zmian.

- [ ] **Step 4: Commit**

```bash
git add services/web/templates/connections/list.html
git commit -m "$(cat <<'EOF'
feat: przyciski EXPORT/IMPORT konfiguracji w UI connections

Formularze passphrase (export) i plik+passphrase (import) w stylu CRT.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Po wdrożeniu (poza planem TDD)

- Aktualizacja docs w vault: `Projekt-tmask-transporter.md` (nowa funkcja import/export), `Propozycje rozbudowy.md` (#8 → zrealizowane), wpis do `LOG.md`.
- `git push` obu repozytoriów po akceptacji.
