#!/bin/sh
#
# Default: run crond with the schedule from MAP_CRON.
# Any arguments override that, e.g.:
#   docker compose run --rm map render-map   # render right now
#
set -e

if [ $# -gt 0 ]; then
    exec "$@"
fi

CRON="${MAP_CRON:-30 4 * * *}"
# Route cron job output to the container log
echo "$CRON /usr/local/bin/render-map >> /proc/1/fd/1 2>&1" > /etc/crontabs/root
echo "Map render scheduled: $CRON (TZ=${TZ:-UTC})"
exec crond -f -l 8
