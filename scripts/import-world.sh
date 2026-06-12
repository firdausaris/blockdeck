#!/usr/bin/env bash
#
# Import an existing Bedrock world into this server.
#
# Usage:
#   ./scripts/import-world.sh <world-folder | world.mcworld | world.zip>
#
# The world is installed as data/worlds/$LEVEL_NAME (from .env).
# Any existing world with that name is kept as a timestamped .bak folder.
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

SRC="${1:?Usage: $0 <world-folder | world.mcworld | world.zip>}"

# Read LEVEL_NAME from .env (compose-style KEY=VALUE)
LEVEL_NAME="$(grep -E '^LEVEL_NAME=' .env 2>/dev/null | head -n1 | cut -d= -f2- || true)"
LEVEL_NAME="${LEVEL_NAME:-world}"
DEST="data/worlds/$LEVEL_NAME"

# --- Stage the source into a temp dir ---
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

case "$SRC" in
    *.mcworld|*.zip)
        command -v unzip >/dev/null || { echo "unzip is required: sudo apt-get install unzip"; exit 1; }
        unzip -q "$SRC" -d "$TMP/extracted"
        STAGED="$TMP/extracted"
        # Some zips wrap the world in a single top-level folder
        if [[ ! -f "$STAGED/level.dat" ]]; then
            INNER="$(find "$STAGED" -maxdepth 2 -name level.dat -printf '%h\n' | head -n1 || true)"
            [[ -n "$INNER" ]] && STAGED="$INNER"
        fi
        ;;
    *)
        STAGED="$SRC"
        ;;
esac

if [[ ! -f "$STAGED/level.dat" ]]; then
    echo "Error: no level.dat found in '$SRC' — is this really a Bedrock world?"
    exit 1
fi

# --- Stop the server while we swap world data ---
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

WAS_RUNNING=0
if $DOCKER compose ps --status running bedrock 2>/dev/null | grep -q bedrock; then
    WAS_RUNNING=1
    echo "==> Stopping server ..."
    $DOCKER compose stop bedrock
fi

# --- Install the world ---
if [[ -d "$DEST" ]]; then
    BAK="$DEST.bak.$(date +%Y%m%d-%H%M%S)"
    echo "==> Existing world found, moving to $BAK"
    mv "$DEST" "$BAK"
fi
mkdir -p "$(dirname "$DEST")"
cp -a "$STAGED" "$DEST"
echo "==> World installed at $DEST"

# --- Restart ---
if [[ $WAS_RUNNING -eq 1 ]]; then
    echo "==> Starting server ..."
    $DOCKER compose up -d bedrock
fi

echo "Done. Verify with: $DOCKER compose logs -f bedrock"
