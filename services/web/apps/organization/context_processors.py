from .models import get_organization


def organization(request):
    if not request.user.is_authenticated:
        return {}
    return {'organization': get_organization()}
