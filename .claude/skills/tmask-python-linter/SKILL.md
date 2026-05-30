---
name: tmask-python-linter
description: Uruchamia statyczną analizę kodu Python (ruff + bandit) przez kontener Docker tmask-python-linter:latest. Wykrywa błędy stylu, import order i podatności bezpieczeństwa. Używaj przed każdym commitem lub po większym refaktorze.
---

# Skill: tmask-python-linter

Uruchamia statyczną analizę kodu Python projektu tmask-transporter za pomocą kontenera
`tmask-python-linter:latest` (ruff + bandit).

## Konfiguracja — dostosuj przed użyciem

> Zamień `{{CODE_DIR}}` na bezwzględną ścieżkę do katalogu projektu, np. `/home/user/tmask-tt`

| Zmienna | Opis | Przykład |
|---------|------|---------|
| `CODE_DIR` | Bezwzględna ścieżka do projektu | `/home/user/tmask-tt` |
| `DOCKER_IMAGE` | Obraz Docker lintera | `tmask-python-linter:latest` |
| `BANDIT_CONFIG` | Plik konfiguracyjny bandit | `${CODE_DIR}/bandit.yaml` |

## Wymagania

| Narzędzie | Instalacja | Weryfikacja |
|-----------|-----------|-------------|
| Docker | https://docs.docker.com/get-docker/ | `docker --version` |
| Obraz Docker | `docker build -t tmask-python-linter:latest ruff_bandit/` | `docker images \| grep tmask-python-linter` |

Obraz bazuje na `ghcr.io/pycqa/bandit/bandit:1.8.0` + ruff (pip). Dockerfile: `ruff_bandit/Dockerfile`.

---

## Krok 1 — Sprawdź obraz Docker

```bash
docker images | grep tmask-python-linter
```

Jeśli obraz nie istnieje — zbuduj go z katalogu projektu:

```bash
docker build -t tmask-python-linter:latest ruff_bandit/
```

---

## Krok 2 — Uruchom Ruff

Ruff sprawdza styl i jakość kodu Python. Entrypoint kontenera to bandit — dla ruff nadpisz przez `--entrypoint ruff`.

```bash
cd {{CODE_DIR}} && \
docker run --rm --entrypoint ruff \
  -v "$(pwd):/code" \
  tmask-python-linter:latest \
  check /code \
  --exclude /code/ruff_bandit \
  --exclude "/code/services/web/apps/*/migrations" \
  --output-format json \
  2>/dev/null > /tmp/ruff-tmask-$(date +%Y-%m-%d).json
```

Przeanalizuj wyniki:

```bash
python3 -c "
import json
results = json.load(open('/tmp/ruff-tmask-$(date +%Y-%m-%d).json'))
print(f'Ruff znalezisk: {len(results)}')
by_code = {}
for r in results:
    code = r.get('code','?')
    by_code[code] = by_code.get(code, 0) + 1
for code, cnt in sorted(by_code.items(), key=lambda x: -x[1]):
    print(f'  {code}: {cnt}')
for r in results:
    code = r.get('code','?')
    msg = r.get('message','?')
    path = r.get('filename','?').replace('/code/','')
    row = r.get('location',{}).get('row','?')
    print(f'[{code}] {path}:{row} — {msg}')
"
```

### Typowe kody ruff

| Kod | Opis |
|-----|------|
| `E402` | Import not at top of file — stała umieszczona między importami |
| `F401` | Unused import |
| `E711` | Comparison to None — użyj `is None` zamiast `== None` |
| `W291` | Trailing whitespace |

---

## Krok 3 — Uruchom Bandit

Bandit wykrywa podatności bezpieczeństwa w kodzie Python.
Konfiguracja w `bandit.yaml` wyklucza uzasadnione false positives (B101, B105, B106, B108).

```bash
cd {{CODE_DIR}} && \
docker run --rm \
  -v "$(pwd):/code" \
  tmask-python-linter:latest \
  -r /code/services \
  --exclude /code/services/web/apps/accounts/migrations,/code/services/web/apps/api/migrations,/code/services/web/apps/connections/migrations,/code/services/web/apps/flows/migrations,/code/services/web/apps/scheduler/migrations,/code/services/web/apps/transfers/migrations \
  -f json \
  2>/dev/null > /tmp/bandit-tmask-$(date +%Y-%m-%d).json
```

> Bandit wypisuje logi INFO/WARNING na stderr — `2>/dev/null` oddziela je od JSON na stdout.

Przeanalizuj wyniki:

```bash
python3 -c "
import json
data = json.load(open('/tmp/bandit-tmask-$(date +%Y-%m-%d).json'))
results = data.get('results', [])
totals = data.get('metrics', {}).get('_totals', {})
print(f'Bandit issues: {len(results)}')
print(f'HIGH: {totals.get(\"SEVERITY.HIGH\",0)}, MEDIUM: {totals.get(\"SEVERITY.MEDIUM\",0)}, LOW: {totals.get(\"SEVERITY.LOW\",0)}')
for r in results:
    sev = r.get('issue_severity','?')
    conf = r.get('issue_confidence','?')
    tid = r.get('test_id','?')
    text = r.get('issue_text','?')
    fname = r.get('filename','?').replace('/code/','')
    line = r.get('line_number','?')
    print(f'[{sev}/{conf}] {fname}:{line} ({tid}) — {text}')
"
```

### Wyjątki bandit.yaml

| ID | Reguła | Powód |
|----|--------|-------|
| B101 | `assert_used` | pytest używa `assert` by design |
| B105 | `hardcoded_password_string` | test fixture credentials |
| B106 | `hardcoded_password_funcarg` | test fixture credentials |
| B108 | `hardcoded_tmp_directory` | `/tmp` tylko w testach; prod używa `tempfile` |

---

## Znane false positives

Brak — ruff i bandit raportują wyłącznie realne problemy lub pomijają przez `bandit.yaml`.

---

## Zasady

- **Ruff wyklucza**: `ruff_bandit/`, `*/migrations/` — nie są częścią kodu aplikacji
- **Bandit wejście**: `-r /code/services` (nie `/code`) — narzędzia dev i konfiguracja poza zakresem
- **E402**: może oznaczać stałą między importami — sprawdź czy to celowe (PEP 8: stałe po importach)
- **Naprawa przed dokumentacją**: jeśli znajdziesz realne issues → napraw → uruchom ponownie → wtedy dokumentuj
- **Nie commituj** plików `/tmp/ruff-*.json` i `/tmp/bandit-*.json`
