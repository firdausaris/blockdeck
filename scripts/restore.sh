#!/usr/bin/env bash
#
# Restore a world from the local backups folder.
#
# Usage:
#   ./scripts/restore.sh                  # restore the most recent backup
#   ./scripts/restore.sh <file.mcworld>   # restore a specific backup
#
# To restore from the off-site restic repository instead, first pull the
# files back (see "Restoring from off-site" in the README), then run this.
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [[ $# -ge 1 ]]; then
    FILE="$1"
else
    FILE="$(ls -1t backups/*.mcworld 2>/dev/null | head -n1 || true)"
    if [[ -z "$FILE" ]]; then
        echo "No .mcworld backups found in backups/"
        exit 1
    fi
fi

[[ -f "$FILE" ]] || { echo "Backup not found: $FILE"; exit 1; }

echo "Available backups (newest first):"
ls -1t backups/*.mcworld 2>/dev/null | head -n 10 | sed 's/^/  /'
echo
echo "About to restore: $FILE"
echo "The current world will be kept as a .bak folder."
read -r -p "Continue? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

exec ./scripts/import-world.sh "$FILE"
