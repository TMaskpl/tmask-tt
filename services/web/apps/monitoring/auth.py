import secrets
from functools import wraps
from django.conf import settings
from django.http import HttpResponse


def require_metrics_token(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        expected = settings.METRICS_TOKEN
        header = request.headers.get('Authorization', '')
        if not expected or not header.startswith('Bearer '):
            return HttpResponse(status=401, headers={'WWW-Authenticate': 'Bearer'})
        provided = header[len('Bearer '):]
        if not provided.isascii():
            return HttpResponse(status=401, headers={'WWW-Authenticate': 'Bearer'})
        if not secrets.compare_digest(provided, expected):
            return HttpResponse(status=401, headers={'WWW-Authenticate': 'Bearer'})
        return view_func(request, *args, **kwargs)
    return wrapper
