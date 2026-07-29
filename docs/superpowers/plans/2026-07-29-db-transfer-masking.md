# Maskowanie danych w transferach DB→DB — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dodać opcjonalny krok maskowania (Faker, format-preserving fake data) wybranych kolumn tekstowych w pipeline transferu DB→DB (Postgres/MySQL/MSSQL), konfigurowalny per (połączenie źródłowe, tabela, kolumna), Admin-only.

**Architecture:** Nowa appka `apps/masking` (model `MaskingRule`, CRUD Admin-only, AJAX introspekcja kolumn) + wspólny moduł `services/worker/modules/masking/` (whitelist generatorów Faker, `mask_value()` z obcinaniem długości) reużywany przez trzy adaptery per silnik: Python relay zastępujący `sed` w `PgTransferHandler` (parsuje bloki `COPY ... FROM stdin`), relay + nowe flagi `mysqldump` w `MysqlTransferHandler` (parsuje `INSERT ... VALUES` po przełączeniu na complete-insert), relay + przełączanie `bcp -n`/`-c` per tabela w `MssqlTransferHandler`.

**Tech Stack:** Django 5.x (web), Celery worker z pełnym Django ORM (`django.setup()`, importuje `apps.*.models` bezpośrednio), Faker (nowa zależność, tylko `services/worker/requirements.txt`), psycopg2/pymysql/pyodbc (już obecne).

## Global Constraints

- **Kanoniczna lista kluczy providerów Faker** (identyczna w `apps/masking/models.py` `FAKER_PROVIDER_CHOICES` i w `services/worker/modules/masking/faker_engine.py` `PROVIDERS` — string musi być bit-for-bit ten sam w obu miejscach): `first_name`, `last_name`, `name`, `email`, `phone_number`, `street_address`, `city`, `postcode`, `country`, `company`, `job_title`.
- **Tabela auto-sugestii** (case-insensitive substring match po nazwie kolumny, pierwsze dopasowanie z góry wygrywa): `first_name`/`given_name`/`firstname`→`first_name`; `last_name`/`surname`/`lastname`→`last_name`; `email`/`mail`→`email`; `phone`/`tel`/`mobile`→`phone_number`; `street`/`address1`/`address_line`→`street_address`; `city`/`town`→`city`; `zip`/`postcode`/`postal`→`postcode`; `country`→`country`; `company`/`employer`/`organization`→`company`; `job`/`title`/`position`→`job_title`; `name`/`fullname` (tylko jeśli nic wcześniejszego nie złapało)→`name`; brak dopasowania→`None`.
- **Maskowalne typy per silnik** (kolumny innych typów są `maskable: False`, nigdy nie trafiają do reguł): Postgres — `character varying`, `varchar`, `text`, `char`, `character`; MySQL — `varchar`, `char`, `text`, `tinytext`, `mediumtext`, `longtext`; MSSQL — `varchar`, `nvarchar`, `char`, `nchar`, `text`, `ntext`.
- **RBAC**: `MaskingRule` list/view = `ROLE_READONLY` (z `apps.accounts.permissions.require_role`), create/edit/delete = `ROLE_ADMIN`. Wzorzec identyczny jak `apps/connections/views.py`.
- **`MaskingRule.connection` to zawsze źródło**, nigdy cel. `unique_together = ('connection', 'table_name', 'column_name')`.
- **Regresja jest obowiązkowa**: gdy dla `(source_connection, table)` nie istnieje żadna `MaskingRule`, wygenerowana komenda (`pg_dump`/`mysqldump`/`bcp`) i strumień danych muszą być bit-for-bit identyczne z zachowaniem sprzed tego planu. Każdy task 6/7/8 musi mieć jawny test regresyjny to potwierdzający.
- **MySQL — efekt uboczny globalny**: `--skip-extended-insert --complete-insert` dodawane do `mysqldump` gdy `source_connection` ma **choć jedną** aktywną `MaskingRule` (niezależnie od tego, która tabela akurat leci) — nie da się tego zrobić per-tabela, bo to flaga na poziomie całego dumpa.
- **MSSQL — per tabela**: `-c` zamiast `-n` w `bcp` tylko dla tabel, które mają choć jedną `MaskingRule` — decyzja per-tabela jest tania, bo `bcp` już dziś leci w pętli po tabelach.
- **Brak profilu dla tabeli w scope CAŁA BAZA** → tabela przechodzi bez maskowania + `log_callback('warn', ...)`, transfer nie failuje.
- **Wartość Faker dłuższa niż `character_maximum_length`** → obcięcie do limitu przed wysłaniem.
- **Sekrety**: `MaskingRule` nie zawiera żadnych sekretów — `changed_fields` w `ConfigAuditLog` może logować wszystkie pola jawnie (brak `secret_fields` w `diff_fields()`).
- **Django app label**: `apps.masking`, URL prefix `/masking/`, `app_name = 'masking'`.

---

### Task 1: Model `MaskingRule` + nowa appka `apps/masking`

**Files:**
- Create: `services/web/apps/masking/__init__.py`
- Create: `services/web/apps/masking/apps.py`
- Create: `services/web/apps/masking/models.py`
- Create: `services/web/apps/masking/admin.py`
- Create: `services/web/apps/masking/migrations/__init__.py`
- Create: `services/web/apps/masking/migrations/0001_initial.py`
- Create: `services/web/apps/masking/tests/__init__.py`
- Create: `services/web/apps/masking/tests/test_models.py`
- Modify: `services/web/config/settings/base.py:28` (INSTALLED_APPS — dodaj `'apps.masking',` po `'apps.db_transfers',`)

**Interfaces:**
- Produces: `apps.masking.models.MaskingRule` (pola: `connection` FK→`connections.Connection`, `table_name` CharField, `column_name` CharField, `faker_provider` CharField z `choices=FAKER_PROVIDER_CHOICES`, `created_by` FK→User nullable, `created_at`, `updated_at`), `apps.masking.models.FAKER_PROVIDER_CHOICES` (lista tupli `(key, label)`), `apps.masking.models.FAKER_PROVIDER_KEYS` (lista samych kluczy, do walidacji w Task 5/6/7/8).

- [ ] **Step 1: Utwórz appkę i model**

`services/web/apps/masking/__init__.py`:
```python
```
(pusty plik)

`services/web/apps/masking/apps.py`:
```python
from django.apps import AppConfig


class MaskingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.masking'
    label = 'masking'
```

`services/web/apps/masking/models.py`:
```python
from django.conf import settings
from django.db import models

FAKER_PROVIDER_CHOICES = [
    ('first_name', 'Imię'),
    ('last_name', 'Nazwisko'),
    ('name', 'Imię i nazwisko'),
    ('email', 'E-mail'),
    ('phone_number', 'Telefon'),
    ('street_address', 'Adres (ulica)'),
    ('city', 'Miasto'),
    ('postcode', 'Kod pocztowy'),
    ('country', 'Kraj'),
    ('company', 'Firma'),
    ('job_title', 'Stanowisko'),
]
FAKER_PROVIDER_KEYS = [key for key, _ in FAKER_PROVIDER_CHOICES]


class MaskingRule(models.Model):
    connection = models.ForeignKey(
        'connections.Connection', on_delete=models.CASCADE, related_name='masking_rules',
    )
    table_name = models.CharField(max_length=255)
    column_name = models.CharField(max_length=255)
    faker_provider = models.CharField(max_length=30, choices=FAKER_PROVIDER_CHOICES)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='masking_rules_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('connection', 'table_name', 'column_name')
        ordering = ['connection', 'table_name', 'column_name']
        verbose_name = 'Reguła maskowania'
        verbose_name_plural = 'Reguły maskowania'

    def __str__(self):
        return f'{self.connection.name}.{self.table_name}.{self.column_name} → {self.get_faker_provider_display()}'
```

`services/web/apps/masking/admin.py`:
```python
from django.contrib import admin
from .models import MaskingRule


@admin.register(MaskingRule)
class MaskingRuleAdmin(admin.ModelAdmin):
    list_display = ('connection', 'table_name', 'column_name', 'faker_provider', 'created_by', 'created_at')
    list_filter = ('faker_provider', 'connection')
```

`services/web/apps/masking/migrations/__init__.py`:
```python
```
(pusty plik)

`services/web/apps/masking/migrations/0001_initial.py` — wygeneruj komendą w Step 2, nie pisz ręcznie.

- [ ] **Step 2: Dodaj appkę do INSTALLED_APPS i wygeneruj migrację**

W `services/web/config/settings/base.py` linia 28, po `'apps.db_transfers',` dodaj:
```python
    'apps.masking',
```

Uruchom (z katalogu repo):
```bash
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python manage.py makemigrations masking
```
Expected: `Migrations for 'masking': ... 0001_initial.py ... - Create model MaskingRule`

- [ ] **Step 3: Napisz test modelu**

`services/web/apps/masking/tests/__init__.py`:
```python
```
(pusty plik)

`services/web/apps/masking/tests/test_models.py`:
```python
import pytest
from django.db.utils import IntegrityError
from apps.connections.models import Connection, KIND_POSTGRES
from apps.masking.models import MaskingRule
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def _make_connection(**kwargs):
    defaults = {
        'name': 'prod-pg', 'host': '10.0.0.1', 'port': 5432, 'username': 'postgres',
        'password': 'pw', 'kind': KIND_POSTGRES, 'db_name': 'proddb',
    }
    defaults.update(kwargs)
    owner = User.objects.create_user(username='owner', password='x')
    return Connection.objects.create(owner=owner, **defaults)


class TestMaskingRule:
    def test_str_includes_connection_table_column_and_provider_label(self):
        conn = _make_connection()
        rule = MaskingRule.objects.create(
            connection=conn, table_name='users', column_name='email', faker_provider='email',
        )
        assert str(rule) == 'prod-pg.users.email → E-mail'

    def test_unique_together_connection_table_column(self):
        conn = _make_connection()
        MaskingRule.objects.create(
            connection=conn, table_name='users', column_name='email', faker_provider='email',
        )
        with pytest.raises(IntegrityError):
            MaskingRule.objects.create(
                connection=conn, table_name='users', column_name='email', faker_provider='name',
            )
```

