# REST API dla zewnętrznych triggerów — Design Spec

**Data:** 2026-05-26
**Projekt:** tmask-transporter
**Status:** Zatwierdzony

---

## Cel

Umożliwienie uruchamiania transferów (Connection i Flow) z zewnętrznych skryptów, CI pipeline lub narzędzi automatyzacji bez konieczności logowania do panelu webowego. Autoryzacja przez statyczny token API per-user generowany w panelu.

---

## Architektura

Nowa izolowana app Django `apps/api/` — nie dotyka istniejących app.

```
apps/api/
├── models.py        # ApiToken
├── auth.py          # get_user_from_token(), @require_api_token decorator
├── views.py         # trigger_connection, trigger_flow, job_status
├── urls.py          # /api/...
├── migrations/
└── tests/
    ├── test_auth.py
    ├── test_trigger.py
    └── test_status.py
```

Rejestracja w `config/urls.py`:
```python
path('api/', include('apps.api.urls')),
```

---

## Model danych

```python
# apps/api/models.py
class ApiToken(models.Model):
    user         = ForeignKey(settings.AUTH_USER_MODEL, on_delete=CASCADE, related_name='api_tokens')
    label        = CharField(max_length=100)       # np. "CI Jenkins", "script produkcja"
    key_hash     = CharField(max_length=64)        # SHA-256(raw_key), hex, unikalny
    created_at   = DateTimeField(auto_now_add=True)
    last_used_at = DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
```

**Generowanie tokenu:**
- `raw_key = secrets.token_hex(32)` → 64-znakowy string
- `key_hash = hashlib.sha256(raw_key.encode()).hexdigest()`
- Raw key pokazywany użytkownikowi **tylko raz** (w modal po wygenerowaniu)
- DB przechowuje wyłącznie `key_hash`
- Limit: max 5 tokenów per user

**Revoke:** usunięcie rekordu `ApiToken`.

---

## Endpointy API

### Trigger transferu przez Connection

```
POST /api/transfers/trigger/connection/<connection_id>/
Authorization: Token <raw_key>
Content-Type: application/json

{
  "source_path": "/local/file.tar",
  "destination_path": "/remote/backups/"
}
```

Odpowiedź `202 Accepted`:
```json
{"job_id": 42}
```

Walidacja:
- `connection_id` musi należeć do właściciela tokenu (`connection.owner == token.user`)
- `source_path` i `destination_path` wymagane, niepuste stringi
- Błąd `404` gdy Connection nie istnieje lub nie należy do usera
- Błąd `400 {"error": "source_path required"}` gdy brak pól

### Trigger transferu przez Flow

```
POST /api/transfers/trigger/flow/<flow_id>/
Authorization: Token <raw_key>
Content-Type: application/json

{}
```

Odpowiedź `202 Accepted`:
```json
{"job_id": 43}
```

Ścieżki (`source_path`, `dest_path`) pobierane z modelu `Flow`. Body może być puste.

### Status joba

```
GET /api/jobs/<job_id>/status/
Authorization: Token <raw_key>
```

Odpowiedź `200 OK`:
```json
{
  "job_id": 43,
  "status": "done",
  "started_at": "2026-05-26T14:32:10Z",
  "finished_at": "2026-05-26T14:32:45Z",
  "error": null
}
```

`status` to jedna z wartości: `pending`, `running`, `done`, `failed`.
Zwraca `404` gdy job nie istnieje lub nie należy do właściciela tokenu.

### Kody błędów

| Kod | Sytuacja |
|-----|----------|
| 400 | Brak wymaganych pól w body |
| 403 | Brak nagłówka `Authorization` lub nieprawidłowy token |
| 404 | Zasób nie istnieje lub nie należy do usera tokenu |
| 405 | Zły method (GET zamiast POST) |

---

## Autoryzacja: `@require_api_token`

```python
# apps/api/auth.py
def get_user_from_token(request) -> User | None:
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
```

Dekorator wstrzykuje `request.api_user` — widoki używają go zamiast `request.user`.

---

## Zarządzanie tokenami w UI

Sekcja `[ API TOKENS ]` w profilu użytkownika (`/accounts/profile/`), spójna z CRT stylem.

**Widok listy:**
- Tabela: label | created_at | last_used_at | [REVOKE]
- Przycisk `[GENERATE NEW TOKEN]`
- Komunikat gdy limit 5 tokenów osiągnięty

**Generowanie tokenu:**
1. Formularz z polem `label` (max 100 znaków)
2. POST → generuje `raw_key`, tworzy `ApiToken`, zwraca `raw_key` w odpowiedzi
3. Modal CRT style z raw key, przycisk `[COPY]` (JS clipboard)
4. Komunikat: "Zapisz ten klucz — nie zostanie pokazany ponownie"

**Revoke:**
- POST `/accounts/api-tokens/<token_id>/revoke/` → usunięcie tokenu → redirect z komunikatem

Endpointy UI (generate, revoke) obsługiwane przez `apps/accounts/` — rozszerzenie istniejącej app profilu. Logika generowania tokenu (raw key, hash) w `apps/api/models.py`. Widoki UI w `apps/accounts/views.py`, URLs w `apps/accounts/urls.py`.

---

## Przepływ danych

```
Skrypt zewnętrzny
  → POST /api/transfers/trigger/connection/5/
  → @require_api_token: SHA-256(key) → szuka ApiToken → token.user
  → sprawdź connection.owner == token.user
  → utwórz TransferJob (owner=token.user)
  → execute_transfer.delay(job_id=job.pk)
  → 202 {"job_id": 42}

Skrypt zewnętrzny (polling)
  → GET /api/jobs/42/status/
  → @require_api_token
  → sprawdź job.owner == token.user
  → 200 {"status": "done", ...}
```

---

## Testy (TDD)

### test_auth.py
- Token poprawny → `request.api_user` ustawiony, `last_used_at` zaktualizowany
- Brak nagłówka → 403
- Niepoprawny klucz → 403
- Cudzysłów/spacje w tokenie → 403

### test_trigger.py
- Trigger Connection: poprawny token + dane → 202, job w DB, Celery task wywołany
- Trigger Connection: cudzy connection → 404
- Trigger Connection: brak `source_path` → 400
- Trigger Flow: poprawny token → 202, job z flow FK
- Trigger Flow: cudzy flow → 404

### test_status.py
- Własny job → 200 z poprawnymi polami
- Cudzy job → 404
- Nieistniejący job → 404

### test_token_management.py (w accounts lub api)
- Generowanie tokenu: raw key w odpowiedzi, hash w DB
- Limit 5 tokenów: przy 6. → błąd
- Revoke: token usunięty, kolejny request → 403

---

## Bezpieczeństwo

- DB przechowuje wyłącznie SHA-256 hash — wyciek DB nie ujawnia tokenów
- `select_related('user')` na `ApiToken` — jeden query przy auth
- Owner check na każdym zasobie — brak możliwości eskalacji
- `last_used_at` w UTC — audytowanie bez logowania sesji
- Brak logowania raw key — nawet w Django logs
- Limit 5 tokenów per user — prosta ochrona przed proliferacją

---

## Powiązane specyfikacje

- `2026-05-20-tmask-transporter-design.md` — projekt bazowy
- `2026-05-21-relay-flows-design.md` — Flow model używany przez trigger_flow
- `2026-05-25-webhook-notifications-design.md` — analogiczny wzorzec (send_webhook task)
