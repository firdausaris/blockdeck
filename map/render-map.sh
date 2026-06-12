#!/usr/bin/env bash
#
# Render a web map from the newest world backup. Rendering from a backup
# snapshot (not the live world) is required: the server writes to its
# LevelDB continuously and reading it live can crash the renderer.
#
set -euo pipefail

latest="$(ls -1t /backups/*.mcworld 2>/dev/null | head -n1 || true)"
if [[ -z "$latest" ]]; then
    echo "No .mcworld backups found - the map renders from backups, trigger one first."
    exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
unzip -q "$latest" -d "$work/world"

echo "Rendering map from $(basename "$latest") ..."
out="/map/.render-$$"
rm -rf "$out"
log="$work/render.log"
if ! /opt/unmined/unmined-cli web render --world="$work/world" --output="$out" 2>&1 | tee "$log"; then
    if grep -q "Found 0 chunks" "$log"; then
        echo "World has no generated terrain yet (nobody has played on it) - nothing to render."
        exit 0
    fi
    echo "Map render failed; see output above."
    exit 1
fi

# The generated entry point is unmined.index.html; add a copy that
# static servers pick up by default
[[ -f "$out/unmined.index.html" ]] && cp "$out/unmined.index.html" "$out/index.html"

# Swap the finished render into place
rm -rf /map/current.old
[[ -d /map/current ]] && mv /map/current /map/current.old
mv "$out" /map/current
rm -rf /map/current.old

echo "Map updated from $(basename "$latest") at $(date)"
