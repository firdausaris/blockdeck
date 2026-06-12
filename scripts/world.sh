#!/usr/bin/env bash
#
# Manage worlds. The active world is the level-name in data/server.properties.
#
# Usage:
#   ./scripts/world.sh list                          # all worlds, active marked *
#   ./scripts/world.sh create <name> [seed]          # create + activate a new world
#   ./scripts/world.sh switch <name>                 # activate an existing world
#   ./scripts/world.sh import <file|folder> [name]   # import as a new world + activate
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

PROPS=data/server.properties
BACKUP_CFG=backup/config.yml

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

prop_set() { # key value — update or append in server.properties
    mkdir -p data
    touch "$PROPS"
    if grep -qE "^${1}=" "$PROPS"; then
        sed -i "s|^${1}=.*|${1}=${2}|" "$PROPS"
    else
        echo "${1}=${2}" >> "$PROPS"
    fi
}

active_world() {
    grep -E '^level-name=' "$PROPS" 2>/dev/null | head -n1 | cut -d= -f2- || true
}

valid_name() {
    [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9\ _\'-]{0,39}$ ]]
}

activate() { # name [seed] — point the server at this world and restart
    local name="$1" seed="${2-}"
    echo "==> Activating world: $name"
    $DOCKER compose stop bedrock
    prop_set level-name "$name"
    [[ -n "$seed" ]] && prop_set level-seed "$seed"
    # keep the backup service pointed at the active world
    sed -i "s|- /server/worlds/.*|- /server/worlds/${name}|" "$BACKUP_CFG"
    $DOCKER compose up -d bedrock
    $DOCKER compose restart backup >/dev/null 2>&1 || true
    echo "==> Done. Watch it come up with: $DOCKER compose logs -f bedrock"
}

cmd="${1:-list}"
case "$cmd" in
    list)
        act="$(active_world)"
        shopt -s nullglob
        for d in data/worlds/*/; do
            name="$(basename "$d")"
            [[ "$name" == *.bak.* ]] && continue
            marker=" "; [[ "$name" == "$act" ]] && marker="*"
            printf '%s %s  (%s)\n' "$marker" "$name" "$(du -sh "$d" | cut -f1)"
        done
        ;;

    create)
        name="${2:?Usage: $0 create <name> [seed]}"
        seed="${3:-}"
        valid_name "$name" || { echo "Invalid name (letters, digits, spaces, _ ' -)"; exit 1; }
        [[ -d "data/worlds/$name" ]] && { echo "World '$name' already exists — use: $0 switch \"$name\""; exit 1; }
        # empty seed = random
        prop_set level-seed "$seed"
        activate "$name"
        ;;

    switch)
        name="${2:?Usage: $0 switch <name>}"
        [[ -d "data/worlds/$name" ]] || { echo "No such world: $name (see: $0 list)"; exit 1; }
        [[ "$name" == "$(active_world)" ]] && { echo "'$name' is already active."; exit 0; }
        activate "$name"
        ;;

    import)
        src="${2:?Usage: $0 import <file.mcworld|file.zip|folder> [name]}"
        want="${3:-}"

        TMP="$(mktemp -d)"
        trap 'rm -rf "$TMP"' EXIT
        case "$src" in
            *.mcworld|*.zip)
                command -v unzip >/dev/null || { echo "unzip is required: sudo apt-get install unzip"; exit 1; }
                unzip -q "$src" -d "$TMP/extracted"
                STAGED="$TMP/extracted"
                if [[ ! -f "$STAGED/level.dat" ]]; then
                    INNER="$(find "$STAGED" -maxdepth 2 -name level.dat -printf '%h\n' | head -n1 || true)"
                    [[ -n "$INNER" ]] && STAGED="$INNER"
                fi
                ;;
            *) STAGED="$src" ;;
        esac
        [[ -f "$STAGED/level.dat" ]] || { echo "No level.dat in '$src' — not a Bedrock world?"; exit 1; }

        # name: explicit > levelname.txt > file name
        name="$want"
        [[ -z "$name" && -f "$STAGED/levelname.txt" ]] && name="$(tr -d '\r\n' < "$STAGED/levelname.txt")"
        [[ -z "$name" ]] && { name="$(basename "$src")"; name="${name%.*}"; }
        valid_name "$name" || { echo "Invalid world name '$name' — pass one: $0 import <file> <name>"; exit 1; }
        [[ -d "data/worlds/$name" ]] && { echo "World '$name' already exists — pass another name: $0 import <file> <name>"; exit 1; }

        mkdir -p data/worlds
        cp -a "$STAGED" "data/worlds/$name"
        echo "==> Imported as data/worlds/$name"
        activate "$name"
        ;;

    *)
        sed -n '3,10p' "$0" | sed 's/^# \{0,1\}//'
        exit 1
        ;;
esac
