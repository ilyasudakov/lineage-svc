# How to Reproduce the Smoke Benchmark

End-to-end runbook. ~30 minutes wall time on a workstation with Docker
Desktop. Replace `E:/projects/lineage-svc` with your checkout path
throughout.

## Prerequisites

- Docker Desktop ≥ 4.x with at least 16 GB allocated
- Python 3.12 with venv (for the loader + Alembic from host)
- `curl`, `bash` (Git Bash on Windows)
- No k6 install needed — runs as a Docker image

## Step 1 — Bring up the side-by-side stack

```bash
cd E:/projects/lineage-svc
docker compose -f benchmark/docker-compose.yml up -d --build
```

Wait ~30 s for both Postgreses to report healthy:

```bash
docker compose -f benchmark/docker-compose.yml ps
# expect both *-pg containers (healthy), lineage-svc healthy, marquez running
```

Sanity-check each backend responds:

```bash
curl -s http://localhost:8000/health        # {"status":"ok"}
curl -s http://localhost:5000/api/v1/namespaces | head -c 200
```

## Step 2 — Create the lineage-svc schema

The Docker image does not bundle Alembic migrations. Run them from the
host against the exposed port 5433:

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]" alembic
LINEAGE_DATABASE_URL="postgresql+asyncpg://lineage:lineage@localhost:5433/lineage" \
  .venv/Scripts/python.exe -m alembic upgrade head
# expect: "Running upgrade  -> 0001_initial, initial lineage_edge"
```

## Step 3 — Generate the fixture

```bash
.venv/Scripts/python.exe benchmark/fixtures/generate.py \
  --edges 100000 \
  --out benchmark/fixture-100k.ndjson
# ~0.4 s; produces 33,333 NDJSON lines
```

## Step 4 — Load fixture into both backends

⚠️ Concurrency=8 is intentional — concurrency=32 trips lineage-svc's
HTTP connection ceiling. Keep them equal for a fair comparison.

```bash
# ~5 min
.venv/Scripts/python.exe benchmark/fixtures/generate.py --load \
  --input benchmark/fixture-100k.ndjson \
  --target http://localhost:8000 --concurrency 8

# ~16 min
.venv/Scripts/python.exe benchmark/fixtures/generate.py --load \
  --input benchmark/fixture-100k.ndjson \
  --target http://localhost:5000 --concurrency 8
```

The throughput each loader reports is the **first comparative data point**:
~110 ev/s for lineage-svc vs ~33 ev/s for Marquez.

## Step 5 — Run k6 scenarios

`MSYS_NO_PATHCONV=1` is only needed on Git Bash for Windows (prevents
MSYS from rewriting `/bench/` to `C:/Program Files/Git/bench/`).

### Steady write (60 s @ 100 rps)

```bash
mkdir -p benchmark/results

MSYS_NO_PATHCONV=1 docker run --rm -i --network benchmark_default \
  -v "E:/projects/lineage-svc/benchmark:/bench" \
  -e SCENARIO=steady_write -e BACKEND=lineage \
  -e TARGET=http://lineage-svc:8000 \
  -e OVERRIDE_DURATION=60s -e OVERRIDE_RATE=100 \
  grafana/k6 run --quiet \
  --summary-export=/bench/results/steady_write_lineage.json \
  /bench/k6/scenarios.js

MSYS_NO_PATHCONV=1 docker run --rm -i --network benchmark_default \
  -v "E:/projects/lineage-svc/benchmark:/bench" \
  -e SCENARIO=steady_write -e BACKEND=marquez \
  -e TARGET=http://marquez:5000 \
  -e OVERRIDE_DURATION=60s -e OVERRIDE_RATE=100 \
  grafana/k6 run --quiet \
  --summary-export=/bench/results/steady_write_marquez.json \
  /bench/k6/scenarios.js
```

### Read baseline (60 s @ 100 rps)

```bash
MSYS_NO_PATHCONV=1 docker run --rm -i --network benchmark_default \
  -v "E:/projects/lineage-svc/benchmark:/bench" \
  -e SCENARIO=read_only_baseline -e BACKEND=lineage \
  -e TARGET=http://lineage-svc:8000 \
  -e OVERRIDE_DURATION=60s -e OVERRIDE_RATE=100 \
  grafana/k6 run --quiet \
  --summary-export=/bench/results/read_lineage.json \
  /bench/k6/scenarios.js

MSYS_NO_PATHCONV=1 docker run --rm -i --network benchmark_default \
  -v "E:/projects/lineage-svc/benchmark:/bench" \
  -e SCENARIO=read_only_baseline -e BACKEND=marquez \
  -e TARGET=http://marquez:5000 \
  -e OVERRIDE_DURATION=60s -e OVERRIDE_RATE=100 \
  grafana/k6 run --quiet \
  --summary-export=/bench/results/read_marquez.json \
  /bench/k6/scenarios.js
```

## Step 6 — Inspect results

```bash
ls benchmark/results/
# read_lineage.json   read_marquez.json
# steady_write_lineage.json   steady_write_marquez.json
```

Quick p95 extract:

```bash
.venv/Scripts/python.exe -c "
import json
for f in ['steady_write_lineage', 'steady_write_marquez',
          'read_lineage', 'read_marquez']:
    d = json.load(open(f'benchmark/results/{f}.json'))
    print(f'\n{f}:')
    for k, v in d['metrics'].items():
        if 'latency' in k or k == 'errors':
            print(f'  {k:30s} p95={v.get(\"p(95)\", 0):.1f}  count={v.get(\"count\", 0)}')
"
```

Or open Grafana at <http://localhost:3000> (anonymous viewer enabled)
and select the `lineage-vs-marquez` dashboard.

## Step 7 — Tear down

```bash
docker compose -f benchmark/docker-compose.yml down -v
```

`-v` removes the Postgres volumes — important when retrying with a
different fixture, otherwise stale data poisons the comparison.

## Stepping up to the full Week 3 run

The smoke run uses `OVERRIDE_DURATION=60s OVERRIDE_RATE=100`. Drop those
env vars to run each scenario at its full duration and rate from the
ticket. Expect ~6 hours total for all 6 scenarios × 2 backends.

For the 5M-edge fixture, also bump generation:

```bash
.venv/Scripts/python.exe benchmark/fixtures/generate.py --edges 5000000 \
  --out benchmark/fixture-5M.ndjson
# expect ~5 minutes generation, ~20 GB output
```

And load using a faster loader — the Python `generate.py --load` would
take 4–5 hours at 110 ev/s for 5M / 3 = 1.67M events. Recommend
[`vegeta`](https://github.com/tsenart/vegeta) or rewriting the loader
in async httpx.
