---
name: security-check
description: Szybki audyt bezpieczeństwa przed commitem — owner filtering, EncryptedField, shlex.quote, sekrety.
allowed-tools: [Bash, Read]
---

Uruchom przed każdym commitem jako sub agent, zawierającym nowe widoki, modele lub handlery transferu.

## 1. Sekrety nie trafiają do repozytorium

```bash
# .env poza gitem
git status --short | grep "\.env" && echo "BŁĄD — .env widoczny" || echo "OK"

# Brak hardkodowanych tokenów/kluczy w nowym kodzie
git diff --cached | grep -iE "(secret_key|password|fernet|api_key)\s*=\s*['\"][^'\"]+" \
  && echo "BŁĄD — hardkodowany sekret w diff" || echo "OK"
```

## 2. DEBUG=False w ustawieniach produkcyjnych

```bash
grep "DEBUG" services/web/config/settings/production.py
# Musi być: DEBUG = False lub DEBUG = config('DEBUG', default=False, cast=bool)

grep "setdefault.*DJANGO_SETTINGS_MODULE" services/web/config/celery.py
# Musi wskazywać na: config.settings.production
```

## 3. Izolacja użytkowników — owner filtering w nowych widokach

Każde nowe view które zwraca dane użytkownika musi filtrować po `owner=request.user`.

```bash
# Znajdź nowe widoki w staged plikach
git diff --cached --name-only | grep "views\.py" | xargs grep -l "def get_queryset\|objects\.all\|objects\.filter" 2>/dev/null
```

Ręcznie sprawdź że każde `objects.filter()` zawiera `owner=request.user`, np.:

```python
# Dobrze
Connection.objects.filter(owner=request.user)

# Źle — zwraca dane wszystkich użytkowników
Connection.objects.all()
Connection.objects.filter(host=host)  # bez owner=
```

## 4. Szyfrowanie wrażliwych pól w nowych modelach

Jeśli nowy model przechowuje hasła, klucze SSH, tokeny lub inne sekrety:

```bash
git diff --cached -- "*.py" | grep -E "password|ssh_key|token|secret" | grep "CharField\|TextField"
# Jeśli wynik niepusty — upewnij się że używasz EncryptedCharField / EncryptedTextField
```

Wymagany import:
```python
from encrypted_model_fields.fields import EncryptedCharField, EncryptedTextField
```

## 5. Bezpieczeństwo subprocess / shell injection

Dla każdego nowego kodu korzystającego z subprocess lub budującego komendy SSH:

```bash
git diff --cached -- "*.py" | grep -E "subprocess|Popen|os\.system|ssh_key"
```

Wzorzec bezpieczny (z `services/worker/modules/rsync/handler.py`):
```python
# Ścieżka klucza SSH — zawsze shlex.quote()
ssh_key_arg = shlex.quote(str(self.params['ssh_key']))

# Komenda jako lista (nie string) — subprocess nie uruchamia shella
cmd = ['rsync', '-az', '--rsh', f'ssh -i {ssh_key_arg}', src, dst]
subprocess.run(cmd, ...)  # NIE subprocess.run(' '.join(cmd), shell=True)
```

## 6. CSRF i formularze POST

```bash
# Każdy nowy szablon z formularzem POST musi mieć {% csrf_token %}
git diff --cached --name-only | grep "\.html" | xargs grep -L "csrf_token" 2>/dev/null \
  | xargs grep -l "method.*post\|method.*POST" 2>/dev/null \
  && echo "BŁĄD — formularz POST bez csrf_token" || echo "OK"
```

## 7. Non-root w nowych Dockerfile'ach

Jeśli modyfikujesz lub dodajesz Dockerfile:

```bash
git diff --cached -- "*Dockerfile" | grep -E "USER|useradd|adduser"
# Musi być USER nieroot przed CMD/ENTRYPOINT
```

## Szybki przegląd całości

```bash
echo "=== Sekrety ===" && git diff --cached | grep -iE "password\s*=\s*['\"].+" || echo "OK"
echo "=== DEBUG ===" && grep "DEBUG = True" services/web/config/settings/production.py || echo "OK"
echo "=== .env ===" && git status --short | grep "\.env$" || echo "OK"
echo "=== CSRF ===" && git diff --cached --name-only | grep "\.html$" | xargs grep -rL "csrf_token" 2>/dev/null | xargs grep -l "POST" 2>/dev/null || echo "OK"
```