- [ ] **Step 4: Uruchom testy**

```bash
docker compose --profile test build web-test
docker compose --profile test run --rm web-test pytest apps/masking/ -q --no-cov
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add services/web/apps/masking services/web/config/settings/base.py
git commit -m "feat(masking): model MaskingRule + appka apps.masking"
```

---

### Task 2: Introspekcja kolumn (web) — `list_columns()` per silnik + AJAX endpoint

**Files:**
- Modify: `services/web/apps/connections/pg_utils.py`
- Modify: `services/web/apps/connections/mysql_utils.py`
- Modify: `services/web/apps/connections/mssql_utils.py`
- Modify: `services/web/apps/connections/tests/test_pg_utils.py`
- Modify: `services/web/apps/connections/tests/test_mysql_utils.py`
- Modify: `services/web/apps/connections/tests/test_mssql_utils.py`
- Create: `services/web/apps/masking/views.py`
- Create: `services/web/apps/masking/urls.py`
- Create: `services/web/templates/masking/_columns_options.html`
- Create: `services/web/apps/masking/tests/test_views.py`
- Modify: `services/web/config/urls.py:16` (dodaj `path('masking/', include('apps.masking.urls')),` po linii `db-transfers`)

**Interfaces:**
- Consumes: `apps.connections.models.Connection`, `apps.accounts.permissions.require_role`, `apps.accounts.models.ROLE_READONLY` (Task 1 wcześniejszych appek).
- Produces: `list_columns(connection) -> list[dict]` w każdym z trzech `*_utils.py`, każdy dict ma klucze `name` (str), `data_type` (str, lowercased), `maskable` (bool), `suggested_provider` (str albo `None`) — wywoływany z `table_name` jako drugi argument: `list_columns(connection, table_name)`. Widok `apps.masking.views.masking_columns` (GET, query params `connection` i `table_name`) zwracający fragment `masking/_columns_options.html`.

- [ ] **Step 1: Rozszerz `pg_utils.py` o `list_columns()`**

`services/web/apps/connections/pg_utils.py` — dopisz na końcu pliku:
```python
_PG_MASKABLE_TYPES = {'character varying', 'varchar', 'text', 'char', 'character'}

_SUGGESTION_KEYWORDS = [
    (('first_name', 'given_name', 'firstname'), 'first_name'),
    (('last_name', 'surname', 'lastname'), 'last_name'),
    (('email', 'mail'), 'email'),
    (('phone', 'tel', 'mobile'), 'phone_number'),
    (('street', 'address1', 'address_line'), 'street_address'),
    (('city', 'town'), 'city'),
    (('zip', 'postcode', 'postal'), 'postcode'),
    (('country',), 'country'),
    (('company', 'employer', 'organization'), 'company'),
    (('job', 'title', 'position'), 'job_title'),
    (('name', 'fullname'), 'name'),
]


def suggest_provider(column_name: str) -> str | None:
    lowered = column_name.lower()
    for keywords, provider in _SUGGESTION_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return provider
    return None


def list_columns(connection, table_name: str) -> list:
    conn = psycopg2.connect(
        host=connection.host, port=connection.port, user=connection.username,
        password=connection.password, dbname=connection.db_name, connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name, data_type FROM information_schema.columns '
                "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
                (table_name,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            'name': name, 'data_type': data_type, 'maskable': data_type in _PG_MASKABLE_TYPES,
            'suggested_provider': suggest_provider(name),
        }
        for name, data_type in rows
    ]
```

- [ ] **Step 2: Testy dla `pg_utils.list_columns()`**

Dopisz do `services/web/apps/connections/tests/test_pg_utils.py`:
```python
from unittest.mock import patch, MagicMock
from apps.connections.pg_utils import list_columns, suggest_provider


class TestSuggestProvider:
    def test_matches_email_keyword(self):
        assert suggest_provider('user_email') == 'email'

    def test_matches_first_name_before_generic_name(self):
        assert suggest_provider('first_name') == 'first_name'

    def test_no_match_returns_none(self):
        assert suggest_provider('internal_ref_code') is None


class TestListColumns:
    @patch('apps.connections.pg_utils.psycopg2.connect')
    def test_marks_varchar_as_maskable_with_suggestion(self, mock_connect):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [('email', 'character varying'), ('id', 'integer')]
        mock_connect.return_value.cursor.return_value.__enter__.return_value = mock_cur
        result = list_columns(MagicMock(host='h', port=5432, username='u', password='p', db_name='db'), 'users')
        assert result[0] == {
            'name': 'email', 'data_type': 'character varying', 'maskable': True, 'suggested_provider': 'email',
        }
        assert result[1] == {
            'name': 'id', 'data_type': 'integer', 'maskable': False, 'suggested_provider': None,
        }
```

Run: `docker compose --profile test build web-test && docker compose --profile test run --rm web-test pytest apps/connections/tests/test_pg_utils.py -q --no-cov`
Expected: nowe testy PASS, reszta pliku bez zmian w wyniku.

- [ ] **Step 3: Rozszerz `mysql_utils.py` o `list_columns()`**

`services/web/apps/connections/mysql_utils.py` — dopisz na końcu (importuje `suggest_provider` z `pg_utils`, żeby nie duplikować tabeli słów kluczowych):
```python
from .pg_utils import suggest_provider

_MYSQL_MASKABLE_TYPES = {'varchar', 'char', 'text', 'tinytext', 'mediumtext', 'longtext'}


def list_columns(connection, table_name: str) -> list:
    conn = pymysql.connect(
        host=connection.host, port=connection.port, user=connection.username,
        password=connection.password, database=connection.db_name, connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT column_name, data_type FROM information_schema.columns '
                'WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position',
                (connection.db_name, table_name),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            'name': name, 'data_type': data_type, 'maskable': data_type in _MYSQL_MASKABLE_TYPES,
            'suggested_provider': suggest_provider(name),
        }
        for name, data_type in rows
    ]
```

- [ ] **Step 4: Testy dla `mysql_utils.list_columns()`**

Dopisz do `services/web/apps/connections/tests/test_mysql_utils.py`:
```python
from unittest.mock import patch, MagicMock
from apps.connections.mysql_utils import list_columns


class TestListColumns:
    @patch('apps.connections.mysql_utils.pymysql.connect')
    def test_marks_varchar_as_maskable(self, mock_connect):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [('phone', 'varchar'), ('created_at', 'datetime')]
        mock_connect.return_value.cursor.return_value.__enter__.return_value = mock_cur
        result = list_columns(MagicMock(host='h', port=3306, username='u', password='p', db_name='db'), 'users')
        assert result[0]['maskable'] is True
        assert result[0]['suggested_provider'] == 'phone_number'
        assert result[1]['maskable'] is False
```

Run: `docker compose --profile test build web-test && docker compose --profile test run --rm web-test pytest apps/connections/tests/test_mysql_utils.py -q --no-cov`
Expected: PASS

- [ ] **Step 5: Rozszerz `mssql_utils.py` o `list_columns()`**

`services/web/apps/connections/mssql_utils.py` — dopisz na końcu:
```python
from .pg_utils import suggest_provider

_MSSQL_MASKABLE_TYPES = {'varchar', 'nvarchar', 'char', 'nchar', 'text', 'ntext'}


def list_columns(connection, table_name: str) -> list:
    conn = pyodbc.connect(_conn_string(connection), timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS '
                'WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION',
                table_name,
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [
        {
            'name': row[0], 'data_type': row[1], 'maskable': row[1] in _MSSQL_MASKABLE_TYPES,
            'suggested_provider': suggest_provider(row[0]),
        }
        for row in rows
    ]
```

- [ ] **Step 6: Testy dla `mssql_utils.list_columns()`**

Dopisz do `services/web/apps/connections/tests/test_mssql_utils.py`:
```python
from unittest.mock import patch, MagicMock
from apps.connections.mssql_utils import list_columns


class TestListColumns:
    @patch('apps.connections.mssql_utils.pyodbc.connect')
    def test_marks_nvarchar_as_maskable(self, mock_connect):
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [('company_name', 'nvarchar'), ('is_active', 'bit')]
        mock_connect.return_value.cursor.return_value.__enter__.return_value = mock_cur
        result = list_columns(MagicMock(host='h', port=1433, username='u', password='p', db_name='db'), 'clients')
        assert result[0]['maskable'] is True
        assert result[0]['suggested_provider'] == 'company'
        assert result[1]['maskable'] is False
```

Run: `docker compose --profile test build web-test && docker compose --profile test run --rm web-test pytest apps/connections/tests/test_mssql_utils.py -q --no-cov`
Expected: PASS

- [ ] **Step 7: AJAX endpoint `masking_columns`**

`services/web/apps/masking/urls.py`:
```python
from django.urls import path
from . import views

app_name = 'masking'

urlpatterns = [
    path('columns/', views.masking_columns, name='columns'),
]
```

