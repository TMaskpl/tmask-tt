from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate, get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
import requests

from .forms import LoginForm, ProfileForm
from utils.url_validator import block_private_url
from apps.api.models import ApiToken, MAX_TOKENS_PER_USER

PROFILE_URL = 'accounts:profile'


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
            return redirect(PROFILE_URL)
        new_token = None
    else:
        form = ProfileForm(instance=request.user)
        new_token = request.session.pop('new_api_token', None)
    api_tokens = request.user.api_tokens.all()
    return render(request, 'accounts/profile.html', {
        'form': form,
        'api_tokens': api_tokens,
        'new_token': new_token,
    })


@login_required
@require_POST
def test_webhook(request):
    url = request.POST.get('webhook_url', '').strip()
    if not url:
        return JsonResponse({'ok': False, 'error': 'Brak URL'})
    if 'hooks.slack.com' in url:
        payload = {'text': ':white_check_mark: *TMask Transporter* — test powiadomienia Slack'}
    else:
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


@login_required
@require_POST
def generate_api_token(request):
    if request.user.api_tokens.count() >= MAX_TOKENS_PER_USER:
        messages.error(request, f'Limit {MAX_TOKENS_PER_USER} tokenów osiągnięty. Usuń token aby dodać nowy.')
        return redirect(PROFILE_URL)
    label = request.POST.get('label', '').strip()[:100]
    if not label:
        messages.error(request, 'Etykieta tokenu jest wymagana.')
        return redirect(PROFILE_URL)
    _, raw_key = ApiToken.generate(request.user, label)
    request.session['new_api_token'] = raw_key
    messages.success(request, 'Token wygenerowany. Zapisz go — nie zostanie pokazany ponownie.')
    return redirect(PROFILE_URL)


@login_required
@require_POST
def revoke_api_token(request, token_id):
    token = get_object_or_404(ApiToken, pk=token_id, user=request.user)
    token.delete()
    messages.success(request, 'Token usunięty.')
    return redirect(PROFILE_URL)
