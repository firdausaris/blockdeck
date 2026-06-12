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

# Generate a dashboard password if none is set yet
if ! grep -qE '^DASH_PASSWORD=.+' .env; then
    DASH_PW="$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 16)"
    if grep -qE '^DASH_PASSWORD=' .env; then
        sed -i "s|^DASH_PASSWORD=.*|DASH_PASSWORD=${DASH_PW}|" .env
    else
        printf 'DASH_USERNAME=admin\nDASH_PASSWORD=%s\n' "$DASH_PW" >> .env
    fi
    DASH_USER="$(grep -E '^DASH_USERNAME=' .env | head -n1 | cut -d= -f2-)"
    echo "==> Dashboard login generated: ${DASH_USER:-admin} / ${DASH_PW}"
    echo "    (stored in .env as DASH_PASSWORD)"
fi

# Create the bind-mount dirs as the current user — if docker creates them
# they end up root-owned and the server runs as root
mkdir -p data backups map-data

# --- First-run world setup ---
# The active world lives in data/server.properties (see scripts/world.sh);
# ask interactively when this is a fresh install
WORLD_CMD=()
if [[ ! -f data/server.properties && -t 0 ]]; then
    echo
    echo "==> First run — set up your world:"
    echo "    1) Create a new world"
    echo "    2) Import an existing world (.mcworld / .zip / folder)"
    read -rp "Choose [1]: " choice
    if [[ "${choice:-1}" == 2 ]]; then
        read -rp "Path to the world file or folder: " wpath
        read -rp "World name (blank = auto-detect): " wname
        WORLD_CMD=(import "$wpath")
        [[ -n "$wname" ]] && WORLD_CMD+=("$wname")
    else
        read -rp "World name [world]: " wname
        read -rp "Seed (blank = random): " wseed
        WORLD_CMD=(create "${wname:-world}")
        [[ -n "$wseed" ]] && WORLD_CMD+=("$wseed")
    fi
fi

# --- Start ---
# Use sudo if the docker group membership isn't active in this shell yet
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
fi

if [[ ${#WORLD_CMD[@]} -gt 0 ]]; then
    ./scripts/world.sh "${WORLD_CMD[@]}"
fi

echo "==> Starting the Bedrock server ..."
$DOCKER compose up -d

echo
echo "Done. Useful commands:"
echo "  $DOCKER compose logs -f bedrock     # watch server logs"
echo "  ./scripts/console.sh list           # send a console command"
echo "  ./scripts/import-world.sh <path>    # import an existing world"
