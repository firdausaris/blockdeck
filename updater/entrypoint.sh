#!/bin/sh
#
# Default: run crond with the schedule from UPDATE_CRON.
# Any arguments override that, e.g.:
#   docker compose run --rm updater check-update   # check & update right now
#
set -e

if [ $# -gt 0 ]; then
    exec "$@"
fi

CRON="${UPDATE_CRON:-15 * * * *}"
# Route cron job output to the container log
echo "$CRON /usr/local/bin/check-update >> /proc/1/fd/1 2>&1" > /etc/crontabs/root
echo "Update check scheduled: $CRON (TZ=${TZ:-UTC})"
exec crond -f -l 8
