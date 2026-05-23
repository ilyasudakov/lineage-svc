#!/usr/bin/env bash
# Hard test: chaos / fault injection.
#
# Scenario 1: kill data-lineage app mid-write, restart, verify recovery
# Scenario 2: kill lineage-pg mid-write, wait for healthcheck, verify recovery
#             and no data loss (sample count before and after)
#
# Assumes the side-by-side stack is up and a writer is producing constant load.
# We launch a background writer using fixtures/generate.py --load and kill the
# target service mid-flight.
set -euo pipefail

COMPOSE="docker compose -f $(dirname "$0")/../docker-compose.yml"
TARGET="${TARGET:-http://localhost:8000}"
DSN="${DSN:-postgresql://lineage:lineage@localhost:5433/lineage}"
HEALTH_URL="${HEALTH_URL:-${TARGET}/health}"
FIXTURE="$(dirname "$0")/_chaos_fixture.ndjson"
RESULTS="$(dirname "$0")/../results"
mkdir -p "$RESULTS"

PYTHON="${PYTHON:-E:/projects/data-lineage/.venv/Scripts/python.exe}"

count_rows() {
  "$PYTHON" -c "
import psycopg
with psycopg.connect('$DSN') as c, c.cursor() as cur:
    cur.execute('SELECT COUNT(*) FROM lineage_edge')
    print(cur.fetchone()[0])
"
}

# Small fixture for background writer.
echo "Generating chaos fixture (60k events)..."
"$PYTHON" "$(dirname "$0")/../fixtures/generate.py" --edges 180000 --out "$FIXTURE" >/dev/null

run_scenario() {
  local name="$1"
  local service="$2"
  echo
  echo "===== chaos scenario: $name ====="

  rows_before=$(count_rows)
  echo "  rows before:   $rows_before"

  echo "  starting background writer..."
  "$PYTHON" "$(dirname "$0")/../fixtures/generate.py" --load \
    --input "$FIXTURE" --target "$TARGET" --concurrency 4 \
    > "$RESULTS/_chaos_${name}_writer.log" 2>&1 &
  WRITER_PID=$!

  sleep 8  # let some rows in

  echo "  killing $service..."
  kill_t0=$(date +%s)
  $COMPOSE kill "$service"
  echo "  restarting $service..."
  $COMPOSE up -d "$service" >/dev/null

  echo "  polling $HEALTH_URL for recovery..."
  recovered=false
  for _ in $(seq 1 60); do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      recovered=true
      break
    fi
    sleep 1
  done
  kill_elapsed=$(( $(date +%s) - kill_t0 ))

  if [ "$recovered" = false ]; then
    echo "  FAIL: did not recover within 60s"
    kill $WRITER_PID 2>/dev/null || true
    return 1
  fi
  echo "  recovered in ${kill_elapsed}s"

  # Let writer finish or terminate.
  wait $WRITER_PID 2>/dev/null || true

  rows_after=$(count_rows)
  echo "  rows after:    $rows_after"
  delta=$(( rows_after - rows_before ))
  echo "  rows added:    $delta"

  if [ "$delta" -lt 100 ]; then
    echo "  FAIL: writer added too few rows ($delta), recovery may have lost data"
    return 1
  fi
  if [ "$kill_elapsed" -gt 30 ]; then
    echo "  FAIL: recovery took ${kill_elapsed}s, target < 30s"
    return 1
  fi
  echo "  PASS"
  return 0
}

set +e
run_scenario "kill_app" data-lineage
APP_RC=$?
run_scenario "kill_pg" lineage-pg
PG_RC=$?
set -e

rm -f "$FIXTURE"

echo
echo "============================================================"
echo "  kill_app: $([ $APP_RC -eq 0 ] && echo PASS || echo FAIL)"
echo "  kill_pg:  $([ $PG_RC -eq 0 ] && echo PASS || echo FAIL)"
echo "============================================================"

exit $(( APP_RC + PG_RC ))
