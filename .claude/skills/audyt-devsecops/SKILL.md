---
name: audyt-devsecops
description: Pełny audyt DevSecOps w trzech etapach — SonarQube SAST + OWASP ZAP DAST + Codex code review. Orchestruje pozostałe skille i tworzy skonsolidowany raport. Kolejność obowiązkowa: SonarQube → ZAP → Codex → raport.
---

# Skill: audyt-devsecops

Pełny audyt bezpieczeństwa: **SonarQube (SAST) → OWASP ZAP (DAST) → Codex (code review)**.

## Konfiguracja — dostosuj przed użyciem

| Zmienna | Opis | Przykład |
|---------|------|---------|
| `CODE_DIR` | Bezwzględna ścieżka do projektu | `/home/user/tmask-tt` |
| `TARGET_URL` | URL aplikacji (opcjonalny — do ZAP) | `http://localhost` |
| `SONAR_TOKEN` | Token SonarQube — env var, nigdy plik | — |
| `ZAP_API_KEY` | Klucz API ZAP — z ZAP GUI | — |

## Wymagania

| Narzędzie | Wymagane | Instalacja |
|-----------|----------|-----------|
| Docker | TAK | https://docs.docker.com/get-docker/ |
| SonarQube | TAK | `docker run -d -p 9000:9000 sonarqube:community` |
| MCP SonarQube plugin | TAK | patrz niżej |
| OWASP ZAP | opcjonalne | https://www.zaproxy.org/download/ |
| Codex CLI | opcjonalne | `npm install -g @openai/codex` |

### Konfiguracja MCP SonarQube

```json
// ~/.claude/settings.json
{
  "mcpServers": {
    "sonarqube": {
      "command": "npx",
      "args": ["@sonarqube/mcp-server"],
      "env": {
        "SONARQUBE_URL": "http://localhost:9000",
        "SONARQUBE_TOKEN": "<twoj-token>"
      }
    }
  }
}
```

---

## Etap 1 — SonarQube (SAST)

### Krok 1 — Odczytaj konfigurację

```bash
SONAR_PROPS="{{CODE_DIR}}/sonar-project.properties"
SONAR_KEY=$(grep "^sonar.projectKey" "${SONAR_PROPS}" | cut -d= -f2)
SONAR_HOST=$(grep "^sonar.host.url" "${SONAR_PROPS}" | cut -d= -f2)
echo "Projekt: ${SONAR_KEY} @ ${SONAR_HOST}"
```

### Krok 2 — Uruchom skan

```bash
SONAR_TOKEN=<token> docker run --rm \
  -e SONAR_HOST_URL="${SONAR_HOST}" \
  -e SONAR_TOKEN="${SONAR_TOKEN}" \
  -v "{{CODE_DIR}}:/usr/src" \
  sonarsource/sonar-scanner-cli
```

Poczekaj na `EXECUTION SUCCESS`.

### Krok 3 — Quality Gate i metryki (MCP)

```
mcp__sonarqube__get_quality_gate_status   projectKey=${SONAR_KEY}
mcp__sonarqube__get_component_measures    projectKey=${SONAR_KEY}
  metryki: bugs,vulnerabilities,code_smells,security_hotspots,
           coverage,duplicated_lines_density,
           reliability_rating,security_rating,sqale_rating
mcp__sonarqube__search_sonar_issues       projectKey=${SONAR_KEY}
  impactSeverities=["HIGH","MEDIUM"], resolved=false, pageSize=100
```

---

## Etap 2 — OWASP ZAP (DAST)

Pomiń jeśli brak `TARGET_URL` lub ZAP nie jest uruchomiony — zaznacz w raporcie.

Patrz skill `zap-scan` — pełne instrukcje spider + active scan + alerty.

Sprawdź dostępność ZAP:
```bash
curl -sf "http://localhost:8080/JSON/core/view/version/?apikey=${ZAP_API_KEY}" | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])"
```

---

## Etap 3 — Codex (Code Review)

Uruchom subagenta Codex do code review:

```
Agent({
  subagent_type: "codex:codex-rescue",
  description: "Security code review — tmask-transporter",
  prompt: "Przeprowadź security-focused code review projektu w {{CODE_DIR}}.
  
  TYLKO analiza — nie modyfikuj plików.
  
  Sprawdź: OWASP Top 10, hardcoded secrets, input validation,
  authorization/owner checks, command injection, path traversal,
  słaba kryptografia, race conditions, dependency risk.
  
  Format każdego znaleziska:
  SEVERITY|FILE:LINE|CWE|DESCRIPTION|FIX
  
  Możliwe SEVERITY: CRITICAL, HIGH, MEDIUM, LOW
  
  Podsumowanie: SUMMARY: X critical, X high, X medium, X low"
})
```

---

## Krok 4 — Skonsolidowany raport

Utwórz raport łączący wyniki wszystkich trzech etapów:

```markdown
---
tags: [security, audyt, devsecops, tmask-transporter]
created: YYYY-MM-DD
updated: YYYY-MM-DD
tools: [sonarqube, zap, codex]
---

# Audyt DevSecOps: tmask-transporter — YYYY-MM-DD

## Executive Summary

| Narzędzie | Status | Krytyczne | Wysokie | Średnie |
|-----------|--------|-----------|---------|---------|
| SonarQube | PASSED/FAILED | — | X | X |
| OWASP ZAP | ✅/POMINIĘTY | X | X | X |
| Codex | ✅ | X | X | X |

**Wynik ogólny:** 🔴 WYMAGA NAPRAWY / 🟢 BRAK BLOKERÓW

## 1. SonarQube — SAST
[wyniki Quality Gate, metryki, issues HIGH/MEDIUM]

## 2. OWASP ZAP — DAST
[alerty High/Medium/Low lub "> ⚠️ Pominięty."]

## 3. Codex — Code Review
[znaleziska CRITICAL/HIGH/MEDIUM/LOW]

## Rekomendacje priorytetowe
### 🔴 CRITICAL — blokery wdrożenia
### 🟠 HIGH — przed kolejnym release
### 🟡 MEDIUM — backlog
```

---

## Zasady

- **Kolejność**: SonarQube → ZAP → Codex → raport (obowiązkowa)
- **ZAP opcjonalny**: pomiń gdy aplikacja nie działa, zaznacz w raporcie
- **SONAR_TOKEN**: wyłącznie przez env var — nigdy do pliku
- **Deduplikacja**: jeśli ZAP i Codex wykryją to samo → jeden wpis z adnotacją `[ZAP+Codex]`
- **Brak blokerów**: zaznacz explicite — nie pomijaj sekcji
