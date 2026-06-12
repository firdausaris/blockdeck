#!/usr/bin/env bash
#
# One-shot setup on a fresh Ubuntu/Debian machine:
# installs Docker if missing, prepares .env, starts the server.
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# --- Docker ---
if ! command -v docker >/dev/null 2>&1; then
    echo "==> Docker not found, installing via get.docker.com ..."
    curl -fsSL https://get.docker.com | sudo sh
else
    echo "==> Docker already installed: $(docker --version)"
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "==> Installing the docker compose plugin ..."
    sudo apt-get update -qq
    sudo apt-get install -y docker-compose-plugin
fi

# Allow running docker without sudo (takes effect on next login)
if ! id -nG "$USER" | grep -qw docker; then
    echo "==> Adding $USER to the docker group (re-login for it to take effect)"
    sudo usermod -aG docker "$USER"
fi

# --- Config ---
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "==> Created .env from .env.example — review it before going live:"
    echo "      $REPO_DIR/.env"
fi

# Generate the console password file the backup service reads, from
# RCON_PASSWORD in .env (rerun this script after changing it)
RCON_PW="$(grep -E '^RCON_PASSWORD=' .env | head -n1 | cut -d= -f2- || true)"
if [[ -n "$RCON_PW" && "$RCON_PW" != "change-me" ]]; then
    printf 'password: %s\n' "$RCON_PW" > backup/console-password.yml
else
    echo "==> WARNING: set a real RCON_PASSWORD in .env, then rerun this script"
    echo "    (the backup service can't reach the server console without it)"
fi

# Create the bind-mount dirs as the current user — if docker creates them
# they end up root-owned and the server runs as root
mkdir -p data backups map-data

# --- Start ---
# Use sudo if the docker group membership isn't active in this shell yet
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
fi

echo "==> Starting the Bedrock server ..."
$DOCKER compose up -d

echo
echo "Done. Useful commands:"
echo "  $DOCKER compose logs -f bedrock     # watch server logs"
echo "  ./scripts/console.sh list           # send a console command"
echo "  ./scripts/import-world.sh <path>    # import an existing world"
