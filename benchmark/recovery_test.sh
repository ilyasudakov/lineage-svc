#!/usr/bin/env bash
# Recovery test: restart lineage-pg, measure time until /health returns 200.
# Target: < 30s (per Definition of Done in IMD-60352).
set -euo pipefail

COMPOSE="docker compose -f $(dirname "$0")/docker-compose.yml"
HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"
TIMEOUT_S=${TIMEOUT_S:-60}

echo "Restarting lineage-pg..."
$COMPOSE restart lineage-pg

echo "Polling $HEALTH_URL (timeout ${TIMEOUT_S}s)..."
start=$(date +%s)
while true; do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    elapsed=$(( $(date +%s) - start ))
    echo "Healthy after ${elapsed}s"
    if [ "$elapsed" -lt 30 ]; then
      echo "PASS (< 30s)"
      exit 0
    else
      echo "FAIL (>= 30s)"
      exit 1
    fi
  fi
  elapsed=$(( $(date +%s) - start ))
  if [ "$elapsed" -gt "$TIMEOUT_S" ]; then
    echo "FAIL: did not recover within ${TIMEOUT_S}s"
    exit 1
  fi
  sleep 1
done