`services/web/apps/masking/views.py`:
```python
import psycopg2
import pymysql
import pyodbc
from django.shortcuts import render
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_READONLY
from apps.connections.models import Connection, KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL
from apps.connections.pg_utils import list_columns as _list_pg_columns
from apps.connections.mysql_utils import list_columns as _list_mysql_columns
from apps.connections.mssql_utils import list_columns as _list_mssql_columns


@require_role(ROLE_READONLY)
def masking_columns(request):
    conn_id = request.GET.get('connection')
    table_name = request.GET.get('table_name')
    columns = []
    error = None
    if conn_id and table_name:
        conn = Connection.objects.filter(
            pk=conn_id, kind__in=[KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL]
        ).first()
        if conn:
            try:
                if conn.kind == KIND_POSTGRES:
                    columns = _list_pg_columns(conn, table_name)
                elif conn.kind == KIND_MYSQL:
                    columns = _list_mysql_columns(conn, table_name)
                elif conn.kind == KIND_MSSQL:
                    columns = _list_mssql_columns(conn, table_name)
            except (psycopg2.Error, pymysql.Error, pyodbc.Error) as e:
                error = f'Błąd połączenia z bazą źródłową — {e}'.strip()
    return render(request, 'masking/_columns_options.html', {'columns': columns, 'error': error})
```

`services/web/templates/masking/_columns_options.html`:
```html
<select id="id_column_name" name="column_name">
  {% if error %}
  <option value="">— błąd połączenia z bazą źródłową —</option>
  {% elif columns %}
  <option value="">— wybierz kolumnę —</option>
  {% for c in columns %}
  {% if c.maskable %}
  <option value="{{ c.name }}" data-suggested="{{ c.suggested_provider|default:'' }}">{{ c.name }} ({{ c.data_type }})</option>
  {% endif %}
  {% endfor %}
  {% else %}
  <option value="">— brak kolumn tekstowych w tej tabeli —</option>
  {% endif %}
</select>
```

W `services/web/config/urls.py` po linii `path('db-transfers/', include('apps.db_transfers.urls')),` dodaj:
```python
    path('masking/', include('apps.masking.urls')),
```

- [ ] **Step 8: Test widoku**

`services/web/apps/masking/tests/test_views.py`:
```python
import pytest
from django.test import Client
from unittest.mock import patch
from apps.connections.models import Connection, KIND_POSTGRES
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def readonly_client():
    User.objects.create_user(username='ro', password='x', role='readonly')
    client = Client()
    client.login(username='ro', password='x')
    return client


@pytest.fixture
def pg_connection():
    owner = User.objects.create_user(username='owner2', password='x')
    return Connection.objects.create(
        owner=owner, name='prod-pg', host='h', port=5432, username='u', password='p',
        kind=KIND_POSTGRES, db_name='db',
    )


class TestMaskingColumnsView:
    @patch('apps.masking.views._list_pg_columns')
    def test_returns_maskable_columns_for_postgres_connection(self, mock_list, readonly_client, pg_connection):
        mock_list.return_value = [
            {'name': 'email', 'data_type': 'varchar', 'maskable': True, 'suggested_provider': 'email'},
        ]
        response = readonly_client.get(
            '/masking/columns/', {'connection': pg_connection.pk, 'table_name': 'users'}
        )
        assert response.status_code == 200
        assert b'email (varchar)' in response.content

    def test_missing_params_returns_empty_select(self, readonly_client):
        response = readonly_client.get('/masking/columns/')
        assert response.status_code == 200
        assert b'wybierz kolumn' not in response.content
```

Run: `docker compose --profile test build web-test && docker compose --profile test run --rm web-test pytest apps/masking/ apps/connections/tests/test_pg_utils.py apps/connections/tests/test_mysql_utils.py apps/connections/tests/test_mssql_utils.py -q --no-cov`
Expected: wszystkie PASS, `id_column_name` w odpowiedzi dla poprawnych parametrów.

- [ ] **Step 9: Commit**

```bash
git add services/web/apps/connections/pg_utils.py services/web/apps/connections/mysql_utils.py \
  services/web/apps/connections/mssql_utils.py services/web/apps/connections/tests/test_pg_utils.py \
  services/web/apps/connections/tests/test_mysql_utils.py services/web/apps/connections/tests/test_mssql_utils.py \
  services/web/apps/masking/views.py services/web/apps/masking/urls.py services/web/apps/masking/tests/test_views.py \
  services/web/templates/masking/_columns_options.html services/web/config/urls.py
git commit -m "feat(masking): introspekcja kolumn per silnik + AJAX endpoint"
```

---

### Task 3: CRUD `MaskingRule` (Admin-only) + nav + audit log

**Files:**
- Create: `services/web/apps/masking/forms.py`
- Modify: `services/web/apps/masking/views.py`
- Modify: `services/web/apps/masking/urls.py`
- Create: `services/web/templates/masking/list.html`
- Create: `services/web/templates/masking/form.html`
- Create: `services/web/static/js/masking_form.js`
- Modify: `services/web/templates/base.html:22-23` (nav link)
- Modify: `services/web/apps/masking/tests/test_views.py`
- Create: `services/web/apps/masking/tests/test_forms.py`

**Interfaces:**
- Consumes: `apps.audit_log.services.log_created/log_updated/log_deleted/diff_fields` (istniejące), `apps.masking.views.masking_columns` (Task 2), `connections:db_tables` endpoint (istniejący, reużyty bez zmian).
- Produces: URL-e `masking:list`, `masking:create`, `masking:edit`, `masking:delete`.

- [ ] **Step 1: Formularz**

`services/web/apps/masking/forms.py`:
```python
from django import forms
from apps.connections.models import Connection, KIND_DB_KINDS
from .models import MaskingRule


class MaskingRuleForm(forms.ModelForm):
    class Meta:
        model = MaskingRule
        fields = ['connection', 'table_name', 'column_name', 'faker_provider']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['connection'].queryset = Connection.objects.filter(kind__in=KIND_DB_KINDS)
```

- [ ] **Step 2: Widoki CRUD**

Zamień całą zawartość `services/web/apps/masking/views.py` na:
```python
import psycopg2
import pymysql
import pyodbc
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN, ROLE_READONLY
from apps.audit_log.services import log_created, log_updated, log_deleted, diff_fields
from apps.connections.models import Connection, KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL
from apps.connections.pg_utils import list_columns as _list_pg_columns
from apps.connections.mysql_utils import list_columns as _list_mysql_columns
from apps.connections.mssql_utils import list_columns as _list_mssql_columns
from .forms import MaskingRuleForm
from .models import MaskingRule

_MASKING_LIST = 'masking:list'
MASKING_RULE_TRACKED_FIELDS = ['connection', 'table_name', 'column_name', 'faker_provider']


@require_role(ROLE_READONLY)
def masking_list(request):
    rules = MaskingRule.objects.select_related('connection', 'created_by').all()
    return render(request, 'masking/list.html', {'rules': rules})


@require_role(ROLE_ADMIN)
def masking_create(request):
    form = MaskingRuleForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        rule = form.save(commit=False)
        rule.created_by = request.user
        rule.save()
        log_created(request.user, rule)
        return redirect(_MASKING_LIST)
    return render(request, 'masking/form.html', {'form': form, 'action': 'CREATE'})


@require_role(ROLE_ADMIN)
def masking_edit(request, pk):
    rule = get_object_or_404(MaskingRule, pk=pk)
    old = MaskingRule.objects.get(pk=pk)
    form = MaskingRuleForm(request.POST or None, instance=rule)
    if request.method == 'POST' and form.is_valid():
        updated = form.save()
        changes = diff_fields(old, updated, MASKING_RULE_TRACKED_FIELDS)
        log_updated(request.user, updated, changes)
        return redirect(_MASKING_LIST)
    return render(request, 'masking/form.html', {'form': form, 'action': 'EDIT'})


@require_role(ROLE_ADMIN)
@require_POST
def masking_delete(request, pk):
    rule = get_object_or_404(MaskingRule, pk=pk)
    log_deleted(request.user, rule)
    rule.delete()
    return redirect(_MASKING_LIST)


@require_role(ROLE_READONLY)
def masking_columns(request):
    conn_id = request.GET.get('connection')
    table_name = request.GET.get('table_name')
    columns = []
    error = None
    if conn_id and table_name:
        conn = Connection.objects.filter(
            pk=conn_id, kind__in=[KIND_POSTGRES, KIND_MYSQL, KIND_MSSQL]
        ).first()
        if conn:
            try:
                if conn.kind == KIND_POSTGRES:
                    columns = _list_pg_columns(conn, table_name)
                elif conn.kind == KIND_MYSQL:
                    columns = _list_mysql_columns(conn, table_name)
                elif conn.kind == KIND_MSSQL:
                    columns = _list_mssql_columns(conn, table_name)
            except (psycopg2.Error, pymysql.Error, pyodbc.Error) as e:
                error = f'Błąd połączenia z bazą źródłową — {e}'.strip()
    return render(request, 'masking/_columns_options.html', {'columns': columns, 'error': error})
```

(Uwaga dla implementera: `diff_fields` na polu `connection` porówna instancje `Connection` przez `str()` — to zamierzone, `Connection.__str__` zwraca `name (host:port)`, czytelne w logu audytu bez ujawniania sekretów.)

- [ ] **Step 3: URL-e**

Zamień `services/web/apps/masking/urls.py` na:
```python
from django.urls import path
from . import views

app_name = 'masking'

urlpatterns = [
    path('', views.masking_list, name='list'),
    path('new/', views.masking_create, name='create'),
    path('<int:pk>/edit/', views.masking_edit, name='edit'),
    path('<int:pk>/delete/', views.masking_delete, name='delete'),
    path('columns/', views.masking_columns, name='columns'),
]
```

- [ ] **Step 4: Szablony**

