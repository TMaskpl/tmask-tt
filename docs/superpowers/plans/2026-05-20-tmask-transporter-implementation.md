# tmask-transporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zbudować kontenerową aplikację webową Django do bezpiecznego przesyłania plików między systemami Linux, z interfejsem Terminal/CRT, harmonogramem cron i modułami SFTP/rsync.

**Architecture:** Django web + Celery worker + Beat scheduler w osobnych kontenerach Docker. Moduły transferu (SFTP, rsync) izolowane w worker container z własną konfiguracją. PostgreSQL jako persistent store, Redis jako Celery broker.

**Tech Stack:** Python 3.12, Django 5.x, Celery 5.x + django-celery-beat, Paramiko, django-encrypted-model-fields, HTMX, PostgreSQL 16, Redis 7, Nginx, Docker Compose

---

## Mapa plików

```
tmask-transporter/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── nginx/
│   └── nginx.conf
├── postgres/
│   └── init.sql
├── services/
│   ├── web/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── manage.py
│   │   ├── conftest.py
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── celery.py
│   │   │   ├── urls.py
│   │   │   ├── wsgi.py
│   │   │   └── settings/
│   │   │       ├── __init__.py
│   │   │       ├── base.py
│   │   │       ├── development.py
│   │   │       └── production.py
│   │   ├── apps/
│   │   │   ├── accounts/
│   │   │   │   ├── models.py       # User z rolą admin/user
│   │   │   │   ├── views.py        # login, logout, profile
│   │   │   │   ├── urls.py
│   │   │   │   ├── forms.py
│   │   │   │   ├── admin.py
│   │   │   │   ├── middleware.py   # role-based access
│   │   │   │   └── tests/
│   │   │   │       ├── conftest.py
│   │   │   │       ├── test_models.py
│   │   │   │       └── test_views.py
│   │   │   ├── connections/
│   │   │   │   ├── models.py       # Connection z encrypted fields
│   │   │   │   ├── views.py        # CRUD + test_connection
│   │   │   │   ├── urls.py
│   │   │   │   ├── forms.py
│   │   │   │   ├── ssh_tester.py   # test połączenia SSH
│   │   │   │   └── tests/
│   │   │   │       ├── conftest.py
│   │   │   │       ├── test_models.py
│   │   │   │       └── test_views.py
│   │   │   ├── transfers/
│   │   │   │   ├── models.py       # TransferJob, TransferLog
│   │   │   │   ├── views.py        # create, status, log fragment (HTMX)
│   │   │   │   ├── urls.py
│   │   │   │   ├── forms.py
│   │   │   │   └── tests/
│   │   │   │       ├── conftest.py
│   │   │   │       ├── test_models.py
│   │   │   │       └── test_views.py
│   │   │   └── scheduler/
│   │   │       ├── models.py       # ScheduledTransfer
│   │   │       ├── views.py        # CRUD harmonogramu
│   │   │       ├── urls.py
│   │   │       ├── forms.py
│   │   │       └── tests/
│   │   │           ├── conftest.py
│   │   │           └── test_models.py
│   │   ├── templates/
│   │   │   ├── base.html
│   │   │   ├── 500.html
│   │   │   ├── accounts/
│   │   │   │   └── login.html
│   │   │   ├── dashboard/
│   │   │   │   └── index.html
│   │   │   ├── connections/
│   │   │   │   ├── list.html
│   │   │   │   ├── form.html
│   │   │   │   └── browse_fragment.html
│   │   │   ├── transfers/
│   │   │   │   ├── create.html
│   │   │   │   └── log_fragment.html
│   │   │   ├── scheduler/
│   │   │   │   ├── list.html
│   │   │   │   └── form.html
│   │   │   ├── logs/
│   │   │   │   └── list.html
│   │   │   └── users/
│   │   │       └── list.html
│   │   └── static/
│   │       └── css/
│   │           └── crt.css
│   └── worker/
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── tasks.py                # Celery tasks — dispatcher
│       ├── conftest.py
│       ├── modules/
│       │   ├── __init__.py
│       │   ├── sftp/
│       │   │   ├── __init__.py
│       │   │   ├── config.py
│       │   │   └── handler.py
│       │   └── rsync/
│       │       ├── __init__.py
│       │       ├── config.py
│       │       └── handler.py
│       └── tests/
│           ├── test_sftp_handler.py
│           └── test_rsync_handler.py
```

---

## FAZA 1: Infrastruktura

### Task 1: Docker Compose + scaffolding projektu

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `nginx/nginx.conf`
- Create: `postgres/init.sql`
- Create: `services/web/Dockerfile`
- Create: `services/worker/Dockerfile`

- [ ] **Step 1: Utwórz .gitignore**

```gitignore
.env
*.pyc
__pycache__/
*.egg-info/
.pytest_cache/
db.sqlite3
staticfiles/
media/
.DS_Store
```

- [ ] **Step 2: Utwórz .env.example**

```env
# Postgres
POSTGRES_DB=transporter
POSTGRES_USER=transporter
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql://transporter:changeme@postgres:5432/transporter

# Django
SECRET_KEY=change-me-in-production-min-50-chars
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Redis / Celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Szyfrowanie pól DB (Fernet) — generuj: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEY=your-fernet-key-here

# Opcjonalne
SENTRY_DSN=
```

- [ ] **Step 3: Utwórz docker-compose.yml**

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16-alpine
    env_file: .env
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./postgres/init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - internal
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    networks:
      - internal
    restart: unless-stopped

  web:
    build: ./services/web
    env_file: .env
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.production
    volumes:
      - static_files:/app/staticfiles
    depends_on:
      - postgres
      - redis
    networks:
      - internal
    restart: unless-stopped

  worker:
    build: ./services/worker
    env_file: .env
    depends_on:
      - redis
      - postgres
    networks:
      - internal
    restart: unless-stopped

  beat:
    build: ./services/worker
    env_file: .env
    command: celery -A tasks beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    depends_on:
      - redis
      - postgres
    networks:
      - internal
    restart: unless-stopped

  nginx:
    image: nginx:1.25-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf
      - static_files:/app/staticfiles
    depends_on:
      - web
    networks:
      - internal
    restart: unless-stopped

volumes:
  postgres_data:
  static_files:

networks:
  internal:
    driver: bridge
```

- [ ] **Step 4: Utwórz nginx/nginx.conf**

```nginx
upstream django {
    server web:8000;
}

server {
    listen 80;
    server_name _;

    location /static/ {
        alias /app/staticfiles/;
    }

    location / {
        proxy_pass http://django;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

- [ ] **Step 5: Utwórz postgres/init.sql**

```sql
-- Baza tworzona automatycznie przez zmienne POSTGRES_DB
-- Ten plik służy do ewentualnych rozszerzeń
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

- [ ] **Step 6: Utwórz services/web/Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
```

- [ ] **Step 7: Utwórz services/worker/Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    rsync openssh-client libpq-dev gcc gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["celery", "-A", "tasks", "worker", "--loglevel=info", "--concurrency=4"]
```

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml .env.example .gitignore nginx/ postgres/ services/web/Dockerfile services/worker/Dockerfile
git commit -m "feat: add Docker Compose infrastructure scaffold"
```

---

### Task 2: Django project scaffold + settings

**Files:**
- Create: `services/web/requirements.txt`
- Create: `services/web/manage.py`
- Create: `services/web/config/__init__.py`
- Create: `services/web/config/settings/base.py`
- Create: `services/web/config/settings/development.py`
- Create: `services/web/config/settings/production.py`
- Create: `services/web/config/urls.py`
- Create: `services/web/config/wsgi.py`
- Create: `services/web/config/celery.py`
- Create: `services/web/conftest.py`

- [ ] **Step 1: Utwórz services/web/requirements.txt**

```
Django==5.1.*
gunicorn==22.*
psycopg2-binary==2.9.*
redis==5.*
celery==5.4.*
django-celery-beat==2.7.*
django-celery-results==2.5.*
paramiko==3.4.*
python-decouple==3.8
django-encrypted-model-fields==0.6.*
cryptography==42.*
bcrypt==4.*
django-htmx==1.19.*
# Dev/test
pytest==8.*
pytest-django==4.8.*
pytest-mock==3.*
factory-boy==3.*
```

- [ ] **Step 2: Utwórz services/web/config/settings/base.py**

```python
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_celery_beat',
    'django_celery_results',
    'django_htmx',
    'apps.accounts',
    'apps.connections',
    'apps.transfers',
    'apps.scheduler',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('POSTGRES_DB'),
        'USER': config('POSTGRES_USER'),
        'PASSWORD': config('POSTGRES_PASSWORD'),
        'HOST': config('DB_HOST', default='postgres'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

LANGUAGE_CODE = 'pl'
TIME_ZONE = 'Europe/Warsaw'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

CELERY_BROKER_URL = config('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']

FIELD_ENCRYPTION_KEY = config('FIELD_ENCRYPTION_KEY')
```

- [ ] **Step 3: Utwórz services/web/config/settings/development.py**

```python
from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*']

DATABASES['default']['HOST'] = 'localhost'

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
```

- [ ] **Step 4: Utwórz services/web/config/settings/production.py**

```python
from .base import *

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
```

- [ ] **Step 5: Utwórz services/web/config/celery.py**

```python
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')

app = Celery('transporter')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

- [ ] **Step 6: Utwórz services/web/config/urls.py**

```python
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('apps.accounts.urls')),
    path('connections/', include('apps.connections.urls')),
    path('transfers/', include('apps.transfers.urls')),
    path('scheduler/', include('apps.scheduler.urls')),
    path('', RedirectView.as_view(url='/transfers/', permanent=False)),
]
```

- [ ] **Step 7: Utwórz services/web/conftest.py**

```python
import pytest
from django.test import Client

