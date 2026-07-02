# HTTPS (nginx + self-signed cert) — Design

**Data:** 2026-07-02
**Status:** zatwierdzony

## Cel

Szyfrować cały ruch do tmask-transporter. Dziś nginx nasłuchuje wyłącznie na porcie 80 (`server_name _`), bez żadnej domeny — aplikacja jest dostępna tylko lokalnie/w LAN, bez wystawienia na internet. Ten spec dodaje HTTPS na tym samym poziomie (self-signed cert), świadomie zostawiając docelową architekturę (reverse proxy manager z prawdziwym certyfikatem) na później.

## Kontekst obecny

- `nginx/nginx.conf` — jeden `server` blok, `listen 80`, `server_name _`, nagłówki bezpieczeństwa (CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy) już ustawione, `proxy_pass http://web:8000` z `X-Forwarded-Proto $scheme`.
- `docker-compose.yml` — serwis `nginx` publikuje tylko `"80:80"`.
- Django (`services/web/config/settings/base.py`) — brak `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE`/`SECURE_PROXY_SSL_HEADER`.
- Brak jakiejkolwiek domeny publicznej — Let's Encrypt odrzucony (wymaga publicznie rozwiązywalnej domeny + dostępności portu 80/443 z internetu na ACME challenge).

## Decyzje (zatwierdzone)

