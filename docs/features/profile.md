# Profil — Ustawienia użytkownika

> Zarządzanie tokenami API, powiadomieniami webhook i ustawieniami konta.

## Dostęp

Panel → ikona użytkownika → `[ PROFILE ]` lub `/accounts/profile/`

---

## API Tokens

Tokeny umożliwiające wywoływanie transferów z zewnętrznych skryptów i CI pipeline bez logowania do panelu.

### Generowanie tokenu

1. W sekcji `[ API TOKENS ]` wpisz etykietę (opis), np. `CI/CD pipeline`
2. Kliknij `[ GENERATE ]`
3. **Token wyświetlany jest jednorazowo** — skopiuj go natychmiast (nie da się odczytać ponownie)
4. Limit: maksymalnie **5 aktywnych tokenów** per użytkownik

### Używanie tokenu — nagłówek Authorization

```bash
# Wyzwolenie transferu przez Connection
curl -X POST http://localhost/api/transfers/trigger/connection/1/ \
     -H "Authorization: Token <twoj-token>"

# Wyzwolenie transferu przez Flow
curl -X POST http://localhost/api/transfers/trigger/flow/1/ \
     -H "Authorization: Token <twoj-token>"

# Sprawdzenie statusu zadania
curl http://localhost/api/jobs/42/status/ \
     -H "Authorization: Token <twoj-token>"
```

### Format odpowiedzi API

```json
// Trigger — sukces
{"job_id": 42}

// Status zadania
{
  "job_id": 42,
  "status": "DONE",
  "source_path": "/transfers/plik.tar",
  "destination_path": "/backup/plik.tar"
}
```

### Cofanie tokenu

W tabeli tokenów kliknij `[ REVOKE ]` → potwierdzenie → token usunięty.

### Bezpieczeństwo tokenów

- Baza danych przechowuje wyłącznie **SHA-256 hash** tokenu — raw key nigdy nie jest persystowany
- Token wyświetlany jednorazowo przez sesję — po zamknięciu modalu nie ma możliwości odczytu
- Każde żądanie API wymaga własności zasobu (owner check) — token użytkownika A nie może triggerować zasobów użytkownika B

---

## Webhook

Powiadomienia HTTP POST wysyłane automatycznie po zakończeniu lub błędzie transferu.

### Konfiguracja

| Pole                  | Opis                                                          |
|-----------------------|---------------------------------------------------------------|
| **WEBHOOK URL**       | Adres odbiorcy, np. `https://hooks.slack.com/...` lub n8n     |
| **WEBHOOK ON DONE**   | Wyślij gdy transfer zakończony sukcesem                       |
| **WEBHOOK ON FAILED** | Wyślij gdy transfer zakończony błędem                         |

Przycisk `[ TEST ]` wysyła testowy payload i pokazuje wynik inline.

### Format payloadu

```json
{
    "job_id": 42,
    "status": "DONE",
    "source_path": "/transfers/plik.tar",
    "destination_path": "/backup/plik.tar",
    "connection": "SRV-PROD (SFTP)",
    "started_at": "2026-05-28T10:15:01Z",
    "finished_at": "2026-05-28T10:15:03Z",
    "error": null
}
```

Relay (Flow): `"connection": "RELAY: NazwaFlow"`.

### Retry

Webhook wysyłany przez Celery task `transfers.send_webhook` (bind=True, max_retries=3, retry_delay=60s).  
Przy błędzie HTTP task jest automatycznie ponawiane 3 razy co minutę.

---

## Powiadomienia e-mail

| Pole                  | Opis                                        |
|-----------------------|---------------------------------------------|
| **NOTIFY ON DONE**    | E-mail po udanym transferze                 |
| **NOTIFY ON FAILED**  | E-mail po błędnym transferze                |

Wymaga skonfigurowanego serwera SMTP w `.env` (`EMAIL_*`).

---

## Kod źródłowy

| Zasób               | Ścieżka                                                  |
|---------------------|----------------------------------------------------------|
| Model User          | `services/web/apps/accounts/models.py`                   |
| ProfileForm         | `services/web/apps/accounts/forms.py`                    |
| Widoki profilu      | `services/web/apps/accounts/views.py`                    |
| ApiToken model      | `services/web/apps/api/models.py`                        |
| API auth decorator  | `services/web/apps/api/auth.py` — `@require_api_token`   |
| API widoki          | `services/web/apps/api/views.py`                         |
| Webhook task        | `services/worker/tasks.py` — `send_webhook`              |
| Testy API           | `services/web/apps/api/tests/`                           |
