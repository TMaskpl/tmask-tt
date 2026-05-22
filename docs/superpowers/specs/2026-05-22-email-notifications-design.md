# tmask-transporter — Email Notifications Design Spec

**Data:** 2026-05-22
**Status:** Zatwierdzony
**Autor:** Daniel Niemczok

---

## Cel

Dodanie konfigurowalnych powiadomień email dla użytkowników po zakończeniu transferu. Każdy użytkownik samodzielnie wybiera, o czym chce być powiadamiany (sukces, błąd, lub oba).

---

## Zakres

- Dwa nowe pola na modelu `User`: `notify_on_done`, `notify_on_failed`
- Osobny Celery task `send_notification` — dispatchowany przez `execute_transfer`
- Multipart email (plain text ASCII + HTML w stylu CRT)
- Strona profilu `/accounts/profile/` z formularzem preferencji
- Konfiguracja SMTP przez `.env`

Poza zakresem: powiadomienia push/SMS, digest dzienny, powiadomienia adminów o transferach innych użytkowników.

---

## Architektura

```
execute_transfer (worker/tasks.py)
  ├── mark_done()   → send_notification.delay(job.pk)
  └── mark_failed() → send_notification.delay(job.pk)

send_notification (worker/notifications.py)
  ├── pobiera job + user
  ├── sprawdza user.email i preferencje
  ├── renderuje plain text + HTML przez Django templates
  └── send_mail() z retry 3x co 60s
```

---

## Sekcja 1: Model i konfiguracja SMTP

### Zmiany w `apps/accounts/models.py`

Dwa nowe pola na istniejącym modelu `User`:

```python
notify_on_done   = models.BooleanField(default=False)
notify_on_failed = models.BooleanField(default=True)
```

Domyślnie: powiadomienia o błędach włączone, o sukcesach wyłączone.

Wymagana migracja: `python manage.py makemigrations accounts`.

### Zmienne w `.env` i `.env.example`

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=noreply@example.com
EMAIL_HOST_PASSWORD=secret
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=TMask Transporter <noreply@example.com>
```

### Zmiany w `config/settings/base.py`

```python
EMAIL_BACKEND       = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST          = config('EMAIL_HOST', default='')
EMAIL_PORT          = config('EMAIL_PORT', default=587, cast=int)
EMAIL_HOST_USER     = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS       = config('EMAIL_USE_TLS', default=True, cast=bool)
DEFAULT_FROM_EMAIL  = config('DEFAULT_FROM_EMAIL', default='noreply@localhost')
```

Default backend `console` — w trybie developerskim maile trafiają do stdout kontenera, bez konieczności konfiguracji SMTP.

---

## Sekcja 2: Celery task i szablony email

### Nowy plik `services/worker/notifications.py`

```python
from celery import Celery
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from apps.transfers.models import TransferJob

app = Celery('transporter')

@app.task(name='transfers.send_notification', bind=True, max_retries=3, default_retry_delay=60)
def send_notification(self, job_id: int):
    job = TransferJob.objects.select_related('owner', 'connection', 'flow').get(pk=job_id)
    user = job.owner

    if not user.email:
        return
    if job.status == 'done' and not user.notify_on_done:
        return
    if job.status == 'failed' and not user.notify_on_failed:
        return

    subject, plain, html = _render_notification(job)
    try:
        send_mail(
            subject, plain,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=html,
            fail_silently=False,
        )
    except Exception as exc:
        raise self.retry(exc=exc)


def _render_notification(job):
    status = job.status  # 'done' lub 'failed'
    context = {'job': job}
    subject = f'[TMask] Transfer #{job.pk} — {"DONE" if status == "done" else "FAILED"}'
    plain = render_to_string(f'notifications/transfer_{status}.txt', context)
    html  = render_to_string(f'notifications/transfer_{status}.html', context)
    return subject, plain, html
```

### Zmiany w `services/worker/tasks.py`

Importuj `send_notification` i dodaj `.delay()` po każdym `mark_done()` / `mark_failed()`:

```python
from notifications import send_notification

# po mark_done():
job.mark_done()
send_notification.delay(job.pk)

# po mark_failed() (oba bloki except):
job.mark_failed(str(e))
send_notification.delay(job.pk)
```

### Szablony email — `services/web/templates/notifications/`

Cztery pliki: `transfer_done.txt`, `transfer_done.html`, `transfer_failed.txt`, `transfer_failed.html`.

**Plain text** (`transfer_done.txt`):

```
╔══════════════════════════════════════╗
║  TMASK TRANSPORTER — TRANSFER DONE   ║
╚══════════════════════════════════════╝