@pytest.fixture
def client():
    return Client()

@pytest.fixture
def admin_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username='admin_test',
        password='testpass123',
        role='admin',
    )

@pytest.fixture
def regular_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username='user_test',
        password='testpass123',
        role='user',
    )

@pytest.fixture
def auth_client(client, regular_user):
    client.login(username='user_test', password='testpass123')
    return client

@pytest.fixture
def admin_client(client, admin_user):
    client.login(username='admin_test', password='testpass123')
    return client
```

- [ ] **Step 8: Utwórz pytest.ini w services/web/**

```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings.development
python_files = tests/test_*.py
python_classes = Test*
python_functions = test_*
```

- [ ] **Step 9: Commit**

```bash
git add services/web/
git commit -m "feat: scaffold Django project with settings, Celery, and test config"
```

---

## FAZA 2: Modele danych

### Task 3: accounts app — User model + auth views

**Files:**
- Create: `services/web/apps/accounts/__init__.py`
- Create: `services/web/apps/accounts/models.py`
- Create: `services/web/apps/accounts/views.py`
- Create: `services/web/apps/accounts/urls.py`
- Create: `services/web/apps/accounts/forms.py`
- Create: `services/web/apps/accounts/admin.py`
- Create: `services/web/apps/accounts/tests/test_models.py`
- Create: `services/web/apps/accounts/tests/test_views.py`

- [ ] **Step 1: Napisz test modelu — weryfikuje role i AUTH_USER_MODEL**

```python
# services/web/apps/accounts/tests/test_models.py
import pytest

@pytest.mark.django_db
class TestUser:
    def test_user_has_role_field(self, django_user_model):
        user = django_user_model.objects.create_user(
            username='tester', password='pass', role='user'
        )
        assert user.role == 'user'

    def test_admin_role(self, django_user_model):
        admin = django_user_model.objects.create_user(
            username='adm', password='pass', role='admin'
        )
        assert admin.is_admin is True

    def test_user_role_is_not_admin(self, django_user_model):
        user = django_user_model.objects.create_user(
            username='usr', password='pass', role='user'
        )
        assert user.is_admin is False
```

- [ ] **Step 2: Uruchom test — powinien FAIL**

```bash
cd services/web && pytest apps/accounts/tests/test_models.py -v
# Expected: ImportError lub AttributeError — User model nie istnieje
```

- [ ] **Step 3: Implementuj apps/accounts/models.py**

```python
from django.contrib.auth.models import AbstractUser
from django.db import models

ROLE_ADMIN = 'admin'
ROLE_USER = 'user'
ROLE_CHOICES = [(ROLE_ADMIN, 'Admin'), (ROLE_USER, 'User')]

class User(AbstractUser):
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_USER)

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    class Meta:
        verbose_name = 'Użytkownik'
        verbose_name_plural = 'Użytkownicy'
```

- [ ] **Step 4: Uruchom test — powinien PASS**

```bash
pytest apps/accounts/tests/test_models.py -v
# Expected: 3 passed
```

- [ ] **Step 5: Napisz test widoków auth**

```python
# services/web/apps/accounts/tests/test_views.py
import pytest
from django.urls import reverse

@pytest.mark.django_db
class TestLoginView:
    def test_login_page_renders(self, client):
        url = reverse('accounts:login')
        response = client.get(url)
        assert response.status_code == 200

    def test_login_with_valid_credentials(self, client, regular_user):
        url = reverse('accounts:login')
        response = client.post(url, {'username': 'user_test', 'password': 'testpass123'})
        assert response.status_code == 302

    def test_login_with_invalid_credentials(self, client):
        url = reverse('accounts:login')
        response = client.post(url, {'username': 'wrong', 'password': 'wrong'})
        assert response.status_code == 200
        assert b'ERROR' in response.content or response.context['form'].errors

    def test_logout_redirects_to_login(self, auth_client):
        url = reverse('accounts:logout')
        response = auth_client.post(url)
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_unauthenticated_redirect_to_login(self, client):
        response = client.get('/')
        assert response.status_code == 302
        assert '/login/' in response['Location']
```

- [ ] **Step 6: Implementuj accounts/views.py i urls.py**

```python
# services/web/apps/accounts/views.py
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from .forms import LoginForm

def login_view(request):
    if request.user.is_authenticated:
        return redirect('transfers:create')
    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data['username'],
            password=form.cleaned_data['password'],
        )
        if user:
            login(request, user)
            return redirect(request.GET.get('next', 'transfers:create'))
        form.add_error(None, 'AUTH FAILED — invalid credentials')
    return render(request, 'accounts/login.html', {'form': form})

@require_POST
def logout_view(request):
    logout(request)
    return redirect('accounts:login')
```

```python
# services/web/apps/accounts/urls.py
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
```

```python
# services/web/apps/accounts/forms.py
from django import forms

class LoginForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)
```

- [ ] **Step 7: Uruchom wszystkie testy accounts**

```bash
pytest apps/accounts/ -v
# Expected: wszystkie passed
```

- [ ] **Step 8: Utwórz migrację i commit**

```bash
python manage.py makemigrations accounts
git add apps/accounts/
git commit -m "feat: add accounts app with User model (role field) and auth views"
```

---

### Task 4: connections app — Connection model + encrypted fields

**Files:**
- Create: `services/web/apps/connections/models.py`
- Create: `services/web/apps/connections/views.py`
- Create: `services/web/apps/connections/urls.py`
- Create: `services/web/apps/connections/forms.py`
- Create: `services/web/apps/connections/ssh_tester.py`
- Create: `services/web/apps/connections/tests/test_models.py`
- Create: `services/web/apps/connections/tests/test_views.py`

- [ ] **Step 1: Napisz test modelu Connection**

```python
# services/web/apps/connections/tests/test_models.py
import pytest
from apps.connections.models import Connection

@pytest.mark.django_db
class TestConnection:
    def test_create_connection_with_password(self, regular_user):
        conn = Connection.objects.create(
            owner=regular_user,
            name='Test Server',
            host='192.168.1.10',
            port=22,
            username='deploy',
            password='secret123',
            protocol='sftp',
        )
        assert conn.pk is not None
        assert conn.password == 'secret123'  # odczyt działa przez Fernet

    def test_password_is_stored_encrypted(self, regular_user):
        conn = Connection.objects.create(
            owner=regular_user, name='S', host='h', port=22,
            username='u', password='mypassword', protocol='sftp',
        )
        from django.db import connection as db_conn
        with db_conn.cursor() as cursor:
            cursor.execute("SELECT password FROM connections_connection WHERE id=%s", [conn.pk])
            raw = cursor.fetchone()[0]
        assert raw != 'mypassword'  # w DB jest zaszyfrowane

    def test_connection_owner_isolation(self, regular_user, admin_user):
        Connection.objects.create(
            owner=admin_user, name='Admin conn', host='h', port=22,
            username='u', protocol='sftp',
        )
        user_connections = Connection.objects.filter(owner=regular_user)
        assert user_connections.count() == 0

    def test_str_representation(self, regular_user):
        conn = Connection(owner=regular_user, name='Prod', host='1.2.3.4', protocol='sftp')
        assert 'Prod' in str(conn)
```

- [ ] **Step 2: Uruchom test — FAIL**

```bash
pytest apps/connections/tests/test_models.py -v
# Expected: ImportError
```

- [ ] **Step 3: Implementuj apps/connections/models.py**

```python
from django.db import models
from encrypted_model_fields.fields import EncryptedCharField, EncryptedTextField
from apps.accounts.models import User

PROTOCOL_SFTP = 'sftp'
PROTOCOL_RSYNC = 'rsync'
PROTOCOL_CHOICES = [(PROTOCOL_SFTP, 'SFTP/SCP'), (PROTOCOL_RSYNC, 'rsync')]

class Connection(models.Model):
    owner    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='connections')
    name     = models.CharField(max_length=100)
    host     = models.CharField(max_length=255)
    port     = models.IntegerField(default=22)
    username = models.CharField(max_length=100)
    password = EncryptedCharField(max_length=500, null=True, blank=True)
    ssh_key  = EncryptedTextField(null=True, blank=True)
    protocol = models.CharField(max_length=10, choices=PROTOCOL_CHOICES, default=PROTOCOL_SFTP)
    compress = models.BooleanField(default=False)
    encrypt  = models.BooleanField(default=False)
    strict_host_key_checking = models.BooleanField(default=True)
    known_host_key = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.host}:{self.port})'

    class Meta:
        ordering = ['-created_at']
```

- [ ] **Step 4: Uruchom test — PASS**

```bash
pytest apps/connections/tests/test_models.py -v
# Expected: 4 passed
```

- [ ] **Step 5: Implementuj ssh_tester.py**

```python
# services/web/apps/connections/ssh_tester.py
import socket
import paramiko

class SSHTestResult:
    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message

def test_connection(connection) -> SSHTestResult:
    client = paramiko.SSHClient()
    if connection.strict_host_key_checking:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
            import io
            pkey = paramiko.RSAKey.from_private_key(io.StringIO(connection.ssh_key))
            connect_kwargs['pkey'] = pkey
        elif connection.password:
            connect_kwargs['password'] = connection.password
        else:
            return SSHTestResult(False, 'AUTH FAILED — no credentials configured')
        client.connect(**connect_kwargs)
        client.close()
        return SSHTestResult(True, f'CONNECTION OK — {connection.host}:{connection.port}')
    except paramiko.AuthenticationException:
        return SSHTestResult(False, 'AUTH FAILED — check credentials')
    except (socket.timeout, socket.gaierror):
        return SSHTestResult(False, f'CONNECTION TIMEOUT — {connection.host} unreachable')
    except paramiko.SSHException as e:
        return SSHTestResult(False, f'SSH ERROR — {e}')
    finally:
        client.close()
