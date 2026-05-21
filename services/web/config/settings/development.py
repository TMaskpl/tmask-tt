from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*']

DATABASES = {
    **DATABASES,
    'default': {**DATABASES['default'], 'HOST': 'localhost'},
}

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
