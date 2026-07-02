# 2FA TOTP (opcjonalne, w profilu) — Design

**Data:** 2026-07-02
**Status:** zatwierdzony

## Cel

Dodać opcjonalne dwuskładnikowe uwierzytelnianie (TOTP — Time-based One-Time Password, RFC 6238) dla loginu sesyjnego. Każdy użytkownik może samodzielnie włączyć/wyłączyć 2FA w swoim profilu. Brak wymuszania 2FA dla żadnej roli — w pełni opt-in per-user.

## Kontekst obecny

- `apps/accounts/models.py` — custom `User(AbstractUser)` z rolami (`admin`/`operator`/`readonly`), bez żadnych pól 2FA.
- `apps/accounts/views.py::login_view` — prosty jednoetapowy login: `authenticate()` + `login()`.
- `apps/accounts/views.py::profile_view` — profil edytowalny przez `ProfileForm` (email, powiadomienia email/webhook/Telegram).
- `apps/connections/models.py` — wzorzec przechowywania sekretów: `EncryptedCharField`/`EncryptedTextField` z `django-encrypted-model-fields` (już w `requirements.txt`).
- Brak w projekcie żadnej biblioteki TOTP/QR — trzeba dodać `pyotp` i `qrcode[pil]`.
- API tokeny (`apps/api/models.py::ApiToken`) to osobny mechanizm auth, nieużywający loginu sesyjnego — poza zakresem tego spec.

## Decyzje (zatwierdzone)

1. **Biblioteki**: `pyotp` (generowanie/weryfikacja TOTP) + `qrcode[pil]` (QR kod z `otpauth://` URI). Odrzucono `django-otp` — zbyt ciężki dla już niestandardowego custom `User`/`login_view`/`permissions.py`; własna implementacja prostsza do zintegrowania i przetestowania, spójna ze stylem projektu (RBAC/webhooks też zbudowane samodzielnie).
2. **Setup flow**: QR kod + kod potwierdzający (nie sam tekstowy sekret) — najwygodniejsze dla użytkownika.
3. **Login flow**: dwuetapowy — hasło poprawne → osobna strona z polem na kod TOTP (sesja pre-auth) → dopiero poprawny kod loguje w pełni.
4. **Recovery**: kody zapasowe (10 szt., jednorazowe, pokazane raz przy włączaniu 2FA, przechowywane jako hash). Brak admin-override do wyłączania cudzego 2FA (poza zakresem — jedyna ścieżka odzyskania to kody zapasowe).
5. **Rate limiting**: limit 5 błędnych prób kodu TOTP na sesję pre-auth — po przekroczeniu sesja pre-auth czyszczona, user wraca do loginu hasłem. Licznik trzymany w `request.session`, nie w bazie.
6. **Poza zakresem, celowo**: reset/wyłączenie 2FA przez admina dla zablokowanego usera, "zapamiętaj to urządzenie" (trusted devices), wymuszanie 2FA per rola, wpływ na API tokeny (bez zmian, osobny mechanizm).

## Architektura zmian

### 1. Model danych (`apps/accounts/models.py`)

Nowe pola na `User`:
```python
totp_secret  = EncryptedCharField(max_length=64, blank=True, default='')
totp_enabled = models.BooleanField(default=False)
```

Nowy model:
```python
class TOTPRecoveryCode(models.Model):
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recovery_codes')
    code_hash  = models.CharField(max_length=128)
    used_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```
Format kodu — kanoniczna postać `XXXX-XXXX` (8 wielkich znaków hex + myślnik po 4.): `secrets.token_hex(4).upper()` da 8 znaków hex (`0-9A-F`), wstawić myślnik po 4. znaku. Ta kanoniczna postać ze myślnikiem jest tym, co się hashuje (`make_password`) i tym, co się pokazuje userowi. Przy weryfikacji: wejście usera znormalizować do tej samej postaci przed `check_password` — `strip()`, `upper()`, usunąć wszystkie istniejące myślniki, wstawić dokładnie jeden po 4. znaku (akceptuje więc zarówno wklejenie z myślnikiem jak i bez).

### 2. Setup flow (`apps/accounts/views.py`, nowe URL-e pod `/accounts/2fa/`)

- `GET /accounts/2fa/setup/` — jeśli `request.user.totp_enabled` już `True`, redirect do profilu z komunikatem. Inaczej: generuje nowy `pyotp.random_base32()`, zapisuje **tymczasowo w sesji** (`request.session['pending_totp_secret']`), renderuje QR (`pyotp.totp.TOTP(secret).provisioning_uri(name=user.username, issuer_name='tmask-transporter')` → `qrcode` → PNG jako base64 inline `<img>`) + formularz na 6-cyfrowy kod potwierdzający.
- `POST /accounts/2fa/setup/` — weryfikuje kod przeciw sekretowi z sesji (`pyotp.TOTP(secret).verify(code, valid_window=1)`). Sukces: zapisuje `totp_secret`+`totp_enabled=True` na `request.user`, usuwa `pending_totp_secret` z sesji, generuje 10 `TOTPRecoveryCode`, zapisuje plaintext kody **tylko w sesji** (`request.session['new_recovery_codes']`, jednorazowy odczyt jak istniejący wzorzec `new_api_token`), redirect do `GET /accounts/2fa/recovery-codes/`. Błąd: formularz z błędem, sekret w sesji zostaje (user może spróbować ponownie bez re-skanowania QR).
- `GET /accounts/2fa/recovery-codes/` — pop `new_recovery_codes` z sesji (jak `new_api_token` we `profile_view`), renderuje listę do zapisania offline. Wejście bez świeżo wygenerowanych kodów w sesji → redirect do profilu.
- `POST /accounts/2fa/disable/` — wymaga pola `password` w body, weryfikowanego `request.user.check_password()`. Sukces: `totp_secret=''`, `totp_enabled=False`, kasuje wszystkie `TOTPRecoveryCode` usera. Błędne hasło: redirect do profilu z komunikatem błędu.

