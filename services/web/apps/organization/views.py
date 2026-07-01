from django.contrib import messages
from django.shortcuts import render, redirect

from apps.accounts.permissions import require_role
from apps.accounts.models import ROLE_ADMIN
from .forms import OrganizationForm
from .models import get_organization


@require_role(ROLE_ADMIN)
def organization_settings(request):
    org = get_organization()
    form = OrganizationForm(request.POST or None, instance=org)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Nazwa organizacji zaktualizowana.')
        return redirect('organization:settings')
    return render(request, 'organization/settings.html', {'form': form, 'organization': org})
