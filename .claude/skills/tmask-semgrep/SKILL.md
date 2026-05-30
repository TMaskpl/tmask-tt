---
name: tmask-semgrep
description: Skan SAST kodu Python przez Semgrep (reguły python + django + security-audit). Wykrywa wzorce bezpieczeństwa specyficzne dla Django. Uzupełnia bandit — inne reguły, inne false positives.
---

# Skill: tmask-semgrep

Przeprowadza statyczny skan bezpieczeństwa kodu źródłowego projektu przez Semgrep
(reguły `p/python`, `p/django`, `p/security-audit`).

## Konfiguracja — dostosuj przed użyciem

> Zamień `{{CODE_DIR}}` na bezwzględną ścieżkę do katalogu projektu

| Zmienna | Opis | Przykład |
|---------|------|---------|
| `CODE_DIR` | Bezwzględna ścieżka do projektu | `/home/user/tmask-tt` |

## Wymagania

| Narzędzie | Instalacja | Weryfikacja |
|-----------|-----------|-------------|
| Semgrep CLI ≥ 1.146.0 | `brew install semgrep` (macOS) lub `pip install semgrep` | `semgrep --version` |

Semgrep działa bez konta (tryb Community) dla reguł `p/*` — nie wymaga `semgrep login`.

---

## Krok 1 — Sprawdź instalację Semgrep

```bash
which semgrep && semgrep --version
```

Jeśli niedostępny:
```bash
# macOS
brew install semgrep

# Linux / inne
pip install semgrep
```

---

## Krok 2 — Uruchom skan

```bash
cd {{CODE_DIR}} && \
semgrep scan \
  --config "p/python" \
  --config "p/django" \
  --config "p/security-audit" \
  --include="*.py" \
  --exclude="migrations" \
  --exclude="*.pyc" \
  --json \
  --output=/tmp/semgrep-tmask-$(date +%Y-%m-%d).json \
  services/
```

Semgrep wypisze podsumowanie: liczba reguł, pliki, znaleziska.

---

## Krok 3 — Przeanalizuj wyniki

```bash
python3 -c "
import json
d = json.load(open('/tmp/semgrep-tmask-$(date +%Y-%m-%d).json'))
results = d.get('results', [])
print(f'Znalezisk: {len(results)}')
for r in results:
    sev = r.get('extra', {}).get('severity', '?')
    msg = r.get('extra', {}).get('message', '')[:120]
    path = r.get('path', '?')
    start = r.get('start', {}).get('line', '?')
    rule = r.get('check_id', '?')
    print(f'[{sev}] {path}:{start}')
    print(f'  Reguła: {rule}')
    print(f'  Opis: {msg}')
    print()
"
```

### Severity w Semgrep

| Poziom | Znaczenie |
|--------|-----------|
| `ERROR` | Krytyczne — wymaga naprawy przed commitem |
| `WARNING` | Do analizy — może być false positive |
| `INFO` | Informacyjne — niskie ryzyko |

---

## Znane false positives w tmask-transporter

| Reguła | Plik | Ocena | Uzasadnienie |
|--------|------|-------|--------------|
| `python.django.security.audit.csrf-exempt.no-csrf-exempt` | `apps/api/views.py:17` i `:55` | FALSE POSITIVE | REST API z `@require_api_token` — token auth w nagłówku, CSRF nie dotyczy |

---

## Zasady

- **Analizuj każde WARNING** — nie pomijaj automatycznie
- **Aktualizuj tabelę false positives** gdy pojawi się nowy fałszywy alarm
- **Pliki JSON** zapisuj w `/tmp/` — nie commituj
- **Reguły zawsze**: `p/python` + `p/django` + `p/security-audit`
- **Wykluczaj zawsze**: `migrations/`, `*.pyc`