Job #{{ job.pk }} zakończony sukcesem.

  FROM : {{ job.source_path }}
  TO   : {{ job.destination_path }}
  START: {{ job.started_at|date:"Y-m-d H:i" }}
  END  : {{ job.finished_at|date:"Y-m-d H:i" }}
  HOST : {% if job.connection %}{{ job.connection.name }} ({{ job.connection.protocol|upper }}){% elif job.flow %}RELAY: {{ job.flow.name }}{% endif %}

--
TMask Transporter | powiadomienia: /accounts/profile/
```

**Plain text** (`transfer_failed.txt`) — analogicznie, z sekcją ERROR:

```
╔══════════════════════════════════════╗
║  TMASK TRANSPORTER — TRANSFER FAILED ║
╚══════════════════════════════════════╝

Job #{{ job.pk }} zakończony błędem.

  FROM  : {{ job.source_path }}
  TO    : {{ job.destination_path }}
  START : {{ job.started_at|date:"Y-m-d H:i" }}
  ERROR : {{ job.error_message }}
  HOST  : {% if job.connection %}{{ job.connection.name }}{% elif job.flow %}RELAY: {{ job.flow.name }}{% endif %}

--
TMask Transporter | powiadomienia: /accounts/profile/
```

**HTML** (`transfer_done.html`, `transfer_failed.html`) — inline CSS, monospace font, tło `#0a0a0a`, tekst `#33ff33` (done) / `#ff3333` (failed). Zawiera te same dane co plain text, bez zewnętrznych zasobów (kompatybilność z klientami pocztowymi).

---

## Sekcja 3: Strona profilu

### Nowy widok `profile_view` w `apps/accounts/views.py`

```python
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
```

### Nowy `ProfileForm` w `apps/accounts/forms.py`

```python
class ProfileForm(forms.ModelForm):
    class Meta:
        model  = get_user_model()
        fields = ['email', 'notify_on_done', 'notify_on_failed']
        labels = {
            'email':            'Adres email',
            'notify_on_done':   'Powiadamiaj o sukcesach transferu',
            'notify_on_failed': 'Powiadamiaj o błędach transferu',
        }
```

### URL w `apps/accounts/urls.py`

```python
path('profile/', views.profile_view, name='profile'),
```

### Szablon `templates/accounts/profile.html`

Rozszerza `base.html`. Sekcja "POWIADOMIENIA EMAIL" w stylu CRT:

```
┌─ PROFIL ──────────────────────────────────────────┐
│ UŻYTKOWNIK: {{ user.username }}                    │
│ ROLA: {{ user.role }}                              │
├─ POWIADOMIENIA EMAIL ──────────────────────────────┤
│ Adres email: [________________________]            │
│                                                    │
│ [✓] Powiadamiaj o błędach transferu               │
│ [ ] Powiadamiaj o sukcesach transferu             │
│                                                    │
│            [ZAPISZ USTAWIENIA]                    │
│                                                    │
│ ⚠ Brak adresu email — powiadomienia nieaktywne    │  ← gdy email pusty
└────────────────────────────────────────────────────┘
```

Ostrzeżenie wyświetlane warunkowo tylko gdy `user.email` jest puste.

### Link w nawigacji `base.html`

Dodać "PROFIL" do paska nawigacji obok "LOGOUT":
```html
<a href="{% url 'accounts:profile' %}">[ PROFIL ]</a>
```

---

## Testy

### `services/web/apps/accounts/tests/`
- `test_profile_view.py` — GET zwraca formularz z aktualnymi wartościami; POST zapisuje email i preferencje; redirect po zapisie
- `test_profile_form.py` — walidacja email; oba pola BooleanField

### `services/worker/tests/test_notifications.py`
- `send_notification` nie wysyła jeśli `user.email` pusty
- `send_notification` nie wysyła jeśli preferencja wyłączona
- `send_notification` wysyła gdy warunki spełnione (mock `send_mail`)
- retry przy błędzie SMTP (mock rzuca wyjątek)
- `_render_notification` zwraca poprawny subject i oba formaty dla `done` i `failed`

---

## Migracje i deployment

1. `python manage.py makemigrations accounts` — nowe pola `notify_on_done`, `notify_on_failed`
2. `python manage.py migrate`
3. Uzupełnić SMTP w `.env` (lub zostawić `console` backend w dev)
4. Rebuild web + worker kontenerów

Istniejące konta użytkowników po migracji: `notify_on_done=False`, `notify_on_failed=True` — bezpieczne defaults.
