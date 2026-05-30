---
name: zap-scan
description: Skan DAST (dynamiczny) przez OWASP ZAP — spider + active scan na uruchomionej aplikacji. Uruchamiaj tylko na środowisku dev/test. Wymaga działającego ZAP na localhost:8080 i uruchomionej aplikacji.
---

# Skill: zap-scan

Skanuje uruchomioną aplikację przez OWASP ZAP (spider + active scan) i dokumentuje wyniki.

## Konfiguracja

| Zmienna | Opis | Przykład |
|---------|------|---------|
| `TARGET_URL` | URL skanowanej aplikacji | `http://localhost` |
| `ZAP_API_KEY` | Klucz API ZAP | z ZAP GUI → Tools → Options → API |

## Wymagania

| Narzędzie | Instalacja | Weryfikacja |
|-----------|-----------|-------------|
| OWASP ZAP | https://www.zaproxy.org/download/ | `curl http://localhost:8080/JSON/core/view/version/` |
| Aplikacja uruchomiona | `docker compose up -d` | `curl http://localhost` |
| Python 3 | systemowy | `python3 --version` |

### Uruchom ZAP z API

```bash
# macOS (po instalacji przez brew lub .dmg)
/Applications/ZAP.app/Contents/MacOS/ZAP \
  -daemon \
  -port 8080 \
  -config api.key=<twoj-klucz>

# Lub przez Docker
docker run -d -p 8080:8080 \
  ghcr.io/zaproxy/zaproxy:stable \
  zap-webswing.sh
```

> ⚠️ Active scan wysyła payloady ataków (SQLi, XSS). Używaj **wyłącznie na dev/test** — nigdy na produkcji.

---

## Krok 1 — Sprawdź dostępność ZAP

```bash
ZAP_API_KEY="<twoj-klucz>"
ZAP_VERSION=$(curl -sf "http://localhost:8080/JSON/core/view/version/?apikey=${ZAP_API_KEY}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])" 2>/dev/null)
echo "ZAP: ${ZAP_VERSION:-NIEDOSTĘPNY}"
```

---

## Krok 2 — Spider Scan

```bash
SPIDER_ID=$(curl -sf \
  "http://localhost:8080/JSON/spider/action/scan/?url=${TARGET_URL}&maxChildren=10&apikey=${ZAP_API_KEY}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['scan'])")

while true; do
  PROG=$(curl -sf \
    "http://localhost:8080/JSON/spider/view/status/?scanId=${SPIDER_ID}&apikey=${ZAP_API_KEY}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "Spider: ${PROG}%"
  [ "$PROG" = "100" ] && break
  sleep 10
done
```

---

## Krok 3 — Active Scan (timeout 30 min)

```bash
ASCAN_ID=$(curl -sf \
  "http://localhost:8080/JSON/ascan/action/scan/?url=${TARGET_URL}&recurse=true&apikey=${ZAP_API_KEY}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['scan'])")

COUNT=0
while [ $COUNT -lt 120 ]; do
  PROG=$(curl -sf \
    "http://localhost:8080/JSON/ascan/view/status/?scanId=${ASCAN_ID}&apikey=${ZAP_API_KEY}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "Active scan: ${PROG}%"
  [ "$PROG" = "100" ] && break
  sleep 15
  COUNT=$((COUNT+1))
done
[ $COUNT -ge 120 ] && echo "⚠️ Timeout — pobieramy dotychczasowe alerty."
```

---

## Krok 4 — Pobierz i zdeduplikuj alerty

```bash
export PROJECT_NAME="tmask-transporter"
curl -sf \
  "http://localhost:8080/JSON/core/view/alerts/?baseurl=${TARGET_URL}&apikey=${ZAP_API_KEY}" \
  > /tmp/zap_alerts_${PROJECT_NAME}.json

python3 - <<'PYEOF'
import json, os
fname = f"/tmp/zap_alerts_{os.environ.get('PROJECT_NAME','project')}.json"
with open(fname) as f:
    alerts = json.load(f).get('alerts', [])
by_risk = {'High': [], 'Medium': [], 'Low': [], 'Informational': []}
seen = set()
for a in alerts:
    key = (a['name'], a.get('cweid',''))
    if key not in seen:
        seen.add(key)
        by_risk.get(a.get('risk','Informational'), by_risk['Informational']).append(a)
icons = {'High': '🔴', 'Medium': '🟠', 'Low': '🟡', 'Informational': 'ℹ️'}
total = sum(len(v) for v in by_risk.values())
print(f"Łącznie: {total} unikalnych alertów")
for risk, items in by_risk.items():
    print(f"{icons[risk]} {risk}: {len(items)}")
    for a in items:
        print(f"  CWE-{a.get('cweid','?')} | {a['name']} | {a.get('url','?')[:70]}")
PYEOF
```

---

## Zasady

- **Spider przed active scan** — zawsze w tej kolejności
- **Timeout**: 30 min na active scan — po tym pobierz dotychczasowe alerty
- **Deduplikacja**: grupuj po `(name, cweid)` — nie raportuj każdej instancji osobno
- **API Key**: nigdy nie zapisuj w dokumentacji ani commitach
- **Tylko dev/test**: active scan wysyła złośliwe payloady
- **Brak alertów High**: odnotuj explicite jako pozytywny wynik
