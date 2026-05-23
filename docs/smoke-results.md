# IMD-60352 — Smoke Benchmark Results

**Status:** abbreviated smoke run, not the full Week 3 deliverable
**Date:** 2026-05-23
**Fixture:** 100k edges (33,333 OL events), power-law, 20 namespaces
**Scenarios:** `steady_write` and `read_only_baseline` only, 60s each at 100 rps
**Stack:** local docker-compose ([benchmark/docker-compose.yml](../benchmark/docker-compose.yml))

The full PoC plan calls for 5M edges and 30-min scenarios at 300 rps with
burst tests on top. These numbers are a sanity check, not the final report.

## Loader throughput (Python `generate.py --load`, concurrency=8)

| Backend | Events/sec | Time for 33k |
| --- | --- | --- |
| lineage-svc | **110** | 5m 02s |
| Marquez | **33** | 16m 28s |

→ lineage-svc ingests **3.3×** faster than Marquez on the same loader.

## k6: `steady_write` @ 100 rps × 60s

| Metric | lineage-svc | Marquez | Ratio |
| --- | --- | --- | --- |
| write p95 | **8 ms** | **21,190 ms** | **2,649× faster** |
| max | 49 ms | 34,990 ms | |
| error rate | 0.0% | 29.3% (666 / 2,273) | |
| dropped iterations | 0 | 3,728 | |
| sustained rate | 100/s | 35/s (couldn't keep up) | |

Marquez is so slow that the constant-arrival-rate executor drops 3,728 of
the 6,001 scheduled iterations.

## k6: `read_only_baseline` @ 100 rps × 60s

| Metric | lineage-svc | Marquez | Ratio |
| --- | --- | --- | --- |
| read direct p95 | **4 ms** | **285.8 ms** | **71× faster** |
| read depth=3 p95 | **4 ms** | **287 ms** | **72× faster** |
| read depth=10 p95 | **4 ms** | **316 ms** | **79× faster** |
| iteration_duration p95 | 4.27 ms | 292 ms | |

Both backends were queried against the same loaded fixture (URNs differ
only by separator — lineage-svc uses `/`, Marquez uses `:`). Power-law
sampling means ~50–80% of queries hit existing nodes.

## Score vs Definition of Done

| # | Target | lineage-svc smoke | Pass? |
| --- | --- | --- | --- |
| 1 | Write throughput ≥ 300/s, zero backlog | **Not tested at 300/s yet (smoke = 100/s)** | _pending_ |
| 2 | Write p95 < 50 ms | 8 ms | ✅ |
| 3 | Read p95 `direct` < 50 ms | 4 ms | ✅ |
| 4 | Read p95 depth=3 < 100 ms | 4 ms | ✅ |
| 5 | Read p95 depth=10 < 500 ms | 4 ms | ✅ |
| 6 | Read p99 depth=10 < 2,000 ms | < 10 ms | ✅ |
| 7 | Postgres CPU < 50% under 10x | not measured at 10x yet | _pending_ |
| 8 | Sequential scans = 0 | not yet sampled | _pending_ |
| 9 | 5xx error rate < 0.1% | 0% | ✅ |

**6 of 9 metrics provisionally passing**, 3 require the full 5M-edge / 300-rps
run. Marquez fails write p95 by **424×** and read p95 by **6×** even at 100 rps.

## Next steps to close out the PoC

1. **Loader perf** — Python loader caps out at ~110/s on lineage-svc (likely
   GIL + per-request HTTP overhead). Rewrite as async or use `wrk`/`vegeta`
   for the 5M-edge fixture load.
2. **5M-edge fixture** — generate + load into both backends.
3. **Full scenarios** — 6 × 2 = 12 runs, 30 min each, at the documented rates
   (300/s steady, 1000/s burst, mixed 100 rps reads).
4. **Correctness diff harness** — needs a URN sample list extracted from
   Marquez (`/api/v1/namespaces/<ns>/datasets`) since random sampling misses
   ~30% of the existing graph.
5. **Recovery test** — `bash benchmark/recovery_test.sh`.

## Reproduction

```bash
docker compose -f benchmark/docker-compose.yml up -d --build
LINEAGE_DATABASE_URL="postgresql+asyncpg://lineage:lineage@localhost:5433/lineage" \
  alembic upgrade head

python benchmark/fixtures/generate.py --edges 100000 --out fixture-100k.ndjson
python benchmark/fixtures/generate.py --load --input fixture-100k.ndjson \
  --target http://localhost:8000 --concurrency 8
python benchmark/fixtures/generate.py --load --input fixture-100k.ndjson \
  --target http://localhost:5000 --concurrency 8

# k6 via docker (Git Bash on Windows: prefix with MSYS_NO_PATHCONV=1)
MSYS_NO_PATHCONV=1 docker run --rm -i --network benchmark_default \
  -v "$(pwd)/benchmark:/bench" \
  -e SCENARIO=steady_write -e BACKEND=lineage \
  -e TARGET=http://lineage-svc:8000 \
  -e OVERRIDE_DURATION=60s -e OVERRIDE_RATE=100 \
  grafana/k6 run --summary-export=/bench/results/steady_write_lineage.json \
  /bench/k6/scenarios.js
```

Raw k6 summaries: [benchmark/results/](../benchmark/results/)
