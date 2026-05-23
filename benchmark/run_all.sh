#!/usr/bin/env bash
# Run all six benchmark scenarios against both backends, dumping summary JSON
# from k6 per (scenario, backend) pair into ./results/.
#
# Assumes:
#   - docker compose -f benchmark/docker-compose.yml up -d  (already running)
#   - Fixture already loaded into both backends
#   - k6 installed locally (https://k6.io/docs/getting-started/installation)
#
# Usage:
#   bash benchmark/run_all.sh                       # all scenarios, both backends
#   bash benchmark/run_all.sh steady_write          # one scenario, both backends
#   TARGETS="lineage" bash benchmark/run_all.sh     # restrict to one backend
set -euo pipefail

SCENARIOS=(${*:-steady_write burst_write steady_read read_only_baseline cold_read deep_read})
TARGETS=${TARGETS:-"lineage marquez"}

declare -A URL
URL[lineage]="http://localhost:8000"
URL[marquez]="http://localhost:5000"

RESULTS_DIR="$(dirname "$0")/results"
mkdir -p "$RESULTS_DIR"

for scenario in "${SCENARIOS[@]}"; do
  for backend in $TARGETS; do
    target="${URL[$backend]}"
    out="$RESULTS_DIR/${scenario}_${backend}.json"
    echo
    echo "=== $scenario → $backend ($target) ==="
    SCENARIO="$scenario" TARGET="$target" \
      k6 run \
        --summary-export "$out" \
        --quiet \
        "$(dirname "$0")/k6/scenarios.js"
    echo "  → $out"
  done
done

echo
echo "All scenarios complete. Summaries in $RESULTS_DIR/"
ls -la "$RESULTS_DIR/"
