#!/usr/bin/env bash
# Instaluje zależności systemowe potrzebne do uruchomienia tmask-transporter
# na czystym serwerze Debian/Ubuntu (on-prem lub VPS): Docker Engine,
# wtyczkę Docker Compose v2, git i openssl.
#
# Użycie:
#   curl -fsSL https://raw.githubusercontent.com/TMaskpl/tmask-tt/main/scripts/install-system-deps.sh | sudo bash
# albo po sklonowaniu repo:
#   sudo ./scripts/install-system-deps.sh
#
# Idempotentny — bezpieczny do ponownego uruchomienia (nie nadpisuje istniejącej
# instalacji Dockera, tylko sprawdza czy jest i w razie braku instaluje).

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Ten skrypt wymaga uprawnień roota — uruchom przez sudo." >&2
  exit 1
fi

if [ ! -f /etc/os-release ]; then
  echo "Nie znaleziono /etc/os-release — skrypt obsługuje tylko Debian/Ubuntu." >&2
  exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release
case "$ID" in
  debian|ubuntu) ;;
  *)
    echo "Wykryto dystrybucję '$ID' — skrypt jest przetestowany tylko na Debian/Ubuntu." >&2
    echo "Kontynuuję mimo to (repozytorium Docker też wspiera pochodne, np. Mint/Pop!_OS)." >&2
    ;;
esac

echo "==> Aktualizacja listy pakietów"
apt-get update -y

echo "==> Instalacja pakietów bazowych (curl, git, ca-certificates, openssl, gnupg)"
apt-get install -y --no-install-recommends ca-certificates curl git openssl gnupg

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "==> Docker + wtyczka Compose już zainstalowane ($(docker --version)), pomijam instalację Dockera."
else
  echo "==> Instalacja Docker Engine + Docker Compose v2 z oficjalnego repozytorium Docker"

  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  ARCH="$(dpkg --print-architecture)"
  CODENAME="${VERSION_CODENAME:-$(lsb_release -cs)}"
  echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  systemctl enable --now docker
fi

TARGET_USER="${SUDO_USER:-$USER}"
if [ "$TARGET_USER" != "root" ] && ! id -nG "$TARGET_USER" | grep -qw docker; then
  echo "==> Dodaję użytkownika '$TARGET_USER' do grupy 'docker' (uruchamianie docker bez sudo)"
  usermod -aG docker "$TARGET_USER"
  echo "    UWAGA: wyloguj się i zaloguj ponownie (albo 'newgrp docker'), żeby zmiana grupy zadziałała."
fi

echo ""
echo "==> Gotowe. Wersje:"
docker --version
docker compose version
git --version

echo ""
echo "Następny krok: sklonuj repo i przejdź do sekcji 'Uruchomienie' w README.md."
