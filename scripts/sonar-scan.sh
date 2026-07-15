#!/bin/sh
# Runs the web + worker test suites with coverage, fixes up the <source>
# paths in the generated coverage.xml files (pytest-cov records them
# relative to each service's own container root — /app — which does not
# line up with the monorepo root the scanner analyzes from), then runs
# sonar-scanner-cli.
#
# Usage: SONAR_TOKEN=... ./scripts/sonar-scan.sh
# SONAR_HOST_URL defaults to the value in sonar-project.properties.
set -e

cd "$(dirname "$0")/.."

echo "==> Running web test suite with coverage"
docker compose --profile test run --rm -v "$PWD/services/web:/app" web-test \
    python -m pytest apps/ -q

echo "==> Running worker test suite with coverage"
docker compose run --rm -v "$PWD/services/worker:/app" worker \
    python -m pytest tests/ -q

echo "==> Rewriting coverage.xml <source> paths to be relative to repo root"
sed -i.bak 's#<source>apps</source>#<source>services/web/apps</source>#' services/web/coverage.xml
sed -i.bak 's#<source></source>#<source>services/worker</source>#; s#<source>modules</source>#<source>services/worker/modules</source>#' services/worker/coverage.xml
rm -f services/web/coverage.xml.bak services/worker/coverage.xml.bak

echo "==> Running sonar-scanner-cli"
docker run --rm \
    -e SONAR_HOST_URL="${SONAR_HOST_URL:-http://10.254.0.1:9000}" \
    -e SONAR_TOKEN="${SONAR_TOKEN:?SONAR_TOKEN is required}" \
    -v "$PWD:/usr/src" \
    sonarsource/sonar-scanner-cli
