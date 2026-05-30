---
name: trivy-sonar
description: Skan CVE obrazów Docker przez Trivy i import wyników do SonarQube jako external issues. Uruchamia skrypt Trivy/scan-trivy-sonar.sh. Wymaga tokenu SonarQube podawanego przez SONAR_TOKEN env — nigdy nie zapisuj tokenu do pliku.
---

# Skill: trivy-sonar

Przeprowadza skan bezpieczeństwa obrazów Docker przez Trivy i integruje wyniki z SonarQube
jako external issues.

## Konfiguracja — dostosuj przed użyciem

> Zamień `{{CODE_DIR}}` na bezwzględną ścieżkę do katalogu projektu

| Zmienna | Opis | Przykład |
|---------|------|---------|
| `CODE_DIR` | Bezwzględna ścieżka do projektu | `/home/user/tmask-tt` |
| `SONAR_HOST` | URL SonarQube | z `sonar-project.properties` |
| `SONAR_KEY` | Klucz projektu SonarQube | z `sonar-project.properties` |

## Wymagania

| Narzędzie | Instalacja | Weryfikacja |
|-----------|-----------|-------------|
| Docker | https://docs.docker.com/get-docker/ | `docker --version` |
| Obraz `trivy-sonar:0.70.0` | Zbuduj z poniższego Dockerfile | `docker images \| grep trivy-sonar` |
| SonarQube | `docker run -d -p 9000:9000 sonarqube:community` | `curl http://localhost:9000/api/system/status` |
| Token SonarQube | SonarQube → My Account → Security → Generate Token | — |
| Python 3 | systemowy | `python3 --version` |

### Zbuduj obraz trivy-sonar

```bash
# Dockerfile dla trivy-sonar:0.70.0
cat > /tmp/Dockerfile.trivy-sonar <<'EOF'
FROM aquasec/trivy:0.70.0
RUN trivy plugin install sonarqube
EOF
docker build -f /tmp/Dockerfile.trivy-sonar -t trivy-sonar:0.70.0 .
```

### Konfiguracja MCP SonarQube (opcjonalne — do odczytu wyników)

Dodaj do `~/.claude/settings.json`:
```json
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

## Krok 1 — Sprawdź token SonarQube

```bash
grep "^sonar.token" {{CODE_DIR}}/sonar-project.properties
```

Jeśli wartość to `REPLACE_WITH_YOUR_SONARQUBE_TOKEN` → **zatrzymaj się i poproś użytkownika o token**.

Token przekazuj **wyłącznie przez zmienną środowiskową** `SONAR_TOKEN` — nigdy nie zapisuj do pliku.

---

## Krok 2 — Uruchom Trivy (etap 1)

Trivy nie potrzebuje tokenu SonarQube:

```bash
cd {{CODE_DIR}}
bash Trivy/scan-trivy-sonar.sh --trivy-only
```

Skrypt skanuje 6 obrazów i generuje pliki w `Trivy/`:
- `trivy-{nginx,web,beat,worker,postgres,redis}.json` — surowy output
- `sonar-trivy-tmask-tt-{nginx,web,beat,worker,postgres,redis}.json` — format SonarQube

Zbierz CVE per serwis:
```bash
cd {{CODE_DIR}}
for f in Trivy/sonar-trivy-tmask-tt-*.json; do
  svc=$(basename $f | sed 's/sonar-trivy-tmask-tt-//;s/\.json//')
  count=$(python3 -c "import json; print(len(json.load(open('$f')).get('issues',[])))")
  echo "${svc}: ${count} CVE"
done
```

---

## Krok 3 — Uruchom SonarQube scan (etap 2)

```bash
cd {{CODE_DIR}}
SONAR_TOKEN=<token_od_użytkownika> bash Trivy/scan-trivy-sonar.sh --sonar-only
```

Poczekaj na `EXECUTION SUCCESS` w output.

---

## Krok 4 — Odczyt wyników (MCP SonarQube)

Po skanie użyj narzędzi MCP jeśli dostępne:

```
mcp__sonarqube__get_quality_gate_status   projectKey=<klucz>
mcp__sonarqube__get_component_measures    projectKey=<klucz>
  metryki: bugs,vulnerabilities,code_smells,security_hotspots,
           coverage,duplicated_lines_density,
           reliability_rating,security_rating,sqale_rating
mcp__sonarqube__search_sonar_issues       projectKey=<klucz>
  impactSeverities=["HIGH","MEDIUM"], resolved=false, pageSize=100
```

---

## Zasady

- **Token SonarQube**: wyłącznie przez `SONAR_TOKEN=<token>` env var — nigdy nie commituj
- **Etapy rozdzielone**: `--trivy-only` nie wymaga tokenu; `--sonar-only` wymaga
- **Obrazy lokalne** (`tmask-tt-*:latest`): skanowane lokalnie bez pull z registry
- Jeśli brak tokenu → uruchom `--trivy-only` i zaznacz w raporcie że SonarQube pominięto
