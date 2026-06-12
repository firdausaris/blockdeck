#!/usr/bin/env bash
#
# Send a console command to the running server.
#
# Usage:
#   ./scripts/console.sh list
#   ./scripts/console.sh say Backup starting in 5 minutes
#
# For an interactive console use:  docker attach bedrock
# (detach with Ctrl-p Ctrl-q — NOT Ctrl-c, which stops the server)
#
set -euo pipefail

[[ $# -ge 1 ]] || { echo "Usage: $0 <command...>"; exit 1; }

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

exec $DOCKER exec bedrock send-command "$@"
