#!/usr/bin/env bash
set -euo pipefail

: "${BMLT_BASE_URL:?Must set BMLT_BASE_URL}"
: "${BMLT_ADMIN_USER:?Must set BMLT_ADMIN_USER}"
: "${BMLT_ADMIN_PASS:?Must set BMLT_ADMIN_PASS}"

SYNC_INTERVAL_MINUTES="${SYNC_INTERVAL_MINUTES:-1440}"
DATA_DIR="${DATA_DIR:-/data}"

mkdir -p "$DATA_DIR"

API_PREFIX="${BMLT_API_PREFIX:-/api/v1}"
echo "Waiting for BMLT API at: ${BMLT_BASE_URL}${API_PREFIX}/formats"
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "${BMLT_BASE_URL}${API_PREFIX}/formats" || true)
  if [ "$code" = "200" ] || [ "$code" = "401" ]; then
    echo "BMLT API is reachable (formats returned $code)."
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