`services/web/templates/masking/list.html`:
```html
{% extends "base.html" %}
{% block title %}MASKING RULES — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">Masking Rules</span>
  <div class="toolbar">
    {% if user.is_admin %}
    <a href="{% url 'masking:create' %}" class="btn">+ New Rule</a>
    {% endif %}
  </div>
  {% if rules %}
  <table>
    <thead>
      <tr>
        <th>Connection</th><th>Table</th><th>Column</th><th>Provider</th><th>Utworzył</th>
        {% if user.is_admin %}<th class="col-actions">Actions</th>{% endif %}
      </tr>
    </thead>
    <tbody>
      {% for rule in rules %}
      <tr>
        <td>{{ rule.connection.name }}</td>
        <td>{{ rule.table_name }}</td>
        <td>{{ rule.column_name }}</td>
        <td>{{ rule.get_faker_provider_display }}</td>
        <td>{{ rule.created_by.username|default:"—" }}</td>
        {% if user.is_admin %}
        <td class="col-actions">
          <div class="row-actions">
            <a href="{% url 'masking:edit' rule.pk %}" class="btn btn-small">Edit</a>
            <form method="post" action="{% url 'masking:delete' rule.pk %}" class="inline-form"
              data-confirm="DELETE regułę {{ rule.table_name }}.{{ rule.column_name }}?">
              {% csrf_token %}
              <button type="submit" class="btn btn-small btn-danger">Del</button>
            </form>
          </div>
        </td>
        {% endif %}
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="text-muted">Brak reguł maskowania — dodaj jedną powyżej</p>
  {% endif %}
</div>
{% endblock %}
```

`services/web/templates/masking/form.html`:
```html
{% extends "base.html" %}
{% load static %}
{% block title %}{{ action }} MASKING RULE — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel" style="max-width:600px;">
  <span class="panel-title">{{ action }} Masking Rule</span>
  <form method="post" id="masking-rule-form" data-db-tables-url="{% url 'connections:db_tables' %}"
    data-columns-url="{% url 'masking:columns' %}">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error" style="margin-bottom:1rem;">
      {% for error in form.non_field_errors %}{{ error }}<br>{% endfor %}
    </div>
    {% endif %}
    <div class="field">
      <label>{{ form.connection.label }}</label>
      {{ form.connection }}
      {% if form.connection.errors %}<div class="field-error">{{ form.connection.errors }}</div>{% endif %}
    </div>
    <div class="field">
      <label>{{ form.table_name.label }}</label>
      <select id="id_table_name_picker">
        <option value="">— wybierz najpierw CONNECTION —</option>
      </select>
      <input type="hidden" name="table_name" id="id_table_name" value="{{ form.table_name.value|default:'' }}">
      {% if form.table_name.errors %}<div class="field-error">{{ form.table_name.errors }}</div>{% endif %}
    </div>
    <div class="field">
      <label>{{ form.column_name.label }}</label>
      <select id="id_column_name_picker">
        <option value="">— wybierz najpierw TABLE —</option>
      </select>
      <input type="hidden" name="column_name" id="id_column_name" value="{{ form.column_name.value|default:'' }}">
      {% if form.column_name.errors %}<div class="field-error">{{ form.column_name.errors }}</div>{% endif %}
    </div>
    <div class="field">
      <label>{{ form.faker_provider.label }}</label>
      {{ form.faker_provider }}
      {% if form.faker_provider.errors %}<div class="field-error">{{ form.faker_provider.errors }}</div>{% endif %}
    </div>
    <button type="submit" class="btn">Save Rule</button>
  </form>
</div>
<script src="{% static 'js/masking_form.js' %}"></script>
{% endblock %}
```

- [ ] **Step 5: JS — łańcuch connection → table → column + auto-sugestia**

`services/web/static/js/masking_form.js`:
```javascript
(function () {
  const form = document.getElementById('masking-rule-form');
  if (!form) return;
  const connSel = document.getElementById('id_connection');
  const tablePicker = document.getElementById('id_table_name_picker');
  const tableHidden = document.getElementById('id_table_name');
  const columnPicker = document.getElementById('id_column_name_picker');
  const columnHidden = document.getElementById('id_column_name');
  const providerSel = document.getElementById('id_faker_provider');
  const tablesUrl = form.dataset.dbTablesUrl;
  const columnsUrl = form.dataset.columnsUrl;

  function loadTables() {
    if (!connSel.value) return;
    fetch(tablesUrl + '?source_connection=' + encodeURIComponent(connSel.value))
      .then(function (r) { return r.text(); })
      .then(function (html) {
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html.trim();
        const newSelect = wrapper.firstChild;
        newSelect.id = 'id_table_name_picker';
        newSelect.removeAttribute('name');
        tablePicker.parentNode.replaceChild(newSelect, tablePicker);
        newSelect.addEventListener('change', loadColumns);
      });
  }

  function loadColumns() {
    const picker = document.getElementById('id_table_name_picker');
    tableHidden.value = picker.value;
    if (!connSel.value || !picker.value) return;
    fetch(columnsUrl + '?connection=' + encodeURIComponent(connSel.value) + '&table_name=' + encodeURIComponent(picker.value))
      .then(function (r) { return r.text(); })
      .then(function (html) {
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html.trim();
        const newSelect = wrapper.firstChild;
        newSelect.id = 'id_column_name_picker';
        newSelect.removeAttribute('name');
        columnPicker.parentNode.replaceChild(newSelect, columnPicker);
        newSelect.addEventListener('change', function () {
          columnHidden.value = newSelect.value;
          const opt = newSelect.options[newSelect.selectedIndex];
          const suggested = opt ? opt.dataset.suggested : '';
          if (suggested && providerSel) providerSel.value = suggested;
        });
      });
  }

  connSel.addEventListener('change', loadTables);
})();
```

- [ ] **Step 6: Nav link**

W `services/web/templates/base.html` po linii `<a href="{% url 'db_transfers:list' %}" ...>DB Transfers</a>` dodaj:
```html
    <a href="{% url 'masking:list' %}" class="{% if request.resolver_match.app_name == 'masking' %}active{% endif %}">Masking</a>
```

- [ ] **Step 7: Testy RBAC + formularza**

Dopisz do `services/web/apps/masking/tests/test_views.py`:
```python
@pytest.fixture
def operator_client():
    User.objects.create_user(username='op', password='x', role='operator')
    client = Client()
    client.login(username='op', password='x')
    return client


@pytest.fixture
def admin_client():
    User.objects.create_user(username='adm', password='x', role='admin')
    client = Client()
    client.login(username='adm', password='x')
    return client


class TestMaskingRuleCrudRbac:
    def test_readonly_can_view_list(self, readonly_client):
        response = readonly_client.get('/masking/')
        assert response.status_code == 200

    def test_operator_cannot_create(self, operator_client, pg_connection):
        response = operator_client.post('/masking/new/', {
            'connection': pg_connection.pk, 'table_name': 'users',
            'column_name': 'email', 'faker_provider': 'email',
        })
        assert response.status_code == 403

    def test_admin_can_create_and_it_is_audit_logged(self, admin_client, pg_connection):
        from apps.audit_log.models import ConfigAuditLog
        response = admin_client.post('/masking/new/', {
            'connection': pg_connection.pk, 'table_name': 'users',
            'column_name': 'email', 'faker_provider': 'email',
        })
        assert response.status_code == 302
        assert ConfigAuditLog.objects.filter(model_name='MaskingRule', action='created').exists()
```

`services/web/apps/masking/tests/test_forms.py`:
```python
import pytest
from apps.connections.models import Connection, KIND_POSTGRES, KIND_SSH
from apps.masking.forms import MaskingRuleForm
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


class TestMaskingRuleForm:
    def test_connection_queryset_excludes_ssh_connections(self):
        owner = User.objects.create_user(username='o3', password='x')
        Connection.objects.create(
            owner=owner, name='ssh-host', host='h', port=22, username='u', kind=KIND_SSH,
        )
        pg = Connection.objects.create(
            owner=owner, name='pg', host='h', port=5432, username='u', password='p',
            kind=KIND_POSTGRES, db_name='db',
        )
        form = MaskingRuleForm()
        assert list(form.fields['connection'].queryset) == [pg]
```

Run: `docker compose --profile test build web-test && docker compose --profile test run --rm web-test pytest apps/masking/ -q --no-cov`
Expected: wszystkie testy PASS (modele, widoki RBAC+audit, formularz).

- [ ] **Step 8: Pełny web suite (regresja)**

```bash
docker compose --profile test build web-test
docker compose --profile test run --rm web-test pytest apps/ -q --no-cov
```
Expected: wszystkie testy PASS, bez regresji w innych appkach (nav link w `base.html` mógł zepsuć testy renderujące pełną nawigację — sprawdź, jeśli coś failuje).

- [ ] **Step 9: Commit**

```bash
git add services/web/apps/masking services/web/templates/masking services/web/static/js/masking_form.js \
  services/web/templates/base.html
git commit -m "feat(masking): CRUD reguł maskowania (Admin-only) + audit log + UI"
```

---

### Task 4: Worker — wspólny moduł `masking/faker_engine.py`

**Files:**
- Create: `services/worker/modules/masking/__init__.py`
- Create: `services/worker/modules/masking/faker_engine.py`
- Create: `services/worker/tests/test_faker_engine.py`
- Modify: `services/worker/requirements.txt`

**Interfaces:**
- Produces: `mask_value(provider: str, max_length: int | None = None) -> str`, `PROVIDERS` (dict `{key: callable}`, klucze identyczne z `FAKER_PROVIDER_KEYS` w Task 1).

- [ ] **Step 1: Dodaj Faker do requirements workera**

W `services/worker/requirements.txt` dodaj nową linię (po `pyodbc==5.*`):
```
Faker==26.*
```

- [ ] **Step 2: Napisz moduł**

`services/worker/modules/masking/__init__.py`:
```python
```
(pusty plik)