1. **Self-signed certyfikat, długi termin ważności (10 lat)** — generowany raz, ręcznie, poza cyklem życia kontenerów (nie w entrypoincie nginx — uniknięcie regeneracji przy każdym restarcie).
2. **SAN certyfikatu**: `tmask-transporter.local`, `localhost`, `127.0.0.1`. Użytkownik świadomie akceptuje ostrzeżenie przeglądarki o niezaufanym CA — priorytet to szyfrowanie transportu, nie eliminacja ostrzeżenia (por. decyzja #5).
3. **HTTP (port 80) przekierowuje 301 na HTTPS** — stare zakładki/linki nadal działają (z przeskokiem), zamiast twardego zamknięcia portu.
4. **Django**: `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`, `SECURE_PROXY_SSL_HEADER` ustawione (nginx już wysyła `X-Forwarded-Proto`). **Bez** `SECURE_SSL_REDIRECT` w Django (redirect robi nginx — unikamy podwójnego przekierowania przy przyszłym reverse proxy) i **bez** HSTS (cert się zmieni przy przyszłej integracji z NPM/Traefik — HSTS z niezaufanym self-signed certem to zbędne ryzyko lockoutu).
5. **Poza zakresem, celowo**: integracja z Nginx Proxy Manager / Traefik, Let's Encrypt, automatyczne odnawianie certyfikatu — użytkownik dokona tego sam w kolejnym etapie. Ten spec dostarcza wyłącznie szyfrowany transport na obecnym poziomie infrastruktury.

## Architektura zmian

### 1. Generowanie certyfikatu (ręczny, jednorazowy krok — dokumentacja, nie kod)

```bash
mkdir -p nginx/certs
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout nginx/certs/selfsigned.key -out nginx/certs/selfsigned.crt \
  -days 3650 -subj "/CN=tmask-transporter.local" \
  -addext "subjectAltName=DNS:tmask-transporter.local,DNS:localhost,IP:127.0.0.1"
```

Instrukcja trafia do `README.md` (sekcja instalacji) i `Wdrożenie` w dokumentacji projektu.

### 2. `.gitignore`

Dodać `nginx/certs/` — klucz prywatny nigdy nie trafia do repo.

### 3. `nginx/nginx.conf`

Restrukturyzacja z jednego `server` bloku na dwa:

```nginx
server {
    listen 80;
    server_name _;
    server_tokens off;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name _;
    server_tokens off;

    ssl_certificate     /etc/nginx/certs/selfsigned.crt;
    ssl_certificate_key /etc/nginx/certs/selfsigned.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    client_max_body_size 100m;

    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; form-action 'self'; base-uri 'self'; object-src 'none';" always;

    resolver 127.0.0.11 valid=10s;

    location /static/ {
        alias /app/staticfiles/;
    }

    location / {
        set $upstream http://web:8000;
        proxy_pass $upstream;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Wszystkie nagłówki bezpieczeństwa i `location` bloki przenoszą się z obecnego bloku 1:1 do nowego bloku 443 — zero zmian w ich treści, tylko przeniesienie.

### 4. `docker-compose.yml`

Serwis `nginx`:
```yaml
  nginx:
    image: nginx:stable-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf
      - ./nginx/certs:/etc/nginx/certs:ro
      - static_files:/app/staticfiles
    depends_on:
      - web
    networks:
      - internal
    restart: unless-stopped
```
(dodane: port `443:443`, wolumen `./nginx/certs:/etc/nginx/certs:ro`).

### 5. `services/web/config/settings/base.py`

Dodać (obok istniejących ustawień bezpieczeństwa):
```python
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
```

**Uwaga na `config/settings/testing.py` i `development.py`**: jeśli dziedziczą z `base.py` przez `from .base import *`, `SESSION_COOKIE_SECURE=True` może przeszkadzać w testach klienta Django (test client domyślnie nie symuluje HTTPS, więc ciasteczka `Secure` mogą nie być odsyłane w kolejnych żądaniach testowych, jeśli test polega na trwałości sesji między żądaniami). Plan implementacji musi to zweryfikować przy pierwszym uruchomieniu pełnego suite'u i, jeśli trzeba, nadpisać `SESSION_COOKIE_SECURE=False`/`CSRF_COOKIE_SECURE=False` w `testing.py` (test client i tak nie używa realnego TLS).

## Obsługa błędów

| Sytuacja | Zachowanie |
|----------|-----------|
| Użytkownik wchodzi na `http://tmask-transporter.local` | 301 → `https://tmask-transporter.local` |
| Przeglądarka nie ufa self-signed CA | Standardowe ostrzeżenie przeglądarki — użytkownik klika "Zaawansowane → Kontynuuj" (świadomie zaakceptowane, decyzja #2) |
| Brak wpisu `tmask-transporter.local` w `/etc/hosts` klienta | DNS nie rozwiąże nazwy — użytkownik musi dodać wpis ręcznie (dokumentacja) lub użyć `https://localhost`/`https://127.0.0.1` (też w SAN) |
| Kontener nginx startuje bez wygenerowanego certu (`nginx/certs/` puste) | nginx nie wystartuje (`ssl_certificate` wskazuje na nieistniejący plik) — błąd czytelny w `docker compose logs nginx`, dokumentacja jasno wymaga wygenerowania certu przed pierwszym `docker compose up` |

## Testy

- Test ustawień Django: `SESSION_COOKIE_SECURE is True`, `CSRF_COOKIE_SECURE is True`, `SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https')` w `production.py`/`base.py`
- **Regresja**: pełny suite `pytest apps/` musi pozostać zielony po zmianie cookie flags — jeśli `testing.py` wymaga nadpisania flag (patrz uwaga w sekcji 5), test to potwierdzi
- **Manualna weryfikacja** (jak przy poprzednich funkcjach tego projektu — brak automatyzacji dla samej warstwy nginx/TLS):
  - `curl -I http://localhost` → `301` z `Location: https://...`
  - `curl -Ik https://localhost` → `200`, nagłówki bezpieczeństwa obecne
  - `openssl s_client -connect localhost:443 -servername tmask-transporter.local </dev/null 2>/dev/null | openssl x509 -noout -dates -subject` → potwierdzenie SAN i daty ważności

## Poza zakresem

- Nginx Proxy Manager / Traefik — kolejny etap, poza tym spec (decyzja #5)
- Let's Encrypt / automatyczne odnawianie — wymaga publicznej domeny, nie dotyczy obecnej architektury
- HSTS — odłożone do czasu zaufanego certyfikatu (decyzja #4)
- Wymuszenie TLS 1.3-only (zostaje TLS 1.2 + 1.3 dla kompatybilności wstecznej)
