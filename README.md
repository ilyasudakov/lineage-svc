# lineage-svc

Lightweight lineage service with an **edges-only schema** — PoC replacement candidate for Marquez.

**Jira:** [IMD-60352](https://improvado.atlassian.net/browse/IMD-60352)

## Why

Marquez's events/versions/runs schema becomes a bottleneck on graph reads (p95 `/lineage/direct` up to ~19s in prod, Postgres CPU 100-200%). This service stores lineage as a flat edge table so graph traversal is a single recursive CTE on indexed columns.

## Stack

- FastAPI + Uvicorn
- SQLAlchemy 2.x (async) + asyncpg
- PostgreSQL 16
- Alembic for migrations (added in PoC week 1)
- Prometheus client for metrics

## Schema

```sql
CREATE TABLE lineage_edge (
  src_urn     TEXT NOT NULL,
  dst_urn     TEXT NOT NULL,
  edge_type   TEXT NOT NULL,        -- 'produces' | 'consumes' | 'derives_from'
  job_urn     TEXT,
  run_id      TEXT,
  namespace   TEXT NOT NULL,
  metadata    JSONB,
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (src_urn, dst_urn, edge_type)
);
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/lineage` | OpenLineage-compatible ingest (mirror of Marquez endpoint) |
| GET  | `/api/v1/lineage/direct?node=<urn>` | Immediate neighbors (up + down) |
| GET  | `/api/v1/lineage?node=<urn>&depth=N&direction=upstream\|downstream\|both` | Recursive traversal |
| GET  | `/health` | Liveness |
| GET  | `/metrics` | Prometheus exposition |

## Run locally

```bash
docker compose up --build
curl http://localhost:8000/health
```

## Develop

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
ruff check .
```

## Status

PoC scope per IMD-60352 — table-level lineage only, three edge types (`produces` / `consumes` / `derives_from`).
Producer side (DTS) emits OL events unchanged; this service translates them to edges on ingest.
