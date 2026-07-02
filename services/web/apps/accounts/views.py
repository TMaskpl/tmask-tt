from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate, get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
import requests

from . import totp
from .forms import LoginForm, ProfileForm, UserCreateForm, TOTPCodeForm
from .permissions import require_role
from .models import ROLE_ADMIN, ROLE_CHOICES
from utils.url_validator import block_private_url
from apps.api.models import ApiToken, MAX_TOKENS_PER_USER
from apps.organization.models import get_organization

PROFILE_URL = 'accounts:profile'
USERS_LIST = 'accounts:users'


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
            next_url = request.GET.get('next', '')
            if user.totp_enabled:
                request.session['pre_2fa_user_id'] = user.id
                request.session['pre_2fa_attempts'] = 0
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                    request.session['pre_2fa_next'] = next_url
                return redirect('accounts:2fa_verify')
            login(request, user)
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect(settings.LOGIN_REDIRECT_URL)
        form.add_error(None, 'Nieprawidłowa nazwa użytkownika lub hasło.')
    return render(request, 'accounts/login.html', {'form': form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('accounts:login')


@require_role(ROLE_ADMIN)
def users_list(request):
    User = get_user_model()
    users = User.objects.all().order_by('username')
    return render(request, 'users/list.html', {
        'users': users,
        'role_choices': ROLE_CHOICES,
        'organization': get_organization(),
    })


@require_role(ROLE_ADMIN)
@require_POST
def change_user_role(request, pk):
    User = get_user_model()
    target = get_object_or_404(User, pk=pk)
    new_role = request.POST.get('role', '')
    valid_roles = dict(ROLE_CHOICES)
    if new_role not in valid_roles:
        messages.error(request, 'Nieprawidłowa rola.')
        return redirect(USERS_LIST)
    if target.role == ROLE_ADMIN and new_role != ROLE_ADMIN:
        remaining_admins = User.objects.filter(role=ROLE_ADMIN).exclude(pk=target.pk).count()
        if remaining_admins == 0:
            messages.error(request, 'Nie można odebrać roli Admin ostatniemu administratorowi.')
            return redirect(USERS_LIST)
    target.role = new_role
    target.save(update_fields=['role'])
    messages.success(request, f'Rola {target.username} zmieniona na {valid_roles[new_role]}.')
    return redirect(USERS_LIST)


@require_role(ROLE_ADMIN)
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        messages.success(request, f'Użytkownik {user.username} utworzony z rolą {user.get_role_display()}.')
        return redirect(USERS_LIST)
    return render(request, 'users/create.html', {'form': form})


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


@login_required
def totp_setup(request):
    if request.user.totp_enabled:
        messages.info(request, '2FA jest już włączone.')
        return redirect(PROFILE_URL)

    secret = request.session.get('pending_totp_secret')

    if request.method == 'POST' and secret:
        form = TOTPCodeForm(request.POST)
        if form.is_valid() and totp.verify_totp(secret, form.cleaned_data['code']):
            request.user.totp_secret = secret
            request.user.totp_enabled = True
            request.user.save(update_fields=['totp_secret', 'totp_enabled'])
            del request.session['pending_totp_secret']
            request.session['new_recovery_codes'] = totp.generate_recovery_codes(request.user)
            return redirect('accounts:2fa_recovery_codes')
        form.add_error(None, 'Nieprawidłowy kod.')
    else:
        if not secret:
            secret = totp.generate_secret()
            request.session['pending_totp_secret'] = secret
            if request.method == 'POST':
                messages.error(request, 'Sesja wygasła — zeskanuj kod QR ponownie.')
        form = TOTPCodeForm()

    uri = totp.build_provisioning_uri(secret, request.user.username)
    qr_data_uri = totp.build_qr_data_uri(uri)
    return render(request, 'accounts/totp_setup.html', {'form': form, 'qr_data_uri': qr_data_uri, 'secret': secret})


@login_required
def totp_recovery_codes(request):
    codes = request.session.pop('new_recovery_codes', None)
    if not codes:
        return redirect(PROFILE_URL)
    return render(request, 'accounts/totp_recovery_codes.html', {'codes': codes})


MAX_PRE_2FA_ATTEMPTS = 5


def totp_verify(request):
    user_id = request.session.get('pre_2fa_user_id')
    if not user_id:
        return redirect('accounts:login')
    User = get_user_model()
    user = get_object_or_404(User, pk=user_id)

    form = TOTPCodeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        code = form.cleaned_data['code']
        recovery_match = None
        if totp.verify_totp(user.totp_secret, code):
            valid = True
        else:
            recovery_match = totp.check_recovery_code(user, code)
            valid = recovery_match is not None

        if valid:
            next_url = request.session.pop('pre_2fa_next', '')
            del request.session['pre_2fa_user_id']
            del request.session['pre_2fa_attempts']
            login(request, user)
            if recovery_match:
                remaining = user.recovery_codes.filter(used_at__isnull=True).count()
                messages.success(request, f'Zalogowano kodem zapasowym ({remaining} pozostało).')
            if next_url:
                return redirect(next_url)
            return redirect(settings.LOGIN_REDIRECT_URL)

        request.session['pre_2fa_attempts'] += 1
        if request.session['pre_2fa_attempts'] >= MAX_PRE_2FA_ATTEMPTS:
            for key in ('pre_2fa_user_id', 'pre_2fa_attempts', 'pre_2fa_next'):
                request.session.pop(key, None)
            messages.error(request, 'Zbyt wiele nieudanych prób — zaloguj się ponownie.')
            return redirect('accounts:login')
        form.add_error(None, 'Nieprawidłowy kod.')

    return render(request, 'accounts/totp_verify.html', {'form': form})
