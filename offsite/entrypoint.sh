#!/bin/sh
#
# Default: run crond with the schedule from OFFSITE_CRON.
# Any arguments override that, e.g.:
#   docker compose run --rm offsite offsite-backup     # back up right now
#   docker compose run --rm offsite restic snapshots   # inspect the repo
#
set -e

if [ $# -gt 0 ]; then
    exec "$@"
fi

CRON="${OFFSITE_CRON:-30 3 * * *}"
# Route cron job output to the container log
echo "$CRON /usr/local/bin/offsite-backup >> /proc/1/fd/1 2>&1" > /etc/crontabs/root
echo "Off-site backup scheduled: $CRON (TZ=${TZ:-UTC})"
exec crond -f -l 8
