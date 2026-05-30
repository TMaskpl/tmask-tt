from .base import *  # NOSONAR  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ['*']

DATABASES = {  # noqa: F405
    **DATABASES,  # noqa: F405
    'default': {**DATABASES['default'], 'HOST': 'localhost'},  # noqa: F405
}

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
