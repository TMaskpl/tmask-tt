from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate, get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
import requests

from .forms import LoginForm, ProfileForm
from utils.url_validator import block_private_url


def login_view(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data['username'],
            password=form.cleaned_data['password'],
        )
        if user:
            login(request, user)
            next_url = request.GET.get('next', '')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect(settings.LOGIN_REDIRECT_URL)
        form.add_error(None, 'Nieprawidłowa nazwa użytkownika lub hasło.')
    return render(request, 'accounts/login.html', {'form': form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('accounts:login')


@login_required
def users_list(request):
    if not request.user.is_admin:
        raise PermissionDenied
    User = get_user_model()
    users = User.objects.all().order_by('username')
    return render(request, 'users/list.html', {'users': users})


@login_required
def profile_view(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Ustawienia zapisane.')
            return redirect('accounts:profile')
    else:
        form = ProfileForm(instance=request.user)
    return render(request, 'accounts/profile.html', {'form': form})


@login_required
@require_POST
def test_webhook(request):
    url = request.POST.get('webhook_url', '').strip()
    if not url:
        return JsonResponse({'ok': False, 'error': 'Brak URL'})
    payload = {
        'job_id': 0,
        'status': 'test',
        'source_path': '/test/source',
        'destination_path': '/test/destination',
        'connection': 'TEST',
        'started_at': None,
        'finished_at': None,
        'error': None,
    }
    try:
        block_private_url(url)
    except ValueError as e:
        return JsonResponse({'ok': False, 'error': str(e)})
    try:
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        return JsonResponse({'ok': True, 'code': resp.status_code})
    except requests.RequestException as e:
        return JsonResponse({'ok': False, 'error': str(e)})
