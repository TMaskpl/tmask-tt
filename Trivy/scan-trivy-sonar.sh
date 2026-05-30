#!/usr/bin/env bash
# scan-trivy-sonar.sh — Trivy image scan → SonarQube external issues
# Użycie: ./scan-trivy-sonar.sh [--trivy-only] [--sonar-only]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SONAR_PROPS="${PROJECT_ROOT}/sonar-project.properties"

# --- Tryb pracy ---
TRIVY_ONLY=false
SONAR_ONLY=false
for arg in "$@"; do
  case "${arg}" in
    --trivy-only) TRIVY_ONLY=true ;;
    --sonar-only) SONAR_ONLY=true ;;
  esac
done

# --- Konfiguracja SonarQube ---
SONAR_KEY=$(grep "^sonar.projectKey" "${SONAR_PROPS}" | cut -d= -f2 | tr -d '[:space:]')
SONAR_HOST=$(grep "^sonar.host.url" "${SONAR_PROPS}" | cut -d= -f2 | tr -d '[:space:]')
SONAR_TOKEN="${SONAR_TOKEN:-$(grep "^sonar.token" "${SONAR_PROPS}" | cut -d= -f2 | tr -d '[:space:]')}"

if [[ "${TRIVY_ONLY}" == "false" && "${SONAR_TOKEN}" == "REPLACE_WITH_YOUR_SONARQUBE_TOKEN" ]]; then
  echo "ERROR: Brak tokenu SonarQube."
  echo "  Opcja 1: ustaw sonar.token=<token> w ${SONAR_PROPS}"
  echo "  Opcja 2: SONAR_TOKEN=<token> ./scan-trivy-sonar.sh"
  echo "  Tylko Trivy (bez SonarQube): ./scan-trivy-sonar.sh --trivy-only"
  exit 1
fi

# --- Obrazy do skanowania: "serwis:obraz:ścieżka_dockerfile_w_projekcie" ---
# filePath musi wskazywać na plik zaindeksowany przez SonarQube
SCANS="nginx:nginx:stable-alpine:Trivy/Dockerfile.nginx
web:tmask-tt-web:latest:services/web/Dockerfile
beat:tmask-tt-beat:latest:services/web/Dockerfile
worker:tmask-tt-worker:latest:services/worker/Dockerfile
postgres:postgres:17-alpine:Trivy/Dockerfile.postgres
redis:redis:7-alpine:Trivy/Dockerfile.redis"

# ============================================================
# ETAP 1: Trivy — skan każdego obrazu + konwersja do formatu SonarQube
# ============================================================
if [[ "${SONAR_ONLY}" == "false" ]]; then
  echo ""
  echo "=== ETAP 1: TRIVY SCAN ==="

  while IFS=: read -r SERVICE IMAGE_NAME IMAGE_TAG DOCKERFILE_PATH; do
    IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
    SONAR_JSON="${SCRIPT_DIR}/sonar-trivy-tmask-tt-${SERVICE}.json"

    echo ""
    echo "  [${SERVICE}] Skanuję obraz: ${IMAGE} → ${DOCKERFILE_PATH}"

    docker run --rm \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v trivy-cache:/root/.cache/ \
      -v "${SCRIPT_DIR}:/work" -w /work \
      trivy-sonar:0.70.0 \
      image --format json -o "trivy-${SERVICE}.json" "${IMAGE}" \
      2>&1 | grep -v "^$" | sed 's/^/    /'

    docker run --rm \
      -v "${SCRIPT_DIR}:/work" -w /work \
      trivy-sonar:0.70.0 \
      sonarqube "/work/trivy-${SERVICE}.json" \
      --filePath="${DOCKERFILE_PATH}" \
      > "${SONAR_JSON}"

    ISSUE_COUNT=$(python3 -c "import json; d=json.load(open('${SONAR_JSON}')); print(len(d.get('issues',[])))" 2>/dev/null || echo "?")
    echo "    → ${SONAR_JSON} (${ISSUE_COUNT} issues)"
  done <<< "${SCANS}"
fi

# ============================================================
# ETAP 2: SonarQube — skan kodu + zewnętrzne wyniki Trivy
# ============================================================
if [[ "${TRIVY_ONLY}" == "false" ]]; then
  echo ""
  echo "=== ETAP 2: SONARQUBE SCAN ==="

  # Popraw ścieżki coverage.xml z Docker-wewnętrznych (/app/) na ścieżki projektu
  WEB_COV="${PROJECT_ROOT}/services/web/coverage.xml"
  WORKER_COV="${PROJECT_ROOT}/services/worker/coverage.xml"
  if [[ -f "${WEB_COV}" ]]; then
    sed -e 's|/app/|services/web/|g' \
        -e 's|<source>/app</source>|<source>services/web</source>|g' \
        "${WEB_COV}" > "${WEB_COV}.fixed" && mv "${WEB_COV}.fixed" "${WEB_COV}"
    echo "  coverage.xml (web): ścieżki poprawione"
  fi
  if [[ -f "${WORKER_COV}" ]]; then
    sed -e 's|/app/|services/worker/|g' \
        -e 's|<source>/app</source>|<source>services/worker</source>|g' \
        "${WORKER_COV}" > "${WORKER_COV}.fixed" && mv "${WORKER_COV}.fixed" "${WORKER_COV}"
    echo "  coverage.xml (worker): ścieżki poprawione"
  fi

  REPORTS=$(cd "${SCRIPT_DIR}" && ls sonar-trivy-tmask-tt-*.json 2>/dev/null \
    | sed "s|^|Trivy/|" | tr '\n' ',' | sed 's/,$//')

  if [[ -z "${REPORTS}" ]]; then
    echo "WARN: Brak plików sonar-trivy-tmask-tt-*.json — uruchom najpierw --trivy-only"
  else
    echo "  Raporty Trivy: ${REPORTS}"
  fi
  echo "  Projekt: ${SONAR_KEY} @ ${SONAR_HOST}"
  echo ""

  EXTRA_ARGS=""
  if [[ -n "${REPORTS}" ]]; then
    EXTRA_ARGS="-Dsonar.externalIssuesReportPaths=${REPORTS}"
  fi

  docker run --rm \
    -v "${PROJECT_ROOT}:/usr/src" \
    -e SONAR_HOST_URL="${SONAR_HOST}" \
    -e SONAR_TOKEN="${SONAR_TOKEN}" \
    sonarsource/sonar-scanner-cli \
    -Dsonar.scm.disabled=true \
    ${EXTRA_ARGS}
fi

echo ""
echo "=== ZAKOŃCZONO ==="