`services/worker/modules/masking/faker_engine.py`:
```python
from faker import Faker

_fake = Faker()

PROVIDERS = {
    'first_name': _fake.first_name,
    'last_name': _fake.last_name,
    'name': _fake.name,
    'email': _fake.email,
    'phone_number': _fake.phone_number,
    'street_address': _fake.street_address,
    'city': _fake.city,
    'postcode': _fake.postcode,
    'country': _fake.country,
    'company': _fake.company,
    'job_title': _fake.job,
}


def mask_value(provider: str, max_length: int | None = None) -> str:
    generator = PROVIDERS.get(provider)
    if generator is None:
        raise ValueError(f'Unknown masking provider: {provider!r}')
    value = str(generator())
    if max_length is not None and len(value) > max_length:
        value = value[:max_length]
    return value
```

(Uwaga: `_fake.<method>` jest związywane raz przy imporcie modułu — każde wywołanie `generator()` nadal generuje świeżą losową wartość, `Faker` nie cache'uje wyników; to celowo zgodne z decyzją "świeży losowy fake za każdym razem", nie trzeba nic dodatkowo robić dla determinizmu.)

- [ ] **Step 3: Testy**

`services/worker/tests/test_faker_engine.py`:
```python
import pytest
from modules.masking.faker_engine import mask_value, PROVIDERS
from apps.masking.models import FAKER_PROVIDER_KEYS


class TestMaskValue:
    def test_provider_keys_match_django_model_choices(self):
        # Global Constraint: kluczowa spójność między web (Task 1) i worker (ten task)
        assert set(PROVIDERS.keys()) == set(FAKER_PROVIDER_KEYS)

    def test_generates_non_empty_string_for_each_provider(self):
        for provider in PROVIDERS:
            result = mask_value(provider)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_truncates_to_max_length(self):
        result = mask_value('street_address', max_length=5)
        assert len(result) <= 5

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError):
            mask_value('not_a_real_provider')
```

Run: `docker compose build worker-test 2>/dev/null || docker compose --profile test build worker-test; docker compose --profile test run --rm worker-test pytest tests/test_faker_engine.py -q --no-cov`

(Jeśli serwis `worker-test` nie istnieje w `docker-compose.yml`, użyj istniejącej komendy testów workera: `docker compose run --rm worker python -m pytest tests/test_faker_engine.py -q` — sprawdź `docker-compose.yml` i `[[reference-tmask-tt-test-command]]`/istniejący README/CI workflow przed uruchomieniem, żeby użyć dokładnie tej samej komendy co reszta test suite workera.)

Expected: `4 passed`

- [ ] **Step 4: Commit**

```bash
git add services/worker/modules/masking services/worker/tests/test_faker_engine.py services/worker/requirements.txt
git commit -m "feat(masking): wspólny moduł Faker (mask_value + PROVIDERS) w workerze"
```

---

### Task 5: Worker — pobieranie reguł maskowania w `tasks.py`

**Files:**
- Modify: `services/worker/tasks.py`
- Modify: plik testów pokrywający `_build_db_transfer_params`/`execute_db_transfer` w `services/worker/tests/` (sprawdź `grep -rl "_build_db_transfer_params" services/worker/tests/` dla dokładnej nazwy).

**Interfaces:**
- Consumes: `apps.masking.models.MaskingRule` (Task 1).
- Produces: `_masking_rules_for(source_connection) -> dict` zwracający **wszystkie** aktywne reguły dla połączenia, zgrupowane `{table_name: {column_name: provider}}` — nie filtrowane po tabeli, bo dla scope CAŁA BAZA nie znamy z góry, które tabele napotka handler. Klucz `masking_rules` dodany do słownika zwracanego przez `_build_db_transfer_params(job)`, konsumowany przez handlery w Task 6/7/8.

**Ważna decyzja projektowa (poprawiona przy self-review planu)**: pierwotny pomysł "filtruj po `table_names` z joba, a dla scope CAŁA BAZA dociągaj per-tabela leniwie w trakcie streamingu" był błędny — `MysqlTransferHandler` musi wiedzieć, czy dołączyć `--skip-extended-insert`/`--complete-insert` do `mysqldump` **zanim dump w ogóle wystartuje**, a nie leniwie w trakcie przetwarzania wierszy. Rozwiązanie: pobierz od razu WSZYSTKIE reguły dla `source_connection` (jedno tanie zapytanie, `MaskingRule` to mała tabela), niezależnie od scope. Handler i tak używa tylko tych kluczy tabel, które faktycznie napotka.

- [ ] **Step 1: Import modelu**

W `services/worker/tasks.py`, obok istniejącego `from apps.db_transfers.models import DbTransferJob, DbTransferLog  # noqa: E402` dodaj:
```python
from apps.masking.models import MaskingRule  # noqa: E402
```

- [ ] **Step 2: Funkcja pobierająca reguły + wpięcie w params**

W `services/worker/tasks.py`, przed `def _build_db_transfer_params(job) -> dict:` dodaj:
```python
def _masking_rules_for(source_connection) -> dict:
    rules = MaskingRule.objects.filter(connection=source_connection).values(
        'table_name', 'column_name', 'faker_provider',
    )
    result = {}
    for r in rules:
        result.setdefault(r['table_name'], {})[r['column_name']] = r['faker_provider']
    return result
```

Zmodyfikuj `_build_db_transfer_params`:
```python
def _build_db_transfer_params(job) -> dict:
    return {
        'source_host': job.source_connection.host,
        'source_port': job.source_connection.port,
        'source_username': job.source_connection.username,
        'source_password': job.source_connection.password,
        'source_db_name': job.source_connection.db_name,
        'dest_host': job.dest_connection.host,
        'dest_port': job.dest_connection.port,
        'dest_username': job.dest_connection.username,
        'dest_password': job.dest_connection.password,
        'dest_db_name': job.dest_connection.db_name,
        'table_name': job.table_name or None,
        'verify_row_count': job.verify_row_count,
        'masking_rules': _masking_rules_for(job.source_connection),
    }
```

**Dla Task 6/7/8**: `masking_rules` jest teraz zawsze kompletne dla całego połączenia. Handler po prostu robi `self.params.get('masking_rules', {}).get(table_name, {})` — bez żadnego dodatkowego zapytania ORM z poziomu `modules/*` (usuwa to potrzebę `source_connection_id` w params i jakiegokolwiek `rules_for_table()` w `faker_engine.py` — nie dodawaj takiej funkcji).

- [ ] **Step 3: Testy**

**Ważne — poprawione po odkryciu podczas Task 4**: `services/worker/tests/conftest.py` konfiguruje Django z `DATABASES={}` (celowo pusty — worker's testy to w 100% testy jednostkowe na mockach, `docker compose run --rm worker python -m pytest tests/` NIGDY nie łączy się z prawdziwą bazą; sprawdź `grep -rn django_db services/worker/tests/*.py` — zero wystąpień w całym istniejącym suite). `@pytest.mark.django_db` + `Model.objects.create(...)` na prawdziwych obiektach (jak w oryginalnej wersji tego kroku) **nie zadziała** w tym środowisku. Zamiast tego mockuj `MaskingRule` dokładnie tym samym wzorcem co reszta `services/worker/tests/test_tasks.py` (`patch('tasks.NazwaModelu')` + `MagicMock()`, zobacz `TestExecuteTransferTask.test_dispatches_to_sftp_module` w tym samym pliku dla wzorca).

Znajdź istniejący plik testów pokrywający `_build_db_transfer_params`/`execute_db_transfer` w `services/worker/tests/` (prawdopodobnie `test_tasks.py`) i dopisz:
```python
from unittest.mock import patch, MagicMock
from tasks import _masking_rules_for


class TestMaskingRulesFor:
    @patch('tasks.MaskingRule')
    def test_returns_empty_dict_when_no_rules(self, MockMaskingRule):
        MockMaskingRule.objects.filter.return_value.values.return_value = []
        mock_connection = MagicMock()
        assert _masking_rules_for(mock_connection) == {}
        MockMaskingRule.objects.filter.assert_called_once_with(connection=mock_connection)

    @patch('tasks.MaskingRule')
    def test_groups_rules_by_table_and_column_across_whole_connection(self, MockMaskingRule):
        MockMaskingRule.objects.filter.return_value.values.return_value = [
            {'table_name': 'users', 'column_name': 'email', 'faker_provider': 'email'},
            {'table_name': 'clients', 'column_name': 'name', 'faker_provider': 'name'},
        ]
        mock_connection = MagicMock()
        assert _masking_rules_for(mock_connection) == {
            'users': {'email': 'email'}, 'clients': {'name': 'name'},
        }
```

(`@patch('tasks.MaskingRule')` funkcjonuje identycznie do `@patch('tasks.SFTPHandler')` używanego w istniejących testach tego pliku — patchuje symbol zaimportowany do modułu `tasks`, nie oryginalną klasę w `apps.masking.models`.)

Run: `docker compose build worker && docker compose run --rm worker python -m pytest tests/ -q` (pełna komenda workerowego suite — patrz [[reference-tmask-tt-test-command]] w vault dla wariantu z montowaniem źródła przy iteracyjnym TDD).
Expected: nowe testy PASS, brak regresji w pozostałych testach workera.

- [ ] **Step 4: Commit**

```bash
git add services/worker/tasks.py services/worker/tests/
git commit -m "feat(masking): pobieranie kompletnej mapy MaskingRule per połączenie w tasks.py"
```

---

### Task 6: Postgres relay — maskowanie w `PgTransferHandler`

**Files:**
- Modify: `services/worker/modules/postgres/handler.py`
- Modify: `services/worker/tests/test_postgres_handler.py`

**Interfaces:**
- Consumes: `params['masking_rules']` (dict `{table: {col: provider}}`, kompletne dla całego połączenia — Task 5), `modules.masking.faker_engine.mask_value` (Task 4).
- Produces: `PgTransferHandler` zachowuje dotychczasowe publiczne API (`__init__(params)`, `.execute(log_callback)`) bez zmian sygnatury.

- [ ] **Step 1: Test regresyjny — bez reguł, zachowanie identyczne**

Dopisz do `services/worker/tests/test_postgres_handler.py`, w klasie `TestPgTransferHandler`:
```python
    def test_no_masking_rules_leaves_copy_data_untouched(self):
        handler = PgTransferHandler(self._make_params(masking_rules={}))
        dump_lines = [
            'CREATE TABLE users (id int, email text);\n',
            'COPY users (id, email) FROM stdin;\n',
            '1\tjan@firma.pl\n',
            '\\.\n',
        ]
        output = list(handler._relay_lines(iter(dump_lines)))
        assert output == dump_lines
```

(`self._make_params` w tym pliku dziś nie zna klucza `masking_rules` — dodaj `'masking_rules': {}` do jej `defaults` w Step 1, żeby wszystkie ISTNIEJĄCE testy dalej działały bez zmian przy jawnym `**kwargs` override w nowych testach.)

Run: `docker compose run --rm worker python -m pytest tests/test_postgres_handler.py::TestPgTransferHandler::test_no_masking_rules_leaves_copy_data_untouched -v`
Expected: FAIL — `AttributeError: 'PgTransferHandler' object has no attribute '_relay_lines'`

- [ ] **Step 2: Test maskowania — kolumna zamieniona, reszta nietknięta**

Dopisz w tej samej klasie:
```python
    def test_masking_rule_replaces_configured_column_only(self):
        handler = PgTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        dump_lines = [
            'COPY users (id, email) FROM stdin;\n',
            '1\tjan@firma.pl\n',
            '\\.\n',
        ]
        output = list(handler._relay_lines(iter(dump_lines)))
        assert output[0] == 'COPY users (id, email) FROM stdin;\n'
        row = output[1].rstrip('\n').split('\t')
        assert row[0] == '1'
        assert row[1] != 'jan@firma.pl'
        assert output[2] == '\\.\n'

    def test_strips_transaction_timeout_line(self):
        handler = PgTransferHandler(self._make_params(masking_rules={}))
        dump_lines = ['SET transaction_timeout = 0;\n', 'SELECT 1;\n']
        output = list(handler._relay_lines(iter(dump_lines)))
        assert output == ['SELECT 1;\n']

    def test_unmasked_table_in_same_dump_passes_through(self):
        handler = PgTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        dump_lines = [
            'COPY sessions (id, token) FROM stdin;\n',
            '1\tabc123\n',
            '\\.\n',
        ]
        output = list(handler._relay_lines(iter(dump_lines)))
        assert output[1] == '1\tabc123\n'

    def test_whole_db_scope_warns_once_on_table_without_profile(self):
        # table_name=None w params ⇒ scope CAŁA BAZA. Tabela 'sessions' nie ma
        # wpisu w masking_rules (brak profilu) ⇒ oczekujemy WARN w logu.
        handler = PgTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}}, table_name=None,
        ))
        warnings = []
        handler._log_callback = lambda level, msg: warnings.append((level, msg))
        handler._whole_db_scope = True
        dump_lines = ['COPY sessions (id, token) FROM stdin;\n', '1\tabc123\n', '\\.\n']
        list(handler._relay_lines(iter(dump_lines)))
        assert any(level == 'warn' and 'sessions' in msg and 'brak zdefiniowanego profilu' in msg for level, msg in warnings)

    def test_single_table_scope_does_not_warn_for_unmasked_table(self):
        # scope POJEDYNCZA TABELA — brak reguły dla tej tabeli jest świadomym
        # wyborem użytkownika, nie luką pokrycia jak w scope CAŁA BAZA. Zero WARN.
        handler = PgTransferHandler(self._make_params(masking_rules={}, table_name='sessions'))
        warnings = []
        handler._log_callback = lambda level, msg: warnings.append((level, msg))
        handler._whole_db_scope = False
        dump_lines = ['COPY sessions (id, token) FROM stdin;\n', '1\tabc123\n', '\\.\n']
        list(handler._relay_lines(iter(dump_lines)))
        assert warnings == []
```

- [ ] **Step 3: Implementacja `_relay_lines`, wpięcie w `_run_pipe`**

W `services/worker/modules/postgres/handler.py` dodaj import na górze:
```python
import re
from modules.masking.faker_engine import mask_value
```

**Dodaj do `__init__`** (zaraz po `self.params = params`):
```python
        self._log_callback = None
        self._whole_db_scope = not self.params.get('table_name')
```

Dodaj nową metodę `_relay_lines` w klasie `PgTransferHandler`, tuż przed `_run_pipe`:
```python
    _COPY_HEADER_RE = re.compile(r'^COPY (\S+) \(([^)]*)\) FROM stdin;\n?$')

    def _relay_lines(self, lines):
        current_table = None
        current_columns = []
        current_rules = {}
        warned_tables = set()
        for line in lines:
            if line.startswith('SET transaction_timeout'):
                continue
            header = self._COPY_HEADER_RE.match(line)
            if header:
                # pg_dump always schema-qualifies COPY headers (e.g. "public.users",
                # never bare "users"), but masking_rules is keyed by the bare table
                # name (populated from pg_tables.tablename via pg_utils.list_tables,
                # which already filters schemaname='public' — this app never deals
                # with non-public schemas). Strip the schema qualifier and any
                # double-quoting before using it as a dict key, otherwise the
                # lookup always misses and masking silently never fires.
                current_table = header.group(1)
                if '.' in current_table:
                    current_table = current_table.split('.', 1)[1]
                current_table = current_table.strip('"')
                current_columns = [c.strip() for c in header.group(2).split(',')]
                current_rules = self.params.get('masking_rules', {}).get(current_table, {})
                if not current_rules and self._whole_db_scope and current_table not in warned_tables and self._log_callback:
                    self._log_callback('warn', f'Tabela "{current_table}" przesłana BEZ maskowania — brak zdefiniowanego profilu')
                    warned_tables.add(current_table)
                yield line
                continue
            if current_table and line != '\\.\n' and current_rules:
                values = line.rstrip('\n').split('\t')
                for i, col in enumerate(current_columns):
                    if col in current_rules and i < len(values):
                        values[i] = mask_value(current_rules[col])
                yield '\t'.join(values) + '\n'
                continue
            if line == '\\.\n':
                current_table = None
                current_columns = []
                current_rules = {}
            yield line
```

W metodzie `execute()` (bez zmiany sygnatury) dodaj jako pierwszą linię ciała `self._log_callback = log_callback` — testy z Step 1-2 (które nie wołają `execute()`) mają `self._log_callback = None` z `__init__` i nie crashują na warunku `if ... and self._log_callback:`.

Zmodyfikuj `_run_pipe` — usuń `sed` z pipeline'u, wstaw relay jako most między `dump_proc` a `psql_proc`:
```python
    def _run_pipe(self, log_callback: Callable[[str, str], None]) -> tuple:
        dump_cmd = self._build_pg_dump_cmd()
        psql_cmd = self._build_psql_cmd()
        dump_env = {**os.environ, 'PGPASSWORD': self.params['source_password']}
        psql_env = {**os.environ, 'PGPASSWORD': self.params['dest_password']}

        dump_proc = subprocess.Popen(  # nosec B603 — cmd built from validated connection params, no shell=True
            dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dump_env,
        )
        psql_proc = subprocess.Popen(  # nosec B603
            psql_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=psql_env,
        )

        output_lines = []
        output_lock = threading.Lock()

        def _drain(stream):
            for line in stream:
                line = line.rstrip()
                if line:
                    with output_lock:
                        output_lines.append(line)
                    log_callback('info', line)

        def _relay():
            for line in self._relay_lines(dump_proc.stdout):
                psql_proc.stdin.write(line)
            psql_proc.stdin.close()

        psql_thread = threading.Thread(target=_drain, args=(psql_proc.stderr,))
        dump_thread = threading.Thread(target=_drain, args=(dump_proc.stderr,))
        relay_thread = threading.Thread(target=_relay)
        psql_thread.start()
        dump_thread.start()
        relay_thread.start()
        psql_thread.join()
        dump_thread.join()
        relay_thread.join()

        psql_exit = psql_proc.wait()
        dump_exit = dump_proc.wait()
        return dump_exit, psql_exit, '\n'.join(output_lines)
```

Usuń teraz nieużywany import `SED_STRIP_INCOMPATIBLE_SET` z `.config` w nagłówku pliku (zostaje `PG_DUMP_BASE_FLAGS`, `PG_DUMP_MAX_RETRIES`, `PG_DUMP_RETRY_DELAY`) — funkcjonalność tej stałej żyje teraz jako `line.startswith('SET transaction_timeout')` w `_relay_lines`. **Nie usuwaj** `SED_STRIP_INCOMPATIBLE_SET` z `services/worker/modules/postgres/config.py` — zostaw ją tam jako martwy, udokumentowany artefakt HISTORII (albo usuń i z configu — decyzja implementera, ale usunięcie samej stałej wymaga też usunięcia jej z importu w handlerze, sprawdź `grep -rn SED_STRIP_INCOMPATIBLE_SET services/worker/` przed usunięciem, żeby niczego nie zostawić martwego).

- [ ] **Step 4: Uruchom testy**

```bash
docker compose build worker
docker compose run --rm worker python -m pytest tests/test_postgres_handler.py -q
```
Expected: wszystkie testy PASS (stare + 4 nowe z Step 1-2), zero regresji.

- [ ] **Step 5: Pełny worker suite**

```bash
docker compose run --rm worker python -m pytest tests/ -q
```
Expected: wszystkie testy PASS.

- [ ] **Step 6: Commit**

```bash
git add services/worker/modules/postgres/handler.py services/worker/tests/test_postgres_handler.py
git commit -m "feat(masking): Python relay maskujący COPY stream w PgTransferHandler"
```

---

### Task 7: MySQL relay — maskowanie w `MysqlTransferHandler`

**Files:**
- Modify: `services/worker/modules/mysql/handler.py`
- Modify: `services/worker/tests/test_mysql_handler.py` (znajdź dokładną nazwę: `grep -rl MysqlTransferHandler services/worker/tests/`)

**Interfaces:**
- Consumes: `params['masking_rules']` (Task 5, kompletne dla całego połączenia), `modules.masking.faker_engine.mask_value` (Task 4).
- Produces: `MysqlTransferHandler` zachowuje publiczne API bez zmian sygnatury.

**Uwaga dot. `SED_STRIP_MYSQL80_COLLATION`**: w przeciwieństwie do Postgresowego `SET transaction_timeout` (Task 6 — cała linia do pominięcia), ta stała to sed *substytucja wewnątrz linii* (`s/ COLLATE utf8mb4_0900_ai_ci//g`, patrz `services/worker/modules/mysql/config.py`) — może wystąpić w środku linii `CREATE TABLE`, nie jako samodzielna linia. Python-owy odpowiednik to `line.replace(' COLLATE utf8mb4_0900_ai_ci', '')` zaaplikowany do KAŻDEJ linii (nie warunkowy `continue`), nie tylko do linii zaczynających się od konkretnego prefiksu.

- [ ] **Step 1: Test regresyjny — bez reguł, brak nowych flag mysqldump**

Dopisz do pliku testów handlera MySQL, w klasie testowej dla `_build_mysqldump_cmd`:
```python
    def test_no_masking_rules_omits_complete_insert_flags(self):
        handler = MysqlTransferHandler(self._make_params(masking_rules={}))
        cmd = handler._build_mysqldump_cmd()
        assert '--skip-extended-insert' not in cmd
        assert '--complete-insert' not in cmd

    def test_active_masking_rule_adds_complete_insert_flags(self):
        handler = MysqlTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        cmd = handler._build_mysqldump_cmd()
        assert '--skip-extended-insert' in cmd
        assert '--complete-insert' in cmd
```

(Dodaj `'masking_rules': {}` do `defaults` w `self._make_params` tego pliku testowego, tym samym wzorcem co Task 6 Step 1 — tak, żeby wszystkie istniejące testy dalej działały bez zmian.)

- [ ] **Step 2: Test maskowania linii INSERT + collation strip + warn**

Dopisz:
```python
    def test_masking_rule_replaces_configured_column_in_insert(self):
        handler = MysqlTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        lines = ["INSERT INTO `users` (`id`, `email`) VALUES (1,'jan@firma.pl');\n"]
        output = list(handler._relay_lines(iter(lines), strip_collation=False))
        assert output[0].startswith("INSERT INTO `users` (`id`, `email`) VALUES (1,'")
        assert 'jan@firma.pl' not in output[0]

    def test_unrelated_line_passes_through(self):
        handler = MysqlTransferHandler(self._make_params(masking_rules={}))
        lines = ['LOCK TABLES `users` WRITE;\n']
        assert list(handler._relay_lines(iter(lines), strip_collation=False)) == lines

    def test_strip_collation_removes_inline_clause(self):
        handler = MysqlTransferHandler(self._make_params(masking_rules={}))
        lines = ['CREATE TABLE `users` (`email` varchar(255) COLLATE utf8mb4_0900_ai_ci);\n']
        output = list(handler._relay_lines(iter(lines), strip_collation=True))
        assert 'COLLATE utf8mb4_0900_ai_ci' not in output[0]
        assert output[0].startswith('CREATE TABLE `users`')

    def test_whole_db_scope_warns_once_per_table_not_per_row(self):
        handler = MysqlTransferHandler(self._make_params(masking_rules={}, table_name=None))
        warnings = []
        handler._log_callback = lambda level, msg: warnings.append((level, msg))
        handler._whole_db_scope = True
        lines = [
            "INSERT INTO `sessions` (`id`, `token`) VALUES (1,'a');\n",
            "INSERT INTO `sessions` (`id`, `token`) VALUES (2,'b');\n",
        ]
        list(handler._relay_lines(iter(lines), strip_collation=False))
        warn_count = sum(1 for level, msg in warnings if level == 'warn' and 'sessions' in msg)
        assert warn_count == 1
```

- [ ] **Step 3: Implementacja**

W `services/worker/modules/mysql/handler.py` dodaj importy:
```python
import re
from modules.masking.faker_engine import mask_value
```

**Dodaj do `__init__`** (zaraz po `self.params = params`):
```python
        self._log_callback = None
        self._whole_db_scope = not self.params.get('table_name')
```

Zmodyfikuj `_build_mysqldump_cmd`:
```python
    def _build_mysqldump_cmd(self) -> list:
        p = self.params
        cmd = ['mysqldump', '-h', p['source_host'], '-P', str(p['source_port']), '-u', p['source_username']]
        cmd += list(MYSQL_DUMP_BASE_FLAGS)
        if p.get('masking_rules'):
            cmd += ['--skip-extended-insert', '--complete-insert']
        cmd.append(p['source_db_name'])
        if p.get('table_name'):
            cmd.append(p['table_name'])
        return cmd
```

Dodaj metodę `_relay_lines` (format `INSERT INTO \`table\` (\`c1\`, \`c2\`) VALUES (v1,v2);` generowany przez `--complete-insert`):
```python
    _INSERT_RE = re.compile(r"^INSERT INTO `([^`]+)` \(([^)]*)\) VALUES \((.*)\);\n?$")

    def _split_values(self, values_str: str) -> list:
        # --complete-insert z mysqldump generuje jeden wiersz per INSERT (bo
        # --skip-extended-insert wymusza brak batchowania) — string wartości
        # to prosta lista rozdzielona przecinkami z opcjonalnym cudzysłowem;
        # tokenizer musi respektować przecinki WEWNĄTRZ cudzysłowu.
        values = []
        current = ''
        in_quotes = False
        i = 0
        while i < len(values_str):
            ch = values_str[i]
            if ch == "'" and (i == 0 or values_str[i - 1] != '\\'):
                in_quotes = not in_quotes
                current += ch
            elif ch == ',' and not in_quotes:
                values.append(current)
                current = ''
            else:
                current += ch
            i += 1
        values.append(current)
        return values

    def _quote_mysql_value(self, value: str) -> str:
        escaped = value.replace('\\', '\\\\').replace("'", "\\'")
        return f"'{escaped}'"

    def _relay_lines(self, lines, strip_collation: bool):
        warned_tables = set()
        for line in lines:
            if strip_collation:
                line = line.replace(' COLLATE utf8mb4_0900_ai_ci', '')
            match = self._INSERT_RE.match(line)
            if not match:
                yield line
                continue
            table, columns_str, values_str = match.groups()
            columns = [c.strip().strip('`') for c in columns_str.split(',')]
            rules = self.params.get('masking_rules', {}).get(table, {})
            if not rules:
                if self._whole_db_scope and table not in warned_tables and self._log_callback:
                    self._log_callback('warn', f'Tabela "{table}" przesłana BEZ maskowania — brak zdefiniowanego profilu')
                    warned_tables.add(table)
                yield line
                continue
            values = self._split_values(values_str)
            for i, col in enumerate(columns):
                if col in rules and i < len(values):
                    values[i] = self._quote_mysql_value(mask_value(rules[col]))
            yield f"INSERT INTO `{table}` ({columns_str}) VALUES ({','.join(values)});\n"
```

Zamień całą metodę `_run_pipe` na:
```python
    def _run_pipe(self, log_callback: Callable[[str, str], None], strip_collation: bool) -> tuple:
        dump_cmd = self._build_mysqldump_cmd()
        mysql_cmd = self._build_mysql_cmd()
        dump_env = {**os.environ, 'MYSQL_PWD': self.params['source_password']}
        mysql_env = {**os.environ, 'MYSQL_PWD': self.params['dest_password']}

        dump_proc = subprocess.Popen(  # nosec B603
            dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dump_env,
        )
        mysql_proc = subprocess.Popen(  # nosec B603
            mysql_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, env=mysql_env,
        )

        output_lines = []
        output_lock = threading.Lock()

        def _drain(stream):
            for line in stream:
                line = line.rstrip()
                if line:
                    with output_lock:
                        output_lines.append(line)
                    log_callback('info', line)

        def _relay():
            # Mirrors PgTransferHandler._run_pipe's guard (Task 6, fixed post-review):
            # if mysql_proc dies early while dump_proc is still writing, closing
            # dump_proc.stdout unblocks it instead of leaving it stuck once its
            # own stdout OS pipe buffer fills.
            try:
                for line in self._relay_lines(dump_proc.stdout, strip_collation):
                    mysql_proc.stdin.write(line)
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    mysql_proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
                dump_proc.stdout.close()

        threads = [
            threading.Thread(target=_drain, args=(mysql_proc.stderr,)),
            threading.Thread(target=_drain, args=(dump_proc.stderr,)),
        ]
        relay_thread = threading.Thread(target=_relay)
        for t in threads:
            t.start()
        relay_thread.start()
        for t in threads:
            t.join()
        relay_thread.join()

        mysql_exit = mysql_proc.wait()
        dump_exit = dump_proc.wait()
        return dump_exit, mysql_exit, '\n'.join(output_lines)
```

To usuwa `sed_proc` całkowicie z pipeline'u OS-owego (dla obu wartości `strip_collation` — collation-strip teraz zawsze idzie przez `_relay_lines`, nigdy przez zewnętrzny `sed`). Sygnatura `_run_pipe` i wywołanie z `execute()` (`self._run_pipe(log_callback, strip_collation)`) zostają bez zmian. W metodzie `execute()` dodaj jako pierwszą linię ciała `self._log_callback = log_callback`, tak samo jak w Task 6.

Usuń teraz nieużywany import `SED_STRIP_MYSQL80_COLLATION` z `.config` w nagłówku pliku (zostaje `MYSQL_DUMP_BASE_FLAGS`, `MYSQL_DUMP_MAX_RETRIES`, `MYSQL_DUMP_RETRY_DELAY`) — jej treść (`' COLLATE utf8mb4_0900_ai_ci'`) żyje teraz jako literał w `_relay_lines`. Zostaw samą stałą w `services/worker/modules/mysql/config.py` nietkniętą (dokumentuje **dlaczego** ten string trzeba usuwać, komentarz nad nią zostaje prawdziwy i przydatny), tylko usuń jej import/użycie w `handler.py`.

- [ ] **Step 4: Uruchom testy**

```bash
docker compose build worker
docker compose run --rm worker python -m pytest tests/test_mysql_handler.py -q
```
(Podmień nazwę pliku na rzeczywistą znalezioną w Step 1.)
Expected: wszystkie PASS, zero regresji.

- [ ] **Step 5: Pełny worker suite + commit**

```bash
docker compose run --rm worker python -m pytest tests/ -q
git add services/worker/modules/mysql/handler.py services/worker/tests/
git commit -m "feat(masking): relay maskujący INSERT-y w MysqlTransferHandler (complete-insert)"
```

---

### Task 8: MSSQL relay — maskowanie w `MssqlTransferHandler`

**Files:**
- Modify: `services/worker/modules/mssql/handler.py`
- Modify: plik testów handlera MSSQL (`grep -rl MssqlTransferHandler services/worker/tests/`)

**Interfaces:**
- Consumes: `params['masking_rules']` (Task 5, kompletne dla całego połączenia), `modules.masking.faker_engine.mask_value` (Task 4), istniejąca `_introspect_table` (zna już kolejność kolumn per tabela — reużyj, nie duplikuj introspekcji).
- Produces: `MssqlTransferHandler` zachowuje publiczne API bez zmian sygnatury.

- [ ] **Step 1: Test regresyjny — tabela bez reguł zostaje przy `-n`**

Dopisz do pliku testów MSSQL:
```python
    def test_table_without_masking_rules_uses_native_bcp_flag(self):
        handler = MssqlTransferHandler(self._make_params(masking_rules={}))
        cmd = handler._build_bcp_out_cmd('users', '/tmp/x.dat')
        assert '-n' in cmd
        assert '-c' not in cmd

    def test_table_with_masking_rule_uses_character_bcp_flag(self):
        # native=False musi być przekazane explicite — _build_bcp_out_cmd nie ma
        # dostępu do "czy ta tabela ma reguły", tę decyzję podejmuje wyłącznie
        # _transfer_once (native = not bool(rules)) i przekazuje ją jawnie.
        handler = MssqlTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        cmd = handler._build_bcp_out_cmd('users', '/tmp/x.dat', native=False)
        assert '-c' in cmd
        assert '-n' not in cmd
```

(Sprawdź `self._make_params` w tym pliku — prawdopodobnie brak takiej metody, MSSQL testy mogą budować `params` dict inline; dodaj `masking_rules` do defaultów tym samym wzorcem co Task 6/7 albo bezpośrednio do dict-literału używanego w istniejących testach tego pliku.)

- [ ] **Step 2: Test maskowania pliku `.dat` + warn dla scope CAŁA BAZA**

```python
    def test_masking_replaces_column_in_character_mode_file(self, tmp_path):
        handler = MssqlTransferHandler(self._make_params(
            masking_rules={'users': {'email': 'email'}},
        ))
        dat_path = tmp_path / 'users.dat'
        dat_path.write_text('1\tjan@firma.pl\n2\tewa@firma.pl\n')
        schema = {'columns': [{'name': 'id'}, {'name': 'email'}], 'primary_key': ['id']}
        handler._mask_dat_file(str(dat_path), 'users', schema)
        lines = dat_path.read_text().splitlines()
        assert lines[0].split('\t')[0] == '1'
        assert 'jan@firma.pl' not in lines[0]
        assert 'ewa@firma.pl' not in lines[1]

    def test_whole_db_scope_warns_for_table_without_profile(self):
        handler = MssqlTransferHandler(self._make_params(masking_rules={}, table_name=None))
        warnings = []
        handler._whole_db_scope = True
        rules = handler._rules_for('sessions', log_callback=lambda level, msg: warnings.append((level, msg)))
        assert rules == {}
        assert any(level == 'warn' and 'sessions' in msg for level, msg in warnings)

    def test_single_table_scope_does_not_warn(self):
        handler = MssqlTransferHandler(self._make_params(masking_rules={}, table_name='sessions'))
        warnings = []
        handler._whole_db_scope = False
        handler._rules_for('sessions', log_callback=lambda level, msg: warnings.append((level, msg)))
        assert warnings == []
```

- [ ] **Step 3: Implementacja**

W `services/worker/modules/mssql/handler.py` dodaj import:
```python
from modules.masking.faker_engine import mask_value
```

**Dodaj do `__init__`** (zaraz po `self.params = params`):
```python
        self._whole_db_scope = not self.params.get('table_name')
```

Zmodyfikuj `_build_bcp_out_cmd` i `_build_bcp_in_cmd`, żeby przyjmowały tryb (domyślnie natywny, jak dziś):
```python
    def _build_bcp_out_cmd(self, table_name: str, out_path: str, native: bool = True) -> list:
        p = self.params
        mode_flag = '-n' if native else '-c'
        return [
            'bcp', table_name, 'out', out_path, '-S', f'{p["source_host"]},{p["source_port"]}',
            '-U', p['source_username'], '-P', p['source_password'], '-d', p['source_db_name'], mode_flag,
        ]

    def _build_bcp_in_cmd(self, table_name: str, in_path: str, native: bool = True) -> list:
        p = self.params
        mode_flag = '-n' if native else '-c'
        return [
            'bcp', table_name, 'in', in_path, '-S', f'{p["dest_host"]},{p["dest_port"]}',
            '-U', p['dest_username'], '-P', p['dest_password'], '-d', p['dest_db_name'], mode_flag,
        ]
```

Dodaj metodę `_rules_for` i `_mask_dat_file`:
```python
    def _rules_for(self, table_name: str, log_callback=None) -> dict:
        rules = self.params.get('masking_rules', {}).get(table_name, {})
        if not rules and self._whole_db_scope and log_callback:
            log_callback('warn', f'Tabela "{table_name}" przesłana BEZ maskowania — brak zdefiniowanego profilu')
        return rules

    def _mask_dat_file(self, path: str, table_name: str, schema: dict) -> None:
        rules = self.params.get('masking_rules', {}).get(table_name, {})
        if not rules:
            return
        column_names = [c['name'] for c in schema['columns']]
        with open(path, 'r') as f:
            lines = f.readlines()
        with open(path, 'w') as f:
            for line in lines:
                values = line.rstrip('\n').split('\t')
                for i, col in enumerate(column_names):
                    if col in rules and i < len(values):
                        values[i] = mask_value(rules[col])
                f.write('\t'.join(values) + '\n')
```

Zmodyfikuj `_transfer_once` — dla każdej tabeli sprawdź `self._rules_for(table_name, log_callback)` (WARN emitowany tu, raz per tabela — pętla po tabelach już naturalnie iteruje raz per tabela, więc nie trzeba dodatkowej deduplikacji jak w Task 6/7), wybierz `native = not bool(rules)`, przekaż do `_build_bcp_out_cmd`/`_build_bcp_in_cmd`, i po `bcp out` (przed `bcp in`) wywołaj `_mask_dat_file` gdy `rules` niepuste:
```python
            for table_name in table_names:
                fd, data_path = tempfile.mkstemp(suffix='.dat')
                os.close(fd)
                tmp_paths.append(data_path)
                rules = self._rules_for(table_name, log_callback)
                native = not bool(rules)
                if self._run_step(self._build_bcp_out_cmd(table_name, data_path, native=native), log_callback) != 0:
                    return False
                if rules:
                    schema = self._introspect_table(table_name)
                    self._mask_dat_file(data_path, table_name, schema)
                if self._run_step(self._build_bcp_in_cmd(table_name, data_path, native=native), log_callback) != 0:
                    return False
            return True
```

(`_transfer_once` już dziś przyjmuje `log_callback` jako parametr — sprawdź dokładną sygnaturę w istniejącym kodzie i przekaż go do `_rules_for` tym samym `log_callback`, które trafia do `_run_step`.)

- [ ] **Step 4: Uruchom testy**

```bash
docker compose build worker
docker compose run --rm worker python -m pytest tests/ -k mssql -q
```
Expected: wszystkie PASS, zero regresji.

- [ ] **Step 5: Pełny worker suite + commit**

```bash
docker compose run --rm worker python -m pytest tests/ -q
git add services/worker/modules/mssql/handler.py services/worker/tests/
git commit -m "feat(masking): przełączanie bcp -n/-c per tabela + maskowanie pliku .dat w MssqlTransferHandler"
```

---

### Po ukończeniu wszystkich tasków

- [ ] Pełny web suite: `docker compose --profile test build web-test && docker compose --profile test run --rm web-test pytest apps/ -q --no-cov`
- [ ] Pełny worker suite: `docker compose build worker && docker compose run --rm worker python -m pytest tests/ -q`
- [ ] Manualna weryfikacja end-to-end na testowych bazach (opcjonalnie, poza zakresem automatycznych testów tego planu) — utworzyć `MaskingRule` przez UI, uruchomić realny `DbTransferJob`, potwierdzić że docelowa tabela ma fake dane w maskowanej kolumnie i realne w pozostałych.
