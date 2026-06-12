#!/usr/bin/env bash
#
# Check Mojang for a new Bedrock server release. If one is out: warn the
# players in-game, then restart the server container — with VERSION=LATEST
# the itzg image downloads the new release on startup.
#
set -euo pipefail

LINKS_URL="${DOWNLOAD_LINKS_URL:-https://net.web.minecraft-services.net/api/v1.0/download/links}"
SERVER_CONTAINER="${SERVER_CONTAINER:-bedrock}"
WARN_MINUTES="${UPDATE_WARN_MINUTES:-5}"

say() {
    # Warnings are best-effort; never let them block the update itself
    docker exec "$SERVER_CONTAINER" send-command say "$*" 2>/dev/null || true
}

if [[ "${VERSION:-LATEST}" != "LATEST" ]]; then
    echo "VERSION is pinned to '${VERSION}' in .env; skipping update check."
    exit 0
fi

# Latest release, from the same API the server image itself uses
latest_url="$(curl -fsSL "$LINKS_URL" \
    | jq -r '.result.links[] | select(.downloadType=="serverBedrockLinux") | .downloadUrl')"
latest="$(sed -nE 's/.*bedrock-server-([0-9.]+)\.zip.*/\1/p' <<< "$latest_url")"
if [[ -z "$latest" ]]; then
    echo "ERROR: could not determine the latest version from $LINKS_URL"
    exit 1
fi

# Installed version: the image keeps the binary as bedrock_server-<version>
installed="$(printf '%s\n' /server/bedrock_server-* 2>/dev/null \
    | sed -n 's/.*bedrock_server-//p' | sort -V | tail -n1)"
if [[ -z "$installed" ]]; then
    echo "ERROR: no bedrock_server-<version> binary found in /server" \
         "(has the server started at least once?)"
    exit 1
fi

if [[ "$installed" == "$latest" ]]; then
    echo "Up to date ($installed)."
    exit 0
fi

echo "Update available: $installed -> $latest"

if ! docker ps --format '{{.Names}}' | grep -qx "$SERVER_CONTAINER"; then
    echo "Server container is not running; it will update on its next start."
    exit 0
fi

if (( WARN_MINUTES > 0 )); then
    echo "Warning players, updating in $WARN_MINUTES minute(s) ..."
    say "Server is updating to $latest in $WARN_MINUTES minute(s)."
    if (( WARN_MINUTES > 1 )); then
        sleep $(( (WARN_MINUTES - 1) * 60 ))
        say "Server is updating in 1 minute!"
    fi
    sleep 60
fi
say "Updating now - back in a minute!"

echo "Restarting $SERVER_CONTAINER ..."
docker restart "$SERVER_CONTAINER" > /dev/null

# Verify the server comes back up on the new version
for _ in $(seq 1 36); do
    sleep 5
    if docker logs --since 3m "$SERVER_CONTAINER" 2>&1 | grep -q "Server started"; then
        echo "Update OK: server is back up on $latest."
        exit 0
    fi
done

echo "ERROR: server did not report 'Server started' within 3 minutes" \
     "after the update to $latest. Check: docker logs $SERVER_CONTAINER"
exit 1
