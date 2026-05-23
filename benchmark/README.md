# Benchmark Harness

Side-by-side load tests for `data-lineage` and Marquez under identical 10x prod load (IMD-60352).

## Layout

```
benchmark/
├── docker-compose.yml      # data-lineage + Marquez + Postgres x2 + Prometheus + Grafana
├── fixtures/
│   └── generate.py         # synthetic power-law graph generator (default 5M edges)
├── k6/
│   ├── scenarios.js        # all six k6 scenarios in one file (run one at a time via env)
│   └── lib/
│       └── urn.js          # URN helpers shared by scenarios
├── grafana/
│   └── provisioning/       # datasources + dashboards baked in
└── prometheus/
    └── prometheus.yml      # scrapes both services
```

## Quickstart

```bash
# 1. Bring up both services side-by-side
docker compose -f benchmark/docker-compose.yml up -d --build

# 2. Generate fixture (default 5M edges, power-law, depth ~8)
python benchmark/fixtures/generate.py --edges 5_000_000 --out /tmp/fixture.ndjson

# 3. Load fixture into BOTH backends
python benchmark/fixtures/generate.py --load --target http://localhost:8000 --input /tmp/fixture.ndjson
python benchmark/fixtures/generate.py --load --target http://localhost:5000 --input /tmp/fixture.ndjson

# 4. Run a scenario against data-lineage, then against Marquez
SCENARIO=steady_write TARGET=http://localhost:8000 k6 run benchmark/k6/scenarios.js
SCENARIO=steady_write TARGET=http://localhost:5000 k6 run benchmark/k6/scenarios.js

# 5. Compare in Grafana (http://localhost:3000, anonymous viewer)
```

## Scenarios

| SCENARIO env value | Profile | Purpose |
| --- | --- | --- |
| `steady_write` | const 300 events/s × 30 min | stability, backlog growth |
| `burst_write` | 0 → 1000/s → 0 over 10 min | backpressure |
| `steady_read` | const 100 rps mixed (70/20/10 direct/d3/d10) | read latency under write |
| `read_only_baseline` | 100 rps mixed, no write | isolate write overhead |
| `cold_read` | 1 rps after a service restart | cold cache latency |
| `deep_read` | 5 rps depth=10–50 | worst-case traversal |

## Pass/fail targets (must beat Marquez on ALL 9)

| Metric | data-lineage target |
| --- | --- |
| Write throughput sustained | ≥ 300 events/s, zero backlog |
| Write p95 | < 50 ms |
| Read p95 `direct` | < 50 ms |
| Read p95 depth=3 | < 100 ms |
| Read p95 depth=10 | < 500 ms |
| Read p99 depth=10 | < 2,000 ms |
| Postgres CPU under 10x | < 50% |
| Sequential scans on `lineage_edge` | 0 |
| 5xx error rate | < 0.1% |
