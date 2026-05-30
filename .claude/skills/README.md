# tmask-tt — Claude Code Skills

Zestaw umiejętności (skills) dla Claude Code do pracy z projektem tmask-transporter.
Skille zastępują wielokrotne opisywanie tych samych procedur — wystarczy wpisać `/nazwa-skilla`.

## Przegląd skilli

| Skill | Komenda | Co robi | Wymaga |
|-------|---------|---------|--------|
| [tmask-python-linter](#tmask-python-linter) | `/tmask-python-linter` | Ruff (styl) + Bandit (security) przez Docker | Docker |
| [tmask-semgrep](#tmask-semgrep) | `/tmask-semgrep` | SAST — wzorce bezpieczeństwa Django/Python | Semgrep CLI |
| [trivy-sonar](#trivy-sonar) | `/trivy-sonar` | CVE obrazów Docker → SonarQube | Docker, SonarQube |
| [zap-scan](#zap-scan) | `/zap-scan` | DAST — spider + active scan | OWASP ZAP, app uruchomiona |
| [audyt-devsecops](#audyt-devsecops) | `/audyt-devsecops` | Pełny audyt: SonarQube + ZAP + Codex | Docker, SonarQube, opcjonalnie ZAP |

Skille z projektu (istniejące):

| Skill | Komenda | Co robi |
|-------|---------|---------|
| audyt | `/audyt` | Codex review + SonarQube QG + docker health + git push |
| debug-transfer | `/debug-transfer` | Diagnostyka nieudanych transferów |
| docker-manage | `/docker-manage` | Zarządzanie Docker Compose (migracje, testy, logi) |
| htmx-live-view | `/htmx-live-view` | Wzorzec Django + HTMX live-update |
| new-module | `/new-module` | Nowy moduł Django (web) lub transfer (worker) |
| pre-deploy | `/pre-deploy` | Checklist przed wdrożeniem na prod |
| retro-style | `/retro-style` | Zasady UI estetyki Terminal/CRT |
| security-check | `/security-check` | Szybki audyt bezpieczeństwa przed commitem |

---

## Instalacja od zera

### 1. Zainstaluj Claude Code

```bash
npm install -g @anthropic-ai/claude-code
```

Wymagana wersja: ≥ 1.x. Weryfikacja: `claude --version`

### 2. Sklonuj projekt

```bash
git clone <repo-url> tmask-tt
cd tmask-tt
```

Skille są częścią repozytorium — katalog `.claude/skills/` jest wersjonowany.

### 3. Dostosuj ścieżki w skillach

Skille zawierają placeholder `{{CODE_DIR}}` — zastąp go bezwzględną ścieżką do projektu:

```bash
# Zamień {{CODE_DIR}} we wszystkich SKILL.md na aktualną ścieżkę
CODE_DIR="$(pwd)"
find .claude/skills -name "SKILL.md" -exec \
  sed -i "s|{{CODE_DIR}}|${CODE_DIR}|g" {} \;
```

> **Uwaga:** Po tym kroku pliki SKILL.md będą zawierać hardcoded ścieżki.
> Nie commituj tych zmian — są lokalne. Dodaj do `.gitignore` jeśli chcesz:
> `.claude/skills/**/*.local.md`

### 4. Zainstaluj wymagania per skill

Patrz sekcje poniżej. Minimum do pracy z projektem:

```bash
# Docker (wymagany przez tmask-python-linter i trivy-sonar)
# https://docs.docker.com/get-docker/

# Zbuduj obraz lintera
docker build -t tmask-python-linter:latest ruff_bandit/

# Zbuduj obraz Trivy+SonarQube (do trivy-sonar)
cat > /tmp/Dockerfile.trivy <<'EOF'
FROM aquasec/trivy:0.70.0
RUN trivy plugin install sonarqube
EOF
docker build -f /tmp/Dockerfile.trivy -t trivy-sonar:0.70.0 .

# Semgrep (wymagany przez tmask-semgrep)
brew install semgrep        # macOS
# lub: pip install semgrep  # Linux
```

### 5. Skonfiguruj SonarQube (dla trivy-sonar i audyt-devsecops)

```bash
# Uruchom SonarQube Community
docker run -d --name sonarqube \
  -p 9000:9000 \
  sonarqube:community

# Poczekaj ~2 minuty, następnie otwórz http://localhost:9000
# Domyślne dane: admin / admin (zmień przy pierwszym logowaniu)
```

Utwórz projekt i token w SonarQube:
1. `http://localhost:9000` → Projects → Create Project → Manual
2. Nazwa projektu: `tmasktt`, klucz: `tmasktt`
3. My Account → Security → Generate Token → zapisz token

Token przekazuj przez zmienną środowiskową — **nigdy nie wpisuj do pliku**:
```bash
export SONAR_TOKEN="<twoj-token>"
```

### 6. Skonfiguruj MCP SonarQube (opcjonalne — do odczytu metryk w Claude)

```bash
# Zainstaluj serwer MCP SonarQube
npm install -g @sonarqube/mcp-server
```

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

### 7. Skonfiguruj OWASP ZAP (opcjonalne — do zap-scan i audyt-devsecops)

```bash
# macOS
brew install --cask owasp-zap

# Uruchom ZAP w trybie daemon
/Applications/ZAP.app/Contents/MacOS/ZAP \
  -daemon -port 8080 \
  -config api.key=<twoj-klucz>
```

Klucz API: ZAP GUI → Tools → Options → API → skopiuj lub ustaw własny.

### 8. Zainstaluj Semgrep plugin Claude Code (opcjonalne — MCP)

```bash
claude plugins install semgrep@claude-plugins-official
```

### 9. Uruchom aplikację

```bash
cp .env.example .env
# Uzupełnij .env (SECRET_KEY, bazy danych, itp.)
docker compose up -d
```

---

## Opis skilli

### tmask-python-linter

**Co robi:** Uruchamia ruff (styl kodu) i bandit (bezpieczeństwo) w kontenerze Docker `tmask-python-linter:latest`.

**Kiedy używać:** Przed każdym commitem, po większym refaktorze, jako część CI.

**Wymaga:**
- Docker
- Obraz `tmask-python-linter:latest` — `docker build -t tmask-python-linter:latest ruff_bandit/`

**Konfiguracja projektu:**
- `bandit.yaml` — wyjątki false positives (B101/B105/B106/B108)
- Brak `pyproject.toml` / `ruff.toml` — ruff używa domyślnych reguł

**Wynik:** Raport z listą issues ruff (styl) i bandit (security). Brak wyniku = kod czysty.

---

### tmask-semgrep

**Co robi:** Skan SAST przez Semgrep z regułami `p/python + p/django + p/security-audit`. Wykrywa wzorce bezpieczeństwa specyficzne dla Django (CSRF, SQL injection, XSS itp.).

**Kiedy używać:** Po dodaniu nowych endpointów, przed release, uzupełnienie bandit.

**Wymaga:**
- Semgrep CLI ≥ 1.146.0: `brew install semgrep` lub `pip install semgrep`
- Nie wymaga konta Semgrep dla reguł `p/*`

**Znane false positives:**
- `csrf-exempt` na `apps/api/views.py` — REST API z token auth, CSRF nie dotyczy

---

### trivy-sonar

**Co robi:** Skanuje 6 obrazów Docker (nginx, web, beat, worker, postgres, redis) przez Trivy w poszukiwaniu CVE, importuje wyniki do SonarQube jako external issues.

**Kiedy używać:** Po aktualizacji obrazów bazowych, przy planowaniu upgradeu zależności.

**Wymaga:**
- Docker
- Obraz `trivy-sonar:0.70.0` (aquasec/trivy + plugin sonarqube)
- SonarQube z tokenem (przez `SONAR_TOKEN` env)
- Skrypt `Trivy/scan-trivy-sonar.sh` w projekcie

**Konfiguracja projektu:**
- `sonar-project.properties` — klucz projektu, URL SonarQube
- `Trivy/Dockerfile.{nginx,postgres,redis}` — referencyje obrazów do skanowania

---

### zap-scan

**Co robi:** Dynamiczny test bezpieczeństwa (DAST) — spider odkrywa wszystkie URL-e, active scan wysyła payloady ataków i raportuje alerty pogrupowane według ryzyka.

**Kiedy używać:** Po dodaniu nowych endpointów, przed release na prod. Tylko na dev/test.

**Wymaga:**
- OWASP ZAP uruchomiony na `localhost:8080`
- Aplikacja uruchomiona i dostępna pod `TARGET_URL`
- Klucz API ZAP

**Ważne:** Active scan wysyła rzeczywiste payloady ataków — **tylko na własnym środowisku**.

---

### audyt-devsecops

**Co robi:** Orchestruje pełny audyt bezpieczeństwa w kolejności: SonarQube SAST → ZAP DAST → Codex code review → skonsolidowany raport.

**Kiedy używać:** Przed ważnym release, po większych zmianach architektury, cyklicznie (np. co sprint).

**Wymaga:**
- Docker + SonarQube (etap 1 — obowiązkowy)
- ZAP + uruchomiona aplikacja (etap 2 — opcjonalny)
- Codex CLI lub subagent (etap 3 — opcjonalny)
- MCP SonarQube do odczytu wyników

---

## Sekwencja pełnego audytu

```
/tmask-python-linter   ← Ruff + Bandit (najszybszy, uruchamiaj pierwszy)
/tmask-semgrep         ← Semgrep SAST (dodatkowe reguły Django)
/trivy-sonar           ← CVE w kontenerach (potrzebuje SONAR_TOKEN)
/zap-scan              ← DAST (potrzebuje działającej aplikacji)
/audyt-devsecops       ← Łączy wszystkie wyniki w jeden raport
```

---

## Bezpieczeństwo — zasady

- **SONAR_TOKEN**: wyłącznie przez env var (`export SONAR_TOKEN=...`) — nigdy do pliku
- **ZAP_API_KEY**: nie zapisuj w commitach ani dokumentacji
- **Hasła adminów**: używaj tylko w sesji Claude, nie commituj
- **Wyniki skanów JSON**: zapisuj w `/tmp/` — nie wchodzą do git (`.gitignore`)
