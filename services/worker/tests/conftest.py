import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ---------------------------------------------------------------------------
# Bootstrap minimal Django settings BEFORE tasks.py is imported.
#
# tasks.py does two things at module level that require Django:
#   1. os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')
#   2. django.setup()
#
# Strategy:
#   a) Configure Django with an inline minimal settings object so that
#      django.conf.settings is already "configured" — then setdefault() is
#      a no-op (we pre-set the env var) and setup() becomes a no-op too.
#   b) Stub out the web-service app modules (apps.transfers.*) that don't
#      exist in the worker's Python path.
# ---------------------------------------------------------------------------

# (a) Pre-set env var so tasks.py's setdefault is a no-op
os.environ['DJANGO_SETTINGS_MODULE'] = ''

# Configure Django with a minimal inline settings so pytest-django and Celery
# can resolve django.conf.settings without needing the production module.
import django
from django.conf import settings as _dj_settings
if not _dj_settings.configured:
    _dj_settings.configure(
        INSTALLED_APPS=[],
        DATABASES={},
        CELERY_TASK_ALWAYS_EAGER=True,
        CELERY_BROKER_URL='memory://',
        CELERY_RESULT_BACKEND='cache+memory://',
        TRANSFERS_DIR='/transfers',
        TRANSFERS_RETENTION_DAYS=1,
    )

# Neutralise django.setup() — settings are already configured inline.
django.setup = lambda: None

# (b) Stub out the Django app modules that tasks.py imports at the top level.
# These modules live in services/web/ which is not on the worker's sys.path.
sys.modules.setdefault('apps', MagicMock())
sys.modules.setdefault('apps.transfers', MagicMock())
sys.modules.setdefault('apps.transfers.models', MagicMock())
sys.modules.setdefault('apps.connections', MagicMock())
sys.modules.setdefault('apps.connections.models', MagicMock())
