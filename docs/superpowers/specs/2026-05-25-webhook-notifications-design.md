# Webhook Notifications — Design Spec

**Data:** 2026-05-25  
**Status:** zatwierdzony  
**Estymacja:** ~4-5h, ~+12 testów

## Cel

Generyczny webhook per-user: po zakończeniu lub błędzie transferu worker wysyła `POST JSON` na skonfigurowany URL. Działa ze Slack Incoming Webhooks, Telegramem przez n8n/Zapier, Discordem, Make i każdym innym serwisem akceptującym HTTP POST.

## Zakres

- Jedno pole `webhook_url` per użytkownik + dwa toggle'e `webhook_on_done` / `webhook_on_failed`
- Asynchroniczne wysyłanie przez Celery z retry (max 3, co 60s)
- Przycisk `[TEST]` w profilu — weryfikuje URL przed zapisem przez HTMX

Poza zakresem: wiele webhooków per user, dedykowane integracje Slack/Telegram, podpisywanie payloadu (HMAC).

## Model danych

Trzy nowe pola na `apps.accounts.User` (migracja `0003_webhook_fields`):

```python
webhook_url       = models.URLField(blank=True, default='')
webhook_on_done   = models.BooleanField(default=False)
webhook_on_failed = models.BooleanField(default=True)
```

Domyślnie: powiadamiaj przy błędzie, nie przy sukcesie — spójnie z `notify_on_failed=True` / `notify_on_done=False`.

## Payload JSON

```json
{
  "job_id": 42,
  "status": "done",
  "source_path": "/data/file.tar",
  "destination_path": "/backup/file.tar",
  "connection": "MyServer (sftp)",
  "started_at": "2026-05-25 14:00",
  "finished_at": "2026-05-25 14:02",
  "error": null
}
```

- `connection`: `"NazwaSerwera (protokół)"` dla transferów bezpośrednich, `"RELAY: NazwaFlow"` dla relay flows
- `error`: `null` przy statusie `done`, string z komunikatem przy `failed`
- Daty w formacie `YYYY-MM-DD HH:MM` (Europe/Warsaw), `null` gdy niedostępne

## Zmiany w kodzie

### `services/worker/notifications.py`

Nowa prywatna funkcja `_build_webhook_payload(job) -> dict` budująca payload.

Nowa funkcja publiczna `send_webhook_notification(job) -> bool`:

```python
def send_webhook_notification(job) -> bool:
    user = job.owner
    if not user.webhook_url:
        return False
    if job.status == 'done' and not user.webhook_on_done:
        return False
    if job.status == 'failed' and not user.webhook_on_failed:
        return False
    payload = _build_webhook_payload(job)
    resp = requests.post(user.webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    return True
```

`raise_for_status()` sprawia, że non-2xx traktowany jako wyjątek → Celery retry.

### `services/worker/tasks.py`

Nowy task (obok `send_notification`):

```python
@app.task(bind=True, name='transfers.send_webhook', max_retries=3, default_retry_delay=60)
def send_webhook(self, job_id: int):
    try:
        job = TransferJob.objects.select_related('owner', 'connection', 'flow').get(pk=job_id)
    except Exception:
        logger.error(f'TransferJob {job_id} not found — webhook skipped')
        return
    try:
        send_webhook_notification(job)
    except Exception as exc:
        raise self.retry(exc=exc)
```

`execute_transfer` — po `mark_done()` i `mark_failed()` wywołuje oba taski:

```python
send_notification.delay(job.pk)
send_webhook.delay(job.pk)
```

### `services/web/apps/accounts/`

**`forms.py` — `ProfileForm`:** dodaj pola `webhook_url`, `webhook_on_done`, `webhook_on_failed`.

**`views.py` — nowy endpoint `test_webhook`:**

```python
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
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        return JsonResponse({'ok': True, 'code': resp.status_code})
    except requests.RequestException as e:
        return JsonResponse({'ok': False, 'error': str(e)})
```

**`urls.py`:** `path('test-webhook/', views.test_webhook, name='test_webhook')`

### `services/web/templates/accounts/profile.html`

Nowa sekcja `[ WEBHOOK ]` poniżej `[ POWIADOMIENIA EMAIL ]`:

```
[ WEBHOOK ]
WEBHOOK URL: [________________________________] [TEST]
> <wynik testu inline — zielony OK lub czerwony ERROR>
☑ POWIADAMIAJ PRZY BŁĘDZIE
☐ POWIADAMIAJ PRZY SUKCESIE
```

Przycisk `[TEST]` — HTMX `hx-post="/accounts/test-webhook/"`, `hx-include` pobiera wartość pola `webhook_url` z formularza, wynik renderowany inline bez przeładowania strony.

## Obsługa błędów

| Scenariusz | Zachowanie |
|-----------|------------|
| Brak `webhook_url` | `send_webhook_notification` zwraca `False`, task kończy się bez retry |
| Timeout (>10s) | `requests.Timeout` → Celery retry (max 3, co 60s) |
| Non-2xx response | `raise_for_status()` → `HTTPError` → Celery retry |
| Job nie istnieje | Log error, task kończy się bez retry |
| Test endpoint — brak URL | `{"ok": false, "error": "Brak URL"}` |
| Test endpoint — błąd sieci | `{"ok": false, "error": "<komunikat>"}` |

## Testy

### `services/worker/tests/test_notifications.py` — nowa klasa `TestSendWebhookNotification`

| Test | Opis |
|------|------|
| `test_skips_if_no_url` | Pusty `webhook_url` → `False`, `requests.post` nie wywołany |
| `test_skips_done_if_webhook_on_done_false` | `status=done`, toggle wyłączony → skip |
| `test_skips_failed_if_webhook_on_failed_false` | `status=failed`, toggle wyłączony → skip |
| `test_sends_on_done_when_enabled` | Mock post → assert `called_once`, zwraca `True` |
| `test_sends_on_failed_when_enabled` | Mock post → assert `called_once`, zwraca `True` |
| `test_raises_on_non_2xx` | `raise_for_status` rzuca `HTTPError` → propaguje |
| `test_raises_on_timeout` | `requests.post` rzuca `Timeout` → propaguje |
| `test_payload_contains_expected_fields` | Weryfikuje klucze JSON w payloadzie |

### `services/web/apps/accounts/tests/test_views.py` — nowa klasa `TestTestWebhookView`

| Test | Opis |
|------|------|
| `test_requires_login` | Anonimowy → redirect 302 |
| `test_returns_ok_on_success` | Mock `requests.post` 200 → `{"ok": true}` |
| `test_returns_error_on_connection_refused` | Mock rzuca `ConnectionError` → `{"ok": false}` |
| `test_returns_error_on_missing_url` | Pusty `webhook_url` → `{"ok": false}` |

## Zależności

- `requests` — **dodać do `services/worker/requirements.txt`** (brakuje, używane przez `send_webhook_notification`)
- `requests` — **dodać do `services/web/requirements.txt`** (endpoint testowy w widoku Django)

## Wdrożenie

```bash
docker compose run --rm web python manage.py migrate
# Restart nie jest wymagany dla worker/beat — nowy task jest wykrywany automatycznie
docker compose restart worker beat
```
