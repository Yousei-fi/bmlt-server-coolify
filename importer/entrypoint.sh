#!/usr/bin/env bash
set -euo pipefail

: "${BMLT_BASE_URL:?Must set BMLT_BASE_URL}"
: "${BMLT_ADMIN_USER:?Must set BMLT_ADMIN_USER}"
: "${BMLT_ADMIN_PASS:?Must set BMLT_ADMIN_PASS}"

SYNC_INTERVAL_MINUTES="${SYNC_INTERVAL_MINUTES:-1440}"
DATA_DIR="${DATA_DIR:-/data}"

mkdir -p "$DATA_DIR"

echo "Waiting for BMLT API at: ${BMLT_BASE_URL}"
for i in $(seq 1 60); do
  if curl -fsSL "${BMLT_BASE_URL}/api/v1/status" >/dev/null 2>&1; then
    echo "BMLT API is reachable."
    break
  fi
  sleep 5
done

CRON_FILE="/app/crontab"
echo "*/${SYNC_INTERVAL_MINUTES} * * * * python3 /app/sync_wp_to_bmlt_v4.py" > "$CRON_FILE"

echo "Running initial sync..."
python3 /app/sync_wp_to_bmlt_v4.py || true

echo "Starting scheduler: every ${SYNC_INTERVAL_MINUTES} minutes"
exec /usr/local/bin/supercronic "$CRON_FILE"