### 3. Login flow (`apps/accounts/views.py::login_view` + nowy widok)

`login_view` — po `authenticate()` zwracającym usera:
```python
if user.totp_enabled:
    request.session['pre_2fa_user_id'] = user.id
    request.session['pre_2fa_attempts'] = 0
    next_url = request.GET.get('next', '')
    if next_url:
        request.session['pre_2fa_next'] = next_url
    return redirect('accounts:2fa_verify')
login(request, user)
# ... istniejący redirect logic bez zmian
```

Nowy widok `GET/POST /accounts/2fa/verify/`:
- Brak `pre_2fa_user_id` w sesji → redirect do `accounts:login`.
- `POST` z polem `code`:
  1. Pobiera usera po `pre_2fa_user_id`.
  2. `pyotp.TOTP(user.totp_secret).verify(code, valid_window=1)` → sukces: `login(request, user)`, czyści `pre_2fa_*` z sesji, redirect na `pre_2fa_next` (walidowany `url_has_allowed_host_and_scheme` jak istniejący `next` handling) lub `LOGIN_REDIRECT_URL`.
  3. Jeśli krok 2 nie pasuje: sprawdza nieużyte `TOTPRecoveryCode` usera przez `check_password(code, code_hash)` — pasujący kod: oznacza `used_at=now()`, loguje, komunikat z liczbą pozostałych kodów.
  4. Nic nie pasuje: `pre_2fa_attempts += 1` w sesji. Przy `>= 5`: czyści całą sesję pre-auth, redirect do `accounts:login` z komunikatem. Inaczej: formularz z błędem, sesja pre-auth zostaje.

### 4. Profil (`templates/accounts/profile.html`, `apps/accounts/views.py::profile_view`)

Nowa sekcja "Weryfikacja dwuskładnikowa (2FA)":
- `totp_enabled=False`: przycisk `[ WŁĄCZ 2FA ]` → `accounts:2fa_setup`
- `totp_enabled=True`: status "2FA: włączone" + formularz `[ WYŁĄCZ 2FA ]` z polem na hasło → `accounts:2fa_disable`

### 5. URL-e (`apps/accounts/urls.py`)

```python
path('2fa/setup/', views.totp_setup, name='2fa_setup'),
path('2fa/recovery-codes/', views.totp_recovery_codes, name='2fa_recovery_codes'),
path('2fa/disable/', views.totp_disable, name='2fa_disable'),
path('2fa/verify/', views.totp_verify, name='2fa_verify'),
```

### 6. Zależności (`requirements.txt`)

```
pyotp==2.*
qrcode[pil]==8.*
```

## Obsługa błędów

| Sytuacja | Zachowanie |
|----------|-----------|
| Sesja Django wygasa w trakcie etapu 2 logowania | Brak `pre_2fa_user_id` → redirect do loginu (traktowane identycznie jak nieautoryzowany dostęp do `/2fa/verify/`) |
| User wchodzi na `/accounts/2fa/setup/` mając już 2FA włączone | Redirect do profilu z komunikatem — brak przypadkowego nadpisania działającego sekretu |
| Użyty kod zapasowy użyty ponownie | Odrzucony (`used_at` niepuste wyklucza go z zapytania) |
| Wyłączenie i ponowne włączenie 2FA | Nowy `totp_secret`, nowy komplet 10 kodów zapasowych, stare (jeśli jakimś trafem przetrwałyby) nie mają zastosowania — `totp_disable` kasuje cały `recovery_codes` set |
| 5 błędnych prób kodu TOTP/zapasowego z rzędu | Sesja pre-auth (`pre_2fa_*`) czyszczona, user wraca do loginu hasłem |
| API tokeny | Bez zmian — 2FA nie dotyczy `apps/api` |

## Testy

- **Model**: `TOTPRecoveryCode` — generowanie, hashowanie, jednorazowość (użyty kod nie przechodzi drugi raz)
- **Setup flow**: QR renderuje się poprawnie (provisioning URI zawiera username+issuer), błędny kod potwierdzający nie włącza 2FA, poprawny kod włącza `totp_enabled` + generuje dokładnie 10 kodów zapasowych, powtórne wejście na setup przy `totp_enabled=True` przekierowuje
- **Login flow — regresja**: user bez 2FA loguje się dokładnie jak dotychczas (test istniejący musi dalej przechodzić)
- **Login flow — z 2FA**: poprawne hasło samo nie loguje (sesja pozostaje anonimowa), poprawny kod TOTP loguje, poprawny kod zapasowy loguje i oznacza się jako zużyty, zużyty kod zapasowy odrzucony przy kolejnej próbie, 5. błędna próba czyści sesję pre-auth i wymusza ponowny login hasłem, brak `pre_2fa_user_id` w sesji przy wejściu na `/2fa/verify/` przekierowuje do loginu
- **Wyłączanie 2FA**: błędne hasło nie wyłącza, poprawne hasło kasuje sekret i wszystkie kody zapasowe

## Poza zakresem

- Reset/wyłączenie 2FA przez admina dla zablokowanego usera (decyzja #4)
- "Zapamiętaj to urządzenie" / trusted devices
- Wymuszanie 2FA dla konkretnej roli (np. obowiązkowe dla Admina)
- Wpływ na uwierzytelnianie API tokenami (`apps/api`) — pozostaje bez zmian
