from django.shortcuts import render

from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN
from .models import ConfigAuditLog

_PAGE_SIZE = 200


@require_role(ROLE_ADMIN)
def audit_log_list(request):
    entries = ConfigAuditLog.objects.select_related('user').all()[:_PAGE_SIZE]
    return render(request, 'audit_log/list.html', {'entries': entries})
