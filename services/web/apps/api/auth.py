import hashlib
from functools import wraps
from django.http import JsonResponse
from django.utils import timezone
from .models import ApiToken


def get_user_from_token(request):
    header = request.headers.get('Authorization', '')
    if not header.startswith('Token '):
        return None
    raw_key = header[6:]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    try:
        token = ApiToken.objects.select_related('user').get(key_hash=key_hash)
        token.last_used_at = timezone.now()
        token.save(update_fields=['last_used_at'])
        return token.user
    except ApiToken.DoesNotExist:
        return None


def require_api_token(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_user_from_token(request)
        if user is None:
            return JsonResponse({'error': 'Invalid or missing token'}, status=403)
        request.api_user = user
        return view_func(request, *args, **kwargs)
    return wrapper
