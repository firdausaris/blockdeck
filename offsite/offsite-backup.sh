#!/usr/bin/env bash
#
# Push ./backups to the restic repository and apply the retention policy.
# Runs on the OFFSITE_CRON schedule; can also be invoked manually:
#   docker compose run --rm offsite offsite-backup
#
set -euo pipefail

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is not set in .env}"
: "${RESTIC_PASSWORD:?RESTIC_PASSWORD is not set in .env}"

# Stage the (read-only mounted) SSH key with the permissions ssh insists on
if [[ -f /ssh/id_ed25519 || -f /ssh/id_rsa ]]; then
    mkdir -p ~/.ssh && chmod 700 ~/.ssh
    cp /ssh/id_* ~/.ssh/ && chmod 600 ~/.ssh/id_*
    printf 'Host *\n  StrictHostKeyChecking accept-new\n' > ~/.ssh/config
fi

echo "=== Off-site backup started: $(date) ==="

if ! restic cat config >/dev/null 2>&1; then
    echo "Repository not initialized yet, running restic init ..."
    restic init
fi

restic backup /backups --tag blockdeck
restic forget --tag blockdeck --prune \
    --keep-daily "${KEEP_DAILY:-7}" \
    --keep-weekly "${KEEP_WEEKLY:-4}" \
    --keep-monthly "${KEEP_MONTHLY:-6}"

echo "=== Off-site backup finished: $(date) ==="