```

- [ ] **Step 6: Implementuj connections/views.py**

```python
# services/web/apps/connections/views.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .models import Connection
from .forms import ConnectionForm
from .ssh_tester import test_connection

@login_required
def connection_list(request):
    connections = Connection.objects.filter(owner=request.user)
    return render(request, 'connections/list.html', {'connections': connections})

@login_required
def connection_create(request):
    form = ConnectionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        conn = form.save(commit=False)
        conn.owner = request.user
        conn.save()
        return redirect('connections:list')
    return render(request, 'connections/form.html', {'form': form, 'action': 'CREATE'})

@login_required
def connection_edit(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    form = ConnectionForm(request.POST or None, instance=conn)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('connections:list')
    return render(request, 'connections/form.html', {'form': form, 'action': 'EDIT', 'conn': conn})

@login_required
@require_POST
def connection_delete(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    conn.delete()
    return redirect('connections:list')

@login_required
def connection_test(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    result = test_connection(conn)
    return JsonResponse({'success': result.success, 'message': result.message})
```

- [ ] **Step 7: Utwórz connections/urls.py i forms.py**

```python
# services/web/apps/connections/urls.py
from django.urls import path
from . import views

app_name = 'connections'

urlpatterns = [
    path('', views.connection_list, name='list'),
    path('new/', views.connection_create, name='create'),
    path('<int:pk>/edit/', views.connection_edit, name='edit'),
    path('<int:pk>/delete/', views.connection_delete, name='delete'),
    path('<int:pk>/test/', views.connection_test, name='test'),
]
```

```python
# services/web/apps/connections/forms.py
from django import forms
from .models import Connection

class ConnectionForm(forms.ModelForm):
    class Meta:
        model = Connection
        fields = ['name', 'host', 'port', 'username', 'password', 'ssh_key',
                  'protocol', 'compress', 'encrypt', 'strict_host_key_checking']
        widgets = {
            'password': forms.PasswordInput(render_value=True),
            'ssh_key': forms.Textarea(attrs={'rows': 6}),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('password') and not cleaned.get('ssh_key'):
            raise forms.ValidationError('AUTH ERROR — provide password or SSH key')
        return cleaned
```

- [ ] **Step 8: Uruchom testy + migracja + commit**

```bash
python manage.py makemigrations connections
pytest apps/connections/ -v
git add apps/connections/
git commit -m "feat: add connections app with encrypted SSH credentials"
```

---

### Task 5: transfers app — TransferJob + TransferLog models

**Files:**
- Create: `services/web/apps/transfers/models.py`
- Create: `services/web/apps/transfers/views.py`
- Create: `services/web/apps/transfers/urls.py`
- Create: `services/web/apps/transfers/forms.py`
- Create: `services/web/apps/transfers/tests/test_models.py`

- [ ] **Step 1: Napisz test modelu**

```python
# services/web/apps/transfers/tests/test_models.py
import pytest
from apps.transfers.models import TransferJob, TransferLog, STATUS_PENDING, STATUS_FAILED

@pytest.mark.django_db
class TestTransferJob:
    def test_create_job(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/data/file.tar',
            destination_path='/backup/',
        )
        assert job.status == STATUS_PENDING
        assert job.started_at is None

    def test_job_owner_isolation(self, regular_user, admin_user, make_connection):
        TransferJob.objects.create(
            owner=admin_user,
            connection=make_connection(admin_user),
            source_path='/x', destination_path='/y',
        )
        assert TransferJob.objects.filter(owner=regular_user).count() == 0

@pytest.mark.django_db
class TestTransferLog:
    def test_log_appended_to_job(self, regular_user, make_connection):
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        TransferLog.objects.create(job=job, level='info', message='Transfer started')
        assert job.logs.count() == 1
```

- [ ] **Step 2: Dodaj fixture make_connection do conftest.py**

```python
# services/web/conftest.py (dodaj do istniejącego)
import pytest
from apps.connections.models import Connection

@pytest.fixture
def make_connection():
    def _make(user, **kwargs):
        defaults = dict(name='Test', host='localhost', port=22,
                        username='u', password='p', protocol='sftp')
        defaults.update(kwargs)
        return Connection.objects.create(owner=user, **defaults)
    return _make
```

- [ ] **Step 3: Implementuj transfers/models.py**

```python
from django.db import models
from django.utils import timezone
from apps.accounts.models import User
from apps.connections.models import Connection

STATUS_PENDING = 'pending'
STATUS_RUNNING = 'running'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'
STATUS_CHOICES = [
    (STATUS_PENDING, 'PENDING'),
    (STATUS_RUNNING, 'RUNNING'),
    (STATUS_DONE, 'DONE'),
    (STATUS_FAILED, 'FAILED'),
]

class TransferJob(models.Model):
    owner            = models.ForeignKey(User, on_delete=models.CASCADE, related_name='jobs')
    connection       = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='jobs')
    source_path      = models.CharField(max_length=2000)
    destination_path = models.CharField(max_length=2000)
    status           = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    celery_task_id   = models.CharField(max_length=255, null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    started_at       = models.DateTimeField(null=True, blank=True)
    finished_at      = models.DateTimeField(null=True, blank=True)
    error_message    = models.TextField(null=True, blank=True)

    def mark_running(self, task_id: str):
        self.status = STATUS_RUNNING
        self.celery_task_id = task_id
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'celery_task_id', 'started_at'])

    def mark_done(self):
        self.status = STATUS_DONE
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'finished_at'])

    def mark_failed(self, message: str):
        self.status = STATUS_FAILED
        self.error_message = message
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'error_message', 'finished_at'])

    class Meta:
        ordering = ['-created_at']

class TransferLog(models.Model):
    job       = models.ForeignKey(TransferJob, on_delete=models.CASCADE, related_name='logs')
    timestamp = models.DateTimeField(auto_now_add=True)
    level     = models.CharField(max_length=5, choices=[('info','INFO'),('warn','WARN'),('error','ERROR')])
    message   = models.TextField()

    class Meta:
        ordering = ['timestamp']
```

- [ ] **Step 4: Uruchom testy + migracja + commit**

```bash
python manage.py makemigrations transfers
pytest apps/transfers/tests/test_models.py -v
git add apps/transfers/
git commit -m "feat: add transfers app with TransferJob and TransferLog models"
```

---

### Task 6: scheduler app — ScheduledTransfer model

**Files:**
- Create: `services/web/apps/scheduler/models.py`
- Create: `services/web/apps/scheduler/views.py`
- Create: `services/web/apps/scheduler/urls.py`
- Create: `services/web/apps/scheduler/forms.py`
- Create: `services/web/apps/scheduler/tests/test_models.py`

- [ ] **Step 1: Napisz test modelu**

```python
# services/web/apps/scheduler/tests/test_models.py
import pytest
from apps.scheduler.models import ScheduledTransfer

@pytest.mark.django_db
class TestScheduledTransfer:
    def test_create_scheduled_transfer(self, regular_user, make_connection):
        sched = ScheduledTransfer.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/data/',
            destination_path='/backup/',
            cron_expr='0 2 * * *',
        )
        assert sched.enabled is True
        assert sched.last_run is None

    def test_default_enabled_true(self, regular_user, make_connection):
        sched = ScheduledTransfer(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
            cron_expr='*/5 * * * *',
        )
        assert sched.enabled is True
```

- [ ] **Step 2: Implementuj scheduler/models.py**

```python
from django.db import models
from apps.accounts.models import User
from apps.connections.models import Connection

class ScheduledTransfer(models.Model):
    owner            = models.ForeignKey(User, on_delete=models.CASCADE, related_name='schedules')
    connection       = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name='schedules')
    source_path      = models.CharField(max_length=2000)
    destination_path = models.CharField(max_length=2000)
    cron_expr        = models.CharField(max_length=100)
    enabled          = models.BooleanField(default=True)
    last_run         = models.DateTimeField(null=True, blank=True)
    next_run         = models.DateTimeField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.connection.name}: {self.cron_expr}'

    class Meta:
        ordering = ['-created_at']
```

- [ ] **Step 3: Uruchom testy + migracja + commit**

```bash
python manage.py makemigrations scheduler
pytest apps/scheduler/ -v
git add apps/scheduler/
git commit -m "feat: add scheduler app with ScheduledTransfer model"
```

---

## FAZA 3: Transfer Engine (Worker)

### Task 7: Worker — SFTP module

**Files:**
- Create: `services/worker/requirements.txt`
- Create: `services/worker/modules/__init__.py`
- Create: `services/worker/modules/sftp/__init__.py`
- Create: `services/worker/modules/sftp/config.py`
- Create: `services/worker/modules/sftp/handler.py`
- Create: `services/worker/tests/test_sftp_handler.py`
- Create: `services/worker/conftest.py`

- [ ] **Step 1: Utwórz services/worker/requirements.txt**

```
celery==5.4.*
redis==5.*
paramiko==3.4.*
psycopg2-binary==2.9.*
django==5.1.*
django-celery-beat==2.7.*
django-celery-results==2.5.*
python-decouple==3.8
django-encrypted-model-fields==0.6.*
cryptography==42.*
pytest==8.*
pytest-mock==3.*
```

- [ ] **Step 2: Utwórz services/worker/modules/sftp/config.py**

```python
SFTP_TIMEOUT = 30
SFTP_MAX_RETRIES = 3
SFTP_RETRY_DELAY = 5
SFTP_BANNER_TIMEOUT = 15
```

- [ ] **Step 3: Napisz test SFTP handlera**

```python
# services/worker/tests/test_sftp_handler.py
import pytest
from unittest.mock import MagicMock, patch
from modules.sftp.handler import SFTPHandler, SFTPTransferError

