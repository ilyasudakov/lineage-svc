# Benchmark Methodology

## Goal

Demonstrate that `lineage-svc`'s edges-only schema is strictly faster than
Marquez's events/versions/runs schema under identical load, on identical
hardware, against identical data — per IMD-60352 Definition of Done:

> Outcome must show lineage-svc strictly better on all 9 perf metrics —
> otherwise PoC fails and we revisit approach.

## Environment

- **Host:** Windows 11, single workstation, Docker Desktop 4.x
- **Network:** docker-compose bridge `benchmark_default`, all containers
  on the same L2 segment, no external network calls during measurement
- **Stack:** [`benchmark/docker-compose.yml`](../../benchmark/docker-compose.yml)
  - `lineage-svc` — FastAPI + uvicorn (2 workers), 2 CPU / 2 GB cap
  - `lineage-pg` — Postgres 16, 4 CPU / 4 GB cap
  - `marquez` — `marquezproject/marquez:0.50.0`, 2 CPU / 2 GB cap
  - `marquez-pg` — Postgres 14, 4 CPU / 4 GB cap (matches what Marquez
    ships with, not bumped to 16 for compatibility)
  - `postgres-exporter` on each DB (ports 9187 / 9188)
  - `prometheus:v2.55.0` scraping both apps + both DBs every 5 s
  - `grafana:11.3.0` with provisioned side-by-side dashboard

Resource caps deliberately mirror each other so the comparison is fair —
no app gets more CPU than the other.

## Fixture

Generator: [`benchmark/fixtures/generate.py`](../../benchmark/fixtures/generate.py)

- **100,000 edges** (33,333 OpenLineage events; each event yields
  ~3 edges: `consumes` / `produces` / `derives_from`)
- **20 namespaces** (multi-tenancy mirrors prod: `{id}_ws_{id*7}`)
- **Dataset pool size:** ~10k (= edges // 10) — chosen so the power-law
  generator gets reuse and produces hub nodes, not a flat star graph
- **Power-law distribution** with α=1.5: small indices much more likely,
  producing the hub/leaf shape we see in real lineage graphs
- **Event shape:** standard OpenLineage RunEvent — same payload posted to
  both backends unchanged

The full PoC plan calls for 5 million edges; the smoke run used 100k to
validate the pipeline. The same generator can produce both.

## Load procedure

1. `docker compose up -d --build`
2. `alembic upgrade head` against `lineage-pg` (creates `lineage_edge` table)
3. Generate fixture NDJSON file
4. POST the same NDJSON line-by-line to **both** backends via the loader
   (Python threaded HTTP, concurrency=8)
5. Sanity-check via `curl /health` and a `/direct` query that data is present

The loader is intentionally simple Python — its throughput cap (~110 ev/s)
becomes a first comparative data point (see [results.md](results.md#loader)).

## Scenarios

All defined in [`benchmark/k6/scenarios.js`](../../benchmark/k6/scenarios.js).
The smoke run executed two of the six; the full Week 3 plan runs all six.

| Scenario | Profile | Purpose |
| --- | --- | --- |
| `steady_write` | const 300 ev/s × 30 min (smoke: 100/s × 60 s) | stability, backlog growth |
| `burst_write` | 0 → 1000/s → 0 over 10 min | backpressure |
| `steady_read` | const 100 rps mixed (70/20/10 direct/d3/d10) | read latency under write |
| `read_only_baseline` | const 100 rps mixed, no write (smoke: 60 s) | isolate write overhead |
| `cold_read` | 1 rps × 2 min after a service restart | cold cache latency |
| `deep_read` | 5 rps depth=10–50 × 10 min | worst-case traversal |

### k6 invocation

k6 ran via the official `grafana/k6` Docker image, joined to the same
network as the services — no port-forwarding latency:

```bash
docker run --rm -i --network benchmark_default \
  -v "$(pwd)/benchmark:/bench" \
  -e SCENARIO=steady_write -e BACKEND=lineage \
  -e TARGET=http://lineage-svc:8000 \
  -e OVERRIDE_DURATION=60s -e OVERRIDE_RATE=100 \
  grafana/k6 run --summary-export=/bench/results/steady_write_lineage.json \
  /bench/k6/scenarios.js
```

`BACKEND=lineage|marquez` switches both the URL shape
(`/api/v1/lineage/direct?node=` vs `/api/v1/lineage?nodeId=`) and the URN
separator (`dataset:ns/name` vs `dataset:ns:name`) so the same scenario
file drives both backends correctly.

## What we measure

Custom k6 trends report latency per request type — independent of
HTTP-level metrics, so we see lineage-svc's `/direct` latency separately
from a depth-10 traversal latency:

- `write_latency_ms`
- `read_direct_latency_ms`
- `read_depth3_latency_ms`
- `read_depth10_latency_ms`
- `errors` (counter, incremented when HTTP status ≥ 400)

k6 thresholds (pass/fail gates baked into the run) come straight from the
9 DoD targets:

```
write_latency_ms:          ["p(95)<50"]
read_direct_latency_ms:    ["p(95)<50"]
read_depth3_latency_ms:    ["p(95)<100"]
read_depth10_latency_ms:   ["p(95)<500", "p(99)<2000"]
errors:                    ["count<10000"]
```

## Correctness

Latency means nothing if the answers differ. The diff harness
([`benchmark/diff_harness.py`](../../benchmark/diff_harness.py)) compares
edge sets returned by both backends for the same sampled nodes:

- Pick N random URNs from the loaded fixture
- For each, call `/direct` on both backends
- Translate Marquez's `graph[].outEdges` into our `(src, dst, edge_type)`
  tuple shape (the adapter is in `diff_harness.py:marquez_direct`)
- `set(lineage_svc_edges) == set(marquez_edges)` → match, else mismatch
- Dump full report to `diff_report.json`

DoD requires 100% match across 1000 samples. This is pending until a
URN sample list extracted from Marquez (`/api/v1/namespaces/<ns>/datasets`)
is wired into the harness — the current random URN generator hits ~70–80%
of existing nodes, not the full graph.

## What this run does NOT prove

- Behaviour at 300 rps sustained or 1000 rps burst (smoke ran at 100 rps)
- Behaviour at 5M edges (smoke ran at 100k = 2% of target volume)
- Postgres CPU under prod-like load
- Cold-cache latency after restart
- Recovery after Postgres restart
- Correctness equality vs Marquez at scale

All of the above are scoped to the full Week 3 run.
