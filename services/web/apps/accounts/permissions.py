from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import ROLE_LEVEL


def require_role(min_role: str):
    """View decorator: require request.user.role_level >= ROLE_LEVEL[min_role].

    Implies login_required (redirects anonymous users to login instead of 403).
    """
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if request.user.role_level < ROLE_LEVEL[min_role]:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