class TestSFTPHandler:
    def _make_params(self, **kwargs):
        defaults = {
            'host': '192.168.1.10', 'port': 22, 'username': 'deploy',
            'password': 'secret', 'ssh_key': None,
            'source_path': '/data/file.tar', 'destination_path': '/backup/',
            'compress': False, 'encrypt': False,
            'strict_host_key_checking': False, 'known_host_key': None,
        }
        defaults.update(kwargs)
        return defaults

    def test_auth_failure_raises_error(self):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            import paramiko
            mock_client.connect.side_effect = paramiko.AuthenticationException()
            handler = SFTPHandler(self._make_params())
            with pytest.raises(SFTPTransferError, match='AUTH FAILED'):
                handler.execute(log_callback=lambda lvl, msg: None)

    def test_successful_transfer_calls_put(self):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            handler = SFTPHandler(self._make_params())
            logs = []
            handler.execute(log_callback=lambda lvl, msg: logs.append((lvl, msg)))
            mock_sftp.put.assert_called_once()

    def test_source_not_found_raises_error(self):
        with patch('modules.sftp.handler.paramiko.SSHClient') as MockSSH:
            mock_client = MagicMock()
            MockSSH.return_value = mock_client
            mock_sftp = MagicMock()
            mock_sftp.put.side_effect = FileNotFoundError('/data/file.tar')
            mock_client.open_sftp.return_value.__enter__ = MagicMock(return_value=mock_sftp)
            mock_client.open_sftp.return_value.__exit__ = MagicMock(return_value=False)
            handler = SFTPHandler(self._make_params())
            with pytest.raises(SFTPTransferError, match='SOURCE NOT FOUND'):
                handler.execute(log_callback=lambda lvl, msg: None)
```

- [ ] **Step 4: Uruchom test — FAIL**

```bash
cd services/worker && pytest tests/test_sftp_handler.py -v
# Expected: ImportError
```

- [ ] **Step 5: Implementuj modules/sftp/handler.py**

```python
import io
import socket
import paramiko
from .config import SFTP_TIMEOUT, SFTP_MAX_RETRIES, SFTP_RETRY_DELAY
import time

class SFTPTransferError(Exception):
    pass

class SFTPHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_client(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        if self.params['strict_host_key_checking'] and self.params['known_host_key']:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return client

    def _connect(self, client: paramiko.SSHClient):
        kwargs = {
            'hostname': self.params['host'],
            'port': self.params['port'],
            'username': self.params['username'],
            'timeout': SFTP_TIMEOUT,
            'look_for_keys': False,
            'allow_agent': False,
        }
        if self.params.get('ssh_key'):
            kwargs['pkey'] = paramiko.RSAKey.from_private_key(io.StringIO(self.params['ssh_key']))
        elif self.params.get('password'):
            kwargs['password'] = self.params['password']
        client.connect(**kwargs)

    def execute(self, log_callback):
        client = self._build_client()
        last_error = None
        for attempt in range(1, SFTP_MAX_RETRIES + 1):
            try:
                log_callback('info', f'Connecting to {self.params["host"]}:{self.params["port"]} (attempt {attempt})')
                self._connect(client)
                log_callback('info', 'Authentication OK')
                break
            except paramiko.AuthenticationException:
                raise SFTPTransferError('AUTH FAILED — check credentials')
            except (socket.timeout, socket.gaierror) as e:
                last_error = str(e)
                if attempt < SFTP_MAX_RETRIES:
                    log_callback('warn', f'Connection failed, retrying in {SFTP_RETRY_DELAY}s...')
                    time.sleep(SFTP_RETRY_DELAY)
            except paramiko.SSHException as e:
                raise SFTPTransferError(f'SSH ERROR — {e}')
        else:
            raise SFTPTransferError(f'CONNECTION TIMEOUT — {self.params["host"]} unreachable')

        try:
            log_callback('info', f'Transferring: {self.params["source_path"]}')
            with client.open_sftp() as sftp:
                sftp.put(
                    self.params['source_path'],
                    self.params['destination_path'],
                    callback=lambda done, total: log_callback('info', f'Progress: {int(done/total*100)}%') if total else None,
                )
            log_callback('info', 'Transfer complete')
        except FileNotFoundError as e:
            raise SFTPTransferError(f'SOURCE NOT FOUND: {self.params["source_path"]}')
        except OSError as e:
            if 'No space' in str(e):
                raise SFTPTransferError('INSUFFICIENT SPACE ON DESTINATION')
            raise SFTPTransferError(f'TRANSFER ERROR — {e}')
        finally:
            client.close()
```

- [ ] **Step 6: Uruchom test — PASS**

```bash
pytest tests/test_sftp_handler.py -v
# Expected: 3 passed
```

- [ ] **Step 7: Commit**

```bash
cd services/worker && git add modules/sftp/ tests/test_sftp_handler.py requirements.txt
git commit -m "feat: add SFTP transfer module with retry and error handling"
```

---

### Task 8: Worker — rsync module

**Files:**
- Create: `services/worker/modules/rsync/__init__.py`
- Create: `services/worker/modules/rsync/config.py`
- Create: `services/worker/modules/rsync/handler.py`
- Create: `services/worker/tests/test_rsync_handler.py`

- [ ] **Step 1: Utwórz modules/rsync/config.py**

```python
RSYNC_BASE_FLAGS = ['-av', '--progress']
RSYNC_COMPRESS_FLAG = '--compress'
RSYNC_TIMEOUT = 60
RSYNC_MAX_RETRIES = 3
RSYNC_RETRY_DELAY = 5
```

- [ ] **Step 2: Napisz test rsync handlera**

```python
# services/worker/tests/test_rsync_handler.py
import pytest
from unittest.mock import patch, MagicMock
from modules.rsync.handler import RsyncHandler, RsyncTransferError

class TestRsyncHandler:
    def _make_params(self, **kwargs):
        defaults = {
            'host': '192.168.1.10', 'port': 22, 'username': 'deploy',
            'password': None, 'ssh_key': '/tmp/id_rsa',
            'source_path': '/data/', 'destination_path': '/backup/',
            'compress': False, 'encrypt': False,
            'strict_host_key_checking': False, 'known_host_key': None,
        }
        defaults.update(kwargs)
        return defaults

    def test_builds_correct_rsync_command(self):
        handler = RsyncHandler(self._make_params())
        cmd = handler._build_command()
        assert 'rsync' in cmd[0]
        assert '-av' in cmd
        assert 'deploy@192.168.1.10:/backup/' in ' '.join(cmd)

    def test_compress_flag_added_when_enabled(self):
        handler = RsyncHandler(self._make_params(compress=True))
        cmd = handler._build_command()
        assert '--compress' in cmd

    def test_auth_failure_raises_error(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['Permission denied (publickey).\n'])
            mock_proc.wait.return_value = 255
            MockPopen.return_value = mock_proc
            handler = RsyncHandler(self._make_params())
            with pytest.raises(RsyncTransferError, match='AUTH FAILED'):
                handler.execute(log_callback=lambda lvl, msg: None)

    def test_successful_rsync(self):
        with patch('modules.rsync.handler.subprocess.Popen') as MockPopen:
            mock_proc = MagicMock()
            mock_proc.stdout = iter(['sending incremental file list\n', 'file.tar\n'])
            mock_proc.wait.return_value = 0
            MockPopen.return_value = mock_proc
            handler = RsyncHandler(self._make_params())
            logs = []
            handler.execute(log_callback=lambda lvl, msg: logs.append(msg))
            assert any('Transfer complete' in l for l in logs)
```

- [ ] **Step 3: Uruchom test — FAIL**

```bash
pytest tests/test_rsync_handler.py -v
# Expected: ImportError
```

- [ ] **Step 4: Implementuj modules/rsync/handler.py**

```python
import subprocess
import time
from .config import (RSYNC_BASE_FLAGS, RSYNC_COMPRESS_FLAG,
                     RSYNC_TIMEOUT, RSYNC_MAX_RETRIES, RSYNC_RETRY_DELAY)

class RsyncTransferError(Exception):
    pass

class RsyncHandler:
    def __init__(self, params: dict):
        self.params = params

    def _build_ssh_options(self) -> str:
        opts = [f'-p {self.params["port"]}', '-o BatchMode=yes']
        if not self.params['strict_host_key_checking']:
            opts.append('-o StrictHostKeyChecking=no')
        if self.params.get('ssh_key'):
            opts.append(f'-i {self.params["ssh_key"]}')
        return ' '.join(opts)

    def _build_command(self) -> list:
        cmd = ['rsync'] + list(RSYNC_BASE_FLAGS)
        if self.params.get('compress'):
            cmd.append(RSYNC_COMPRESS_FLAG)
        ssh_opts = self._build_ssh_options()
        cmd += ['-e', f'ssh {ssh_opts}']
        cmd.append(self.params['source_path'])
        cmd.append(f'{self.params["username"]}@{self.params["host"]}:{self.params["destination_path"]}')
        return cmd

    def execute(self, log_callback):
        cmd = self._build_command()
        last_error = None
        for attempt in range(1, RSYNC_MAX_RETRIES + 1):
            log_callback('info', f'Starting rsync (attempt {attempt}): {" ".join(cmd)}')
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
            output_lines = []
            for line in proc.stdout:
                line = line.rstrip()
                output_lines.append(line)
                log_callback('info', line)
            exit_code = proc.wait()
            full_output = '\n'.join(output_lines)

            if exit_code == 0:
                log_callback('info', 'Transfer complete')
                return
            if 'Permission denied' in full_output or exit_code == 255:
                raise RsyncTransferError('AUTH FAILED — check credentials')
            if 'No space left' in full_output:
                raise RsyncTransferError('INSUFFICIENT SPACE ON DESTINATION')
            if 'No such file' in full_output:
                raise RsyncTransferError(f'SOURCE NOT FOUND: {self.params["source_path"]}')
            last_error = f'rsync exited with code {exit_code}'
            if attempt < RSYNC_MAX_RETRIES:
                log_callback('warn', f'Retrying in {RSYNC_RETRY_DELAY}s...')
                time.sleep(RSYNC_RETRY_DELAY)
        raise RsyncTransferError(f'CONNECTION TIMEOUT — {last_error}')
```

- [ ] **Step 5: Uruchom test — PASS**

```bash
pytest tests/test_rsync_handler.py -v
# Expected: 4 passed
```

- [ ] **Step 6: Commit**

```bash
git add modules/rsync/ tests/test_rsync_handler.py
git commit -m "feat: add rsync transfer module with error classification"
```

---

### Task 9: Celery tasks — dispatcher + error handling

**Files:**
- Create: `services/worker/tasks.py`
- Create: `services/worker/tests/test_tasks.py`

- [ ] **Step 1: Napisz test tasks**

```python
# services/worker/tests/test_tasks.py
import pytest
from unittest.mock import patch, MagicMock

class TestExecuteTransferTask:
    def test_dispatches_to_sftp_module(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.connection.protocol = 'sftp'
            mock_sftp_instance = MagicMock()
            MockSFTP.return_value = mock_sftp_instance
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            MockSFTP.assert_called_once()
            mock_sftp_instance.execute.assert_called_once()

    def test_marks_job_failed_on_sftp_error(self):
        with patch('tasks.SFTPHandler') as MockSFTP, \
             patch('tasks.TransferJob') as MockJob:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.connection.protocol = 'sftp'
            from modules.sftp.handler import SFTPTransferError
            MockSFTP.return_value.execute.side_effect = SFTPTransferError('AUTH FAILED')
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            mock_job.mark_failed.assert_called_once_with('AUTH FAILED')

    def test_dispatches_to_rsync_module(self):
        with patch('tasks.RsyncHandler') as MockRsync, \
             patch('tasks.TransferJob') as MockJob:
            mock_job = MagicMock()
            MockJob.objects.get.return_value = mock_job
            mock_job.connection.protocol = 'rsync'
            from tasks import execute_transfer
            execute_transfer(job_id=1)
            MockRsync.assert_called_once()
```

- [ ] **Step 2: Implementuj tasks.py**

```python
# services/worker/tasks.py
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
django.setup()

from celery import Celery
from celery.utils.log import get_task_logger
from apps.transfers.models import TransferJob, TransferLog
from modules.sftp.handler import SFTPHandler, SFTPTransferError
from modules.rsync.handler import RsyncHandler, RsyncTransferError

app = Celery('transporter')
app.config_from_object('django.conf:settings', namespace='CELERY')

logger = get_task_logger(__name__)

def _build_params(job: TransferJob) -> dict:
    conn = job.connection
    return {
        'host': conn.host,
        'port': conn.port,
        'username': conn.username,
        'password': conn.password,
        'ssh_key': conn.ssh_key,
        'source_path': job.source_path,
        'destination_path': job.destination_path,
        'compress': conn.compress,
        'encrypt': conn.encrypt,
        'strict_host_key_checking': conn.strict_host_key_checking,
        'known_host_key': conn.known_host_key,
    }

@app.task(bind=True, name='transfers.execute')
def execute_transfer(self, job_id: int):
    job = TransferJob.objects.get(pk=job_id)
    job.mark_running(self.request.id)

    def log_callback(level: str, message: str):
        TransferLog.objects.create(job=job, level=level, message=message)

    params = _build_params(job)
    handler_cls = SFTPHandler if job.connection.protocol == 'sftp' else RsyncHandler
    error_cls = SFTPTransferError if job.connection.protocol == 'sftp' else RsyncTransferError

    try:
        handler_cls(params).execute(log_callback=log_callback)
        job.mark_done()
    except (SFTPTransferError, RsyncTransferError) as e:
        job.mark_failed(str(e))
        log_callback('error', str(e))
    except Exception as e:
        job.mark_failed(f'UNEXPECTED ERROR — {e}')
        log_callback('error', f'UNEXPECTED ERROR — {e}')
        raise

@app.task(name='transfers.cleanup_orphans')
def cleanup_orphan_jobs():
    from django.utils import timezone
    from datetime import timedelta
    from apps.transfers.models import STATUS_RUNNING, STATUS_FAILED
    cutoff = timezone.now() - timedelta(hours=1)
    orphans = TransferJob.objects.filter(status=STATUS_RUNNING, started_at__lt=cutoff)
    count = orphans.count()
    orphans.update(status=STATUS_FAILED, error_message='TASK INTERRUPTED — worker restarted')
    logger.info(f'Cleaned up {count} orphaned jobs')
```

- [ ] **Step 3: Uruchom testy**

```bash
pytest tests/test_tasks.py -v
# Expected: 3 passed
```

- [ ] **Step 4: Commit**

```bash
git add tasks.py tests/test_tasks.py
git commit -m "feat: add Celery task dispatcher with SFTP/rsync routing and orphan cleanup"
```

---

## FAZA 4: UI — CRT/Terminal Interface

### Task 10: Base template + CRT CSS

**Files:**
- Create: `services/web/static/css/crt.css`
- Create: `services/web/templates/base.html`
- Create: `services/web/templates/500.html`

- [ ] **Step 1: Utwórz static/css/crt.css**

```css
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');

:root {
  --bg: #0a0a0a;
  --green: #33ff33;
  --green-bright: #00ff41;
  --amber: #ffb000;
  --red: #ff3333;
  --dim: #1a1a1a;
  --border: #1f4d1f;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--green);
  font-family: 'JetBrains Mono', 'Courier New', monospace;
  font-size: 14px;
  line-height: 1.5;
  min-height: 100vh;
}

/* CRT scanlines overlay */
body::after {
  content: '';
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(0,0,0,0.08) 2px,
    rgba(0,0,0,0.08) 4px
  );
  pointer-events: none;
  z-index: 9999;
}

/* Text glow */
h1, h2, .glow {
  color: var(--green-bright);
  text-shadow: 0 0 8px rgba(0, 255, 65, 0.7);
}

/* ASCII box borders */
.box {
  border: 1px solid var(--border);
  padding: 1rem;
  margin-bottom: 1rem;
  position: relative;
}

.box-title {
  position: absolute;
  top: -0.6rem;
  left: 1rem;
  background: var(--bg);
  padding: 0 0.5rem;
  color: var(--green-bright);
  font-size: 0.85rem;
  letter-spacing: 2px;
  text-transform: uppercase;
}

/* Navigation */
nav {
  border-bottom: 1px solid var(--border);
  padding: 0.75rem 2rem;
  display: flex;
  align-items: center;
  gap: 2rem;
}

nav .logo {
  color: var(--green-bright);
  font-size: 1.1rem;
  font-weight: 700;
  text-shadow: 0 0 10px rgba(0, 255, 65, 0.9);
  letter-spacing: 3px;
}

nav a {
  color: var(--green);
  text-decoration: none;
  letter-spacing: 1px;
  padding: 0.25rem 0.5rem;
  border: 1px solid transparent;
}

nav a:hover, nav a.active {
  border-color: var(--green-bright);
  color: var(--green-bright);
  text-shadow: 0 0 5px rgba(0, 255, 65, 0.5);
}

nav .nav-right { margin-left: auto; color: #888; font-size: 0.8rem; }

/* Main content */
main { padding: 2rem; max-width: 1200px; margin: 0 auto; }

/* Tables */
table { width: 100%; border-collapse: collapse; }
th { color: var(--green-bright); text-align: left; padding: 0.5rem; border-bottom: 1px solid var(--border); letter-spacing: 2px; font-size: 0.8rem; }
td { padding: 0.5rem; border-bottom: 1px solid #111; }
tr:hover td { background: var(--dim); }

/* Forms */
input, select, textarea {
  background: #050505;
  border: 1px solid var(--border);
  color: var(--green);
  font-family: inherit;
  font-size: inherit;
  padding: 0.4rem 0.6rem;
  width: 100%;
  outline: none;
}

input:focus, select:focus, textarea:focus {
  border-color: var(--green-bright);
  box-shadow: 0 0 5px rgba(0, 255, 65, 0.3);
}

/* Blinking cursor on focused inputs */
input:focus::after { content: '█'; animation: blink 1s step-end infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

label { display: block; margin-bottom: 0.25rem; color: #aaffaa; font-size: 0.85rem; letter-spacing: 1px; }
.field { margin-bottom: 1rem; }

/* Buttons */
.btn {
  background: transparent;
  border: 1px solid var(--green);
  color: var(--green);
  cursor: pointer;
  font-family: inherit;
  font-size: inherit;
  padding: 0.4rem 1.2rem;
  letter-spacing: 2px;
  text-transform: uppercase;
  text-decoration: none;
  display: inline-block;
}

.btn:hover { border-color: var(--green-bright); color: var(--green-bright); box-shadow: 0 0 8px rgba(0,255,65,0.4); }
.btn-danger { border-color: var(--red); color: var(--red); }
.btn-danger:hover { box-shadow: 0 0 8px rgba(255,51,51,0.4); }
.btn-warn { border-color: var(--amber); color: var(--amber); }

/* Status badges */
.status { font-size: 0.8rem; padding: 0.1rem 0.4rem; border: 1px solid; letter-spacing: 1px; }
.status-pending  { color: #888; border-color: #444; }
.status-running  { color: var(--amber); border-color: var(--amber); animation: pulse 1.5s ease-in-out infinite; }
.status-done     { color: var(--green-bright); border-color: var(--green-bright); }
.status-failed   { color: var(--red); border-color: var(--red); }

@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }

/* Log terminal */
.log-terminal {
  background: #020202;
  border: 1px solid var(--border);
  font-size: 0.85rem;
  min-height: 200px;
  max-height: 400px;
  overflow-y: auto;
  padding: 1rem;
}

.log-line { margin-bottom: 0.2rem; }
.log-info  { color: var(--green); }
.log-warn  { color: var(--amber); }
.log-error { color: var(--red); }

/* Messages */
.messages { margin-bottom: 1rem; }
.msg-error { color: var(--red); padding: 0.5rem; border: 1px solid var(--red); margin-bottom: 0.5rem; }
.msg-success { color: var(--green-bright); padding: 0.5rem; border: 1px solid var(--green-bright); margin-bottom: 0.5rem; }
```

- [ ] **Step 2: Utwórz templates/base.html**

```html
<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}TMASK-TRANSPORTER{% endblock %}</title>
  {% load static %}
  <link rel="stylesheet" href="{% static 'css/crt.css' %}">
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
</head>
<body>
  {% if user.is_authenticated %}
  <nav>
    <span class="logo">[ TMASK-TRANSPORTER ]</span>
    <a href="{% url 'transfers:create' %}" class="{% if request.resolver_match.app_name == 'transfers' %}active{% endif %}">TRANSFERS</a>
    <a href="{% url 'connections:list' %}" class="{% if request.resolver_match.app_name == 'connections' %}active{% endif %}">CONNECTIONS</a>
    <a href="{% url 'scheduler:list' %}" class="{% if request.resolver_match.app_name == 'scheduler' %}active{% endif %}">SCHEDULER</a>
    <a href="{% url 'transfers:logs' %}" >LOGS</a>
    {% if user.is_admin %}
    <a href="{% url 'accounts:users' %}">USERS</a>
    {% endif %}
    <span class="nav-right">
      USER: {{ user.username|upper }} [{{ user.role|upper }}]
      &nbsp;|&nbsp;
      <form method="post" action="{% url 'accounts:logout' %}" style="display:inline">
        {% csrf_token %}
        <button type="submit" class="btn" style="border:none;padding:0;">LOGOUT</button>
      </form>
    </span>
  </nav>
  {% endif %}

  <main>
    {% if messages %}
    <div class="messages">
      {% for message in messages %}
      <div class="msg-{% if message.tags == 'error' %}error{% else %}success{% endif %}">
        > {{ message }}
      </div>
      {% endfor %}
    </div>
    {% endif %}
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 3: Utwórz templates/500.html**

```html
<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  body { background: #0a0a0a; color: #33ff33; font-family: monospace; display: flex; justify-content: center; align-items: center; height: 100vh; }
  .box { border: 1px solid #1f4d1f; padding: 3rem; text-align: center; }
  h1 { color: #ff3333; font-size: 3rem; }
</style></head>
<body>
  <div class="box">
    <h1>[ SYSTEM ERROR ]</h1>
    <p>KERNEL PANIC — CONTACT ADMIN</p>
    <br>
    <a href="/" style="color: #33ff33;">[ REBOOT ]</a>
  </div>
</body></html>
```

- [ ] **Step 4: Commit**

```bash
git add services/web/static/ services/web/templates/base.html services/web/templates/500.html
git commit -m "feat: add CRT terminal CSS and base template with HTMX"
```

---

### Task 11: Login page

**Files:**
- Create: `services/web/templates/accounts/login.html`

- [ ] **Step 1: Utwórz templates/accounts/login.html**

```html
<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <title>LOGIN — TMASK-TRANSPORTER</title>
  {% load static %}
  <link rel="stylesheet" href="{% static 'css/crt.css' %}">
</head>
<body>
<main style="display:flex; justify-content:center; align-items:center; min-height:100vh;">
  <div style="width:400px;">
    <pre class="glow" style="text-align:center; margin-bottom:2rem; font-size:0.75rem;">
 ████████╗███╗   ███╗ █████╗ ███████╗██╗  ██╗
    ██╔══╝████╗ ████║██╔══██╗██╔════╝██║ ██╔╝
    ██║   ██╔████╔██║███████║███████╗█████╔╝
    ██║   ██║╚██╔╝██║██╔══██║╚════██║██╔═██╗
    ██║   ██║ ╚═╝ ██║██║  ██║███████║██║  ██╗
    ╚═╝   ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
         TRANSPORTER v1.0 — FILE TRANSFER SYSTEM
    </pre>

    <div class="box">
      <span class="box-title">AUTHENTICATION REQUIRED</span>
      <form method="post">
        {% csrf_token %}
        {% if form.non_field_errors %}
        <div class="msg-error">
          {% for error in form.non_field_errors %}> {{ error }}{% endfor %}
        </div>
        {% endif %}
        <div class="field">
          <label>USERNAME:</label>
          <input type="text" name="username" autofocus autocomplete="username"
                 value="{{ form.username.value|default:'' }}">
        </div>
        <div class="field">
          <label>PASSWORD:</label>
          <input type="password" name="password" autocomplete="current-password">
        </div>
        <button type="submit" class="btn" style="width:100%;">[ LOGIN ]</button>
      </form>
    </div>
  </div>
</main>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add services/web/templates/accounts/
git commit -m "feat: add CRT-style login page with ASCII logo"
```

---

### Task 12: Connections UI (list + form)

**Files:**
- Create: `services/web/templates/connections/list.html`
- Create: `services/web/templates/connections/form.html`

- [ ] **Step 1: Utwórz templates/connections/list.html**

```html
{% extends "base.html" %}
{% block title %}CONNECTIONS — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">CONNECTIONS</span>
  <div style="margin-bottom:1rem;">
    <a href="{% url 'connections:create' %}" class="btn">[ + NEW CONNECTION ]</a>
  </div>
  {% if connections %}
  <table>
    <thead>
      <tr>
        <th>NAME</th><th>HOST</th><th>PORT</th><th>PROTO</th>
        <th>COMPRESS</th><th>ENCRYPT</th><th>ACTIONS</th>
      </tr>
    </thead>
    <tbody>
      {% for conn in connections %}
      <tr>
        <td class="glow">{{ conn.name }}</td>
        <td>{{ conn.host }}</td>
        <td>{{ conn.port }}</td>
        <td>{{ conn.protocol|upper }}</td>
        <td>{% if conn.compress %}YES{% else %}—{% endif %}</td>
        <td>{% if conn.encrypt %}YES{% else %}—{% endif %}</td>
        <td>
          <button class="btn btn-warn"
            hx-get="{% url 'connections:test' conn.pk %}"
            hx-target="#test-result-{{ conn.pk }}"
            hx-swap="innerHTML">[TEST]</button>
          <a href="{% url 'connections:edit' conn.pk %}" class="btn">[EDIT]</a>
          <form method="post" action="{% url 'connections:delete' conn.pk %}" style="display:inline"
            onsubmit="return confirm('DELETE {{ conn.name }}?')">
            {% csrf_token %}
            <button type="submit" class="btn btn-danger">[DEL]</button>
          </form>
          <span id="test-result-{{ conn.pk }}" style="font-size:0.8rem; margin-left:0.5rem;"></span>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color:#555;">NO CONNECTIONS CONFIGURED — ADD ONE ABOVE</p>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 2: Utwórz templates/connections/form.html**

```html
{% extends "base.html" %}
{% block title %}{{ action }} CONNECTION{% endblock %}
{% block content %}
<div class="box" style="max-width:600px;">
  <span class="box-title">{{ action }} CONNECTION</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error">{% for e in form.non_field_errors %}> {{ e }}{% endfor %}</div>
    {% endif %}
    {% for field in form %}
    <div class="field">
      <label>{{ field.label|upper }}:</label>
      {{ field }}
      {% if field.errors %}
      <div style="color:var(--red);font-size:0.8rem;">{% for e in field.errors %}{{ e }}{% endfor %}</div>
      {% endif %}
    </div>
    {% endfor %}
    <div style="display:flex;gap:1rem;margin-top:1.5rem;">
      <button type="submit" class="btn">[ SAVE ]</button>
      <a href="{% url 'connections:list' %}" class="btn btn-danger">[ CANCEL ]</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add services/web/templates/connections/
git commit -m "feat: add connections list and form templates with HTMX test button"
```

---

### Task 13: Transfer Now UI + live log (HTMX polling)

**Files:**
- Create: `services/web/templates/transfers/create.html`
- Create: `services/web/templates/transfers/log_fragment.html`
- Create: `services/web/apps/transfers/views.py`
- Create: `services/web/apps/transfers/urls.py`
- Create: `services/web/apps/transfers/forms.py`
- Create: `services/web/apps/transfers/tests/test_views.py`

- [ ] **Step 1: Napisz test widoku create transfer**

```python
# services/web/apps/transfers/tests/test_views.py
import pytest
from django.urls import reverse
from apps.transfers.models import TransferJob, STATUS_PENDING

@pytest.mark.django_db
class TestTransferCreateView:
    def test_create_form_renders(self, auth_client):
        response = auth_client.get(reverse('transfers:create'))
        assert response.status_code == 200

    def test_create_transfer_dispatches_celery_task(self, auth_client, regular_user, make_connection, mocker):
        mock_delay = mocker.patch('apps.transfers.views.execute_transfer.delay')
        conn = make_connection(regular_user)
        response = auth_client.post(reverse('transfers:create'), {
            'connection': conn.pk,
            'source_path': '/data/file.tar',
            'destination_path': '/backup/',
        })
        assert response.status_code == 302
        job = TransferJob.objects.get(owner=regular_user)
        assert job.status == STATUS_PENDING
        mock_delay.assert_called_once_with(job_id=job.pk)

    def test_log_fragment_returns_logs(self, auth_client, regular_user, make_connection):
        from apps.transfers.models import TransferLog
        job = TransferJob.objects.create(
            owner=regular_user,
            connection=make_connection(regular_user),
            source_path='/x', destination_path='/y',
        )
        TransferLog.objects.create(job=job, level='info', message='Transfer started')
        response = auth_client.get(reverse('transfers:log_fragment', args=[job.pk]))
        assert response.status_code == 200
        assert b'Transfer started' in response.content
```

- [ ] **Step 2: Uruchom test — FAIL**

```bash
pytest apps/transfers/tests/test_views.py -v
# Expected: ImportError lub NoReverseMatch
```

- [ ] **Step 3: Implementuj transfers/views.py**

```python
# services/web/apps/transfers/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from .models import TransferJob, STATUS_RUNNING
from .forms import TransferForm
# Import z worker — przez Celery app signature
from celery import current_app

@login_required
def transfer_create(request):
    from apps.connections.models import Connection
    connections = Connection.objects.filter(owner=request.user)
    form = TransferForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        job = form.save(commit=False)
        job.owner = request.user
        job.save()
        current_app.send_task('transfers.execute', kwargs={'job_id': job.pk})
        return redirect('transfers:detail', pk=job.pk)
    return render(request, 'transfers/create.html', {'form': form, 'connections': connections})

@login_required
def transfer_detail(request, pk):
    job = get_object_or_404(TransferJob, pk=pk, owner=request.user)
    return render(request, 'transfers/create.html', {'job': job})

@login_required
def log_fragment(request, pk):
    job = get_object_or_404(TransferJob, pk=pk, owner=request.user)
    logs = job.logs.all()
    still_running = job.status == STATUS_RUNNING
    return render(request, 'transfers/log_fragment.html', {
        'job': job, 'logs': logs, 'still_running': still_running
    })

@login_required
def transfer_logs(request):
    jobs = TransferJob.objects.filter(owner=request.user).select_related('connection')
    return render(request, 'logs/list.html', {'jobs': jobs})
```

- [ ] **Step 4: Utwórz transfers/urls.py i forms.py**

```python
# services/web/apps/transfers/urls.py
from django.urls import path
from . import views

app_name = 'transfers'

urlpatterns = [
    path('', views.transfer_create, name='create'),
    path('<int:pk>/', views.transfer_detail, name='detail'),
    path('<int:pk>/logs/', views.log_fragment, name='log_fragment'),
    path('logs/', views.transfer_logs, name='logs'),
]
```

```python
# services/web/apps/transfers/forms.py
from django import forms
from .models import TransferJob
from apps.connections.models import Connection

class TransferForm(forms.ModelForm):
    class Meta:
        model = TransferJob
        fields = ['connection', 'source_path', 'destination_path']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['connection'].queryset = Connection.objects.filter(owner=user)
```

- [ ] **Step 5: Utwórz templates/transfers/create.html**

```html
{% extends "base.html" %}
{% block title %}TRANSFER — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div style="display:grid; grid-template-columns:1fr 1fr; gap:2rem;">
  <div class="box">
    <span class="box-title">NEW TRANSFER</span>
    <form method="post">
      {% csrf_token %}
      {% for field in form %}
      <div class="field">
        <label>{{ field.label|upper }}:</label>
        {{ field }}
        {% if field.errors %}<div style="color:var(--red);font-size:0.8rem;">{{ field.errors }}</div>{% endif %}
      </div>
      {% endfor %}
      <button type="submit" class="btn">[ EXECUTE TRANSFER ]</button>
    </form>
  </div>

  {% if job %}
  <div class="box">
    <span class="box-title">TRANSFER LOG — #{{ job.pk }}</span>
    <div style="margin-bottom:0.5rem;">
      STATUS: <span class="status status-{{ job.status }}">{{ job.status|upper }}</span>
    </div>
    <div
      id="log-output"
      class="log-terminal"
      {% if job.status == 'running' or job.status == 'pending' %}
        hx-get="{% url 'transfers:log_fragment' job.pk %}"
        hx-trigger="every 2s"
        hx-swap="innerHTML"
      {% endif %}
    >
      {% include "transfers/log_fragment.html" with logs=job.logs.all %}
    </div>
  </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 6: Utwórz templates/transfers/log_fragment.html**

```html
{% for log in logs %}
<div class="log-line log-{{ log.level }}">
  [{{ log.timestamp|date:"H:i:s" }}] {{ log.message }}
</div>
{% endfor %}
{% if still_running %}
<div class="log-line log-info" style="animation: pulse 1s infinite;">▋ RUNNING...</div>
{% endif %}
```

- [ ] **Step 7: Uruchom testy + commit**

```bash
pytest apps/transfers/ -v
git add apps/transfers/ templates/transfers/ templates/logs/
git commit -m "feat: add transfer create view with HTMX live log polling"
```

---

### Task 14: Scheduler UI

**Files:**
- Create: `services/web/templates/scheduler/list.html`
- Create: `services/web/templates/scheduler/form.html`
- Create: `services/web/apps/scheduler/views.py`
- Create: `services/web/apps/scheduler/urls.py`
- Create: `services/web/apps/scheduler/forms.py`

- [ ] **Step 1: Implementuj scheduler/views.py**

```python
# services/web/apps/scheduler/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from .models import ScheduledTransfer
from .forms import ScheduledTransferForm

@login_required
def schedule_list(request):
    schedules = ScheduledTransfer.objects.filter(owner=request.user).select_related('connection')
    return render(request, 'scheduler/list.html', {'schedules': schedules})

@login_required
def schedule_create(request):
    form = ScheduledTransferForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        sched = form.save(commit=False)
        sched.owner = request.user
        sched.save()
        _sync_celery_beat(sched)
        return redirect('scheduler:list')
    return render(request, 'scheduler/form.html', {'form': form, 'action': 'CREATE'})

@login_required
def schedule_edit(request, pk):
    sched = get_object_or_404(ScheduledTransfer, pk=pk, owner=request.user)
    form = ScheduledTransferForm(request.POST or None, instance=sched, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        _sync_celery_beat(sched)
        return redirect('scheduler:list')
    return render(request, 'scheduler/form.html', {'form': form, 'action': 'EDIT', 'sched': sched})

@login_required
@require_POST
def schedule_toggle(request, pk):
    sched = get_object_or_404(ScheduledTransfer, pk=pk, owner=request.user)
    sched.enabled = not sched.enabled
    sched.save(update_fields=['enabled'])
    _sync_celery_beat(sched)
    return redirect('scheduler:list')

@login_required
@require_POST
def schedule_delete(request, pk):
    sched = get_object_or_404(ScheduledTransfer, pk=pk, owner=request.user)
    _delete_celery_beat(sched)
    sched.delete()
    return redirect('scheduler:list')

def _sync_celery_beat(sched: ScheduledTransfer):
    from django_celery_beat.models import PeriodicTask, CrontabSchedule
    import json
    minute, hour, day_of_month, month_of_year, day_of_week = sched.cron_expr.split()
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=minute, hour=hour, day_of_month=day_of_month,
        month_of_year=month_of_year, day_of_week=day_of_week,
    )
    task_name = f'scheduled_transfer_{sched.pk}'
    PeriodicTask.objects.update_or_create(
        name=task_name,
        defaults={
            'crontab': crontab,
            'task': 'transfers.execute',
            'kwargs': json.dumps({'job_id': None, 'scheduled_id': sched.pk}),
            'enabled': sched.enabled,
        }
    )

def _delete_celery_beat(sched: ScheduledTransfer):
    from django_celery_beat.models import PeriodicTask
    PeriodicTask.objects.filter(name=f'scheduled_transfer_{sched.pk}').delete()
```

- [ ] **Step 2: Utwórz scheduler/urls.py i forms.py**

```python
# services/web/apps/scheduler/urls.py
from django.urls import path
from . import views

app_name = 'scheduler'

urlpatterns = [
    path('', views.schedule_list, name='list'),
    path('new/', views.schedule_create, name='create'),
    path('<int:pk>/edit/', views.schedule_edit, name='edit'),
    path('<int:pk>/toggle/', views.schedule_toggle, name='toggle'),
    path('<int:pk>/delete/', views.schedule_delete, name='delete'),
]
```

```python
# services/web/apps/scheduler/forms.py
from django import forms
from .models import ScheduledTransfer
from apps.connections.models import Connection

class ScheduledTransferForm(forms.ModelForm):
    class Meta:
        model = ScheduledTransfer
        fields = ['connection', 'source_path', 'destination_path', 'cron_expr', 'enabled']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['connection'].queryset = Connection.objects.filter(owner=user)

    def clean_cron_expr(self):
        expr = self.cleaned_data['cron_expr']
        parts = expr.split()
        if len(parts) != 5:
            raise forms.ValidationError('INVALID CRON — format: "min hour day month weekday" (5 fields)')
        return expr
```

- [ ] **Step 3: Utwórz templates/scheduler/list.html**

```html
{% extends "base.html" %}
{% block title %}SCHEDULER{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">SCHEDULED TRANSFERS</span>
  <div style="margin-bottom:1rem;">
    <a href="{% url 'scheduler:create' %}" class="btn">[ + NEW SCHEDULE ]</a>
  </div>
  {% if schedules %}
  <table>
    <thead>
      <tr><th>CONNECTION</th><th>SOURCE</th><th>DESTINATION</th><th>CRON</th><th>LAST RUN</th><th>STATUS</th><th>ACTIONS</th></tr>
    </thead>
    <tbody>
      {% for s in schedules %}
      <tr>
        <td class="glow">{{ s.connection.name }}</td>
        <td>{{ s.source_path }}</td>
        <td>{{ s.destination_path }}</td>
        <td>{{ s.cron_expr }}</td>
        <td>{{ s.last_run|date:"Y-m-d H:i"|default:"—" }}</td>
        <td>{% if s.enabled %}<span style="color:var(--green-bright);">● ACTIVE</span>{% else %}<span style="color:#555;">○ PAUSED</span>{% endif %}</td>
        <td>
          <form method="post" action="{% url 'scheduler:toggle' s.pk %}" style="display:inline">{% csrf_token %}
            <button type="submit" class="btn btn-warn">{% if s.enabled %}[PAUSE]{% else %}[RESUME]{% endif %}</button>
          </form>
          <a href="{% url 'scheduler:edit' s.pk %}" class="btn">[EDIT]</a>
          <form method="post" action="{% url 'scheduler:delete' s.pk %}" style="display:inline"
            onsubmit="return confirm('DELETE schedule?')">{% csrf_token %}
            <button type="submit" class="btn btn-danger">[DEL]</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p style="color:#555;">NO SCHEDULES — ADD ONE ABOVE</p>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 4: Commit**

```bash
git add apps/scheduler/ templates/scheduler/
git commit -m "feat: add scheduler UI with Celery Beat integration"
```

---

### Task 15: Logs view + Users admin view

**Files:**
- Create: `services/web/templates/logs/list.html`
- Create: `services/web/templates/users/list.html`
- Create: `services/web/apps/accounts/views.py` (rozszerz o users_list)

- [ ] **Step 1: Utwórz templates/logs/list.html**

```html
{% extends "base.html" %}
{% block title %}TRANSFER LOGS{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">TRANSFER HISTORY</span>
  <table>
    <thead>
      <tr><th>#</th><th>CONNECTION</th><th>SOURCE</th><th>STATUS</th><th>STARTED</th><th>DURATION</th><th>ACTIONS</th></tr>
    </thead>
    <tbody>
      {% for job in jobs %}
      <tr>
        <td>{{ job.pk }}</td>
        <td class="glow">{{ job.connection.name }}</td>
        <td>{{ job.source_path }}</td>
        <td><span class="status status-{{ job.status }}">{{ job.status|upper }}</span></td>
        <td>{{ job.created_at|date:"Y-m-d H:i" }}</td>
        <td>
          {% if job.finished_at and job.started_at %}
            {{ job.finished_at|timeuntil:job.started_at }}
          {% else %}—{% endif %}
        </td>
        <td><a href="{% url 'transfers:detail' job.pk %}" class="btn">[VIEW]</a></td>
      </tr>
      {% empty %}
      <tr><td colspan="7" style="color:#555;">NO TRANSFER HISTORY</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 2: Dodaj users_list view do accounts/views.py**

```python
# Dodaj do services/web/apps/accounts/views.py:
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from .models import User

@login_required
def users_list(request):
    if not request.user.is_admin:
        raise PermissionDenied
    users = User.objects.all().order_by('username')
    return render(request, 'users/list.html', {'users': users})
```

- [ ] **Step 3: Dodaj URL do accounts/urls.py**

```python
# Dodaj do urlpatterns w accounts/urls.py:
path('users/', views.users_list, name='users'),
```

- [ ] **Step 4: Utwórz templates/users/list.html**

```html
{% extends "base.html" %}
{% block title %}USERS — ADMIN{% endblock %}
{% block content %}
<div class="box">
  <span class="box-title">USER MANAGEMENT</span>
  <table>
    <thead>
      <tr><th>USERNAME</th><th>ROLE</th><th>EMAIL</th><th>LAST LOGIN</th><th>ACTIVE</th></tr>
    </thead>
    <tbody>
      {% for u in users %}
      <tr>
        <td class="glow">{{ u.username }}</td>
        <td><span style="color:{% if u.is_admin %}var(--amber){% else %}var(--green){% endif %}">{{ u.role|upper }}</span></td>
        <td>{{ u.email|default:"—" }}</td>
        <td>{{ u.last_login|date:"Y-m-d H:i"|default:"NEVER" }}</td>
        <td>{% if u.is_active %}<span style="color:var(--green-bright);">● YES</span>{% else %}<span style="color:var(--red);">○ NO</span>{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 5: Commit**

```bash
git add templates/logs/ templates/users/ apps/accounts/views.py apps/accounts/urls.py
git commit -m "feat: add logs history view and admin users list"
```

---

## FAZA 5: Polish & Production

### Task 16: Orphan job cleanup Beat task

- [ ] **Step 1: Zarejestruj cleanup task w django-celery-beat przez migration**

```python
# services/web/apps/transfers/migrations/0002_cleanup_periodic_task.py
from django.db import migrations

def create_cleanup_task(apps, schema_editor):
    try:
        IntervalSchedule = apps.get_model('django_celery_beat', 'IntervalSchedule')
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=5, period='minutes'
        )
        PeriodicTask.objects.get_or_create(
            name='cleanup-orphan-jobs',
            defaults={
                'interval': schedule,
                'task': 'transfers.cleanup_orphans',
                'enabled': True,
            }
        )
    except Exception:
        pass  # django_celery_beat może nie być gotowe przy pierwszym migrate

def remove_cleanup_task(apps, schema_editor):
    try:
        PeriodicTask = apps.get_model('django_celery_beat', 'PeriodicTask')
        PeriodicTask.objects.filter(name='cleanup-orphan-jobs').delete()
    except Exception:
        pass

class Migration(migrations.Migration):
    dependencies = [
        ('transfers', '0001_initial'),
        ('django_celery_beat', '0001_initial'),
    ]
    operations = [migrations.RunPython(create_cleanup_task, remove_cleanup_task)]
```

- [ ] **Step 2: Commit**

```bash
git add apps/transfers/migrations/0002_cleanup_periodic_task.py
git commit -m "feat: register orphan job cleanup as periodic Celery Beat task"
```

---

### Task 17: Weryfikacja end-to-end + README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Uruchom pełny suite testów**

```bash
cd services/web && pytest -v --tb=short
# Expected: all passed, no warnings o deprecated API
cd services/worker && pytest -v --tb=short
# Expected: all passed
```

- [ ] **Step 2: Sprawdź docker-compose build**

```bash
cp .env.example .env
# Edytuj .env — ustaw realne SECRET_KEY i FIELD_ENCRYPTION_KEY:
python -c "import secrets; print(secrets.token_urlsafe(50))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
docker-compose build
# Expected: wszystkie image budują się bez błędów
```

- [ ] **Step 3: Uruchom stack i sprawdź migracje**

```bash
docker-compose up -d postgres redis
docker-compose run --rm web python manage.py migrate
docker-compose run --rm web python manage.py createsuperuser
docker-compose up -d
# Expected: wszystkie kontenery w stanie Up
```

- [ ] **Step 4: Utwórz README.md**

```markdown
# tmask-transporter

Webowa aplikacja do przesyłania plików między systemami Linux przez SSH (SFTP/rsync).

## Wymagania

- Docker + Docker Compose

## Uruchomienie

```bash
cp .env.example .env
# Edytuj .env — ustaw SECRET_KEY i FIELD_ENCRYPTION_KEY
docker-compose up -d
docker-compose run --rm web python manage.py migrate
docker-compose run --rm web python manage.py createsuperuser
```

Aplikacja dostępna pod: http://localhost

## Architektura

- `web` — Django + Gunicorn (UI, API)
- `worker` — Celery worker (SFTP/rsync transfer modules)
- `beat` — Celery Beat (cron scheduling)
- `redis` — Celery broker
- `postgres` — baza danych
- `nginx` — reverse proxy

## Moduły transferu

Każdy moduł ma niezależną konfigurację:
- `services/worker/modules/sftp/` — SFTP/SCP przez Paramiko
- `services/worker/modules/rsync/` — rsync przez SSH
```

- [ ] **Step 5: Final commit**

```bash
git add README.md
git commit -m "docs: add README with setup instructions"
```

---

## Self-Review — Pokrycie specyfikacji

| Wymaganie ze spec | Task |
|---|---|
| Docker Compose, .env, wszystkie kontenery | Task 1 |
| Django settings z python-decouple | Task 2 |
| User model z rolą admin/user, bcrypt | Task 3 |
| Connection model z Fernet encrypted fields | Task 4 |
| SFTP strict_host_key_checking, known_host_key | Task 4 |
| Test connection endpoint (SSH) | Task 4 |
| TransferJob + TransferLog models | Task 5 |
| status: pending/running/done/failed | Task 5 |
| ScheduledTransfer + cron_expr | Task 6 |
| SFTP handler + retry 3x + error classification | Task 7 |
| rsync handler + retry + error classification | Task 8 |
| Celery task dispatcher (sftp/rsync routing) | Task 9 |
| Orphan task cleanup (>1h running → failed) | Task 9, 16 |
| CRT/Terminal UI — CSS, scanlines, glow | Task 10 |
| Login page ASCII art | Task 11 |
| Connections CRUD + TEST button (HTMX) | Task 12 |
| Transfer Now + live log (HTMX polling 2s) | Task 13 |
| Scheduler + cron UI + Celery Beat sync | Task 14 |
| Logs history view | Task 15 |
| Users admin view (admin only) | Task 15 |
| Owner isolation (filter by request.user) | Task 4, 5, 6 |
| Nginx config — jedyny port zewnętrzny | Task 1 |
| compress=True → rsync --compress flag | Task 8 |
| encrypt=True → GPG *(TODO: rozszerz Task 9)* | — |
| File browser modal | *(opcjonalne — nie w MVP)* |

> **Uwaga:** `encrypt=True` (GPG) i file browser zostały oznaczone jako rozszerzenia post-MVP zgodnie z decyzją z brainstormingu. Można dodać jako Task 18 i 19 w przyszłości.
