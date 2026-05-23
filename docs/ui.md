# Lineage UI

A small single-page graph explorer for the edges stored in `lineage-svc`.
Lives at **`/ui`**, served by FastAPI itself — no separate frontend service.

## Stack

- Vanilla JS, no build step
- [cytoscape.js](https://js.cytoscape.org/) for graph rendering (loaded from CDN)
- Custom CSS, dark theme

The whole frontend is three static files under [`app/static/`](../app/static/):
`index.html`, `style.css`, `app.js`. Adding a feature = edit a file, refresh.

## Features

| | |
| --- | --- |
| Namespace filter | Pre-populated dropdown of distinct namespaces from `lineage_edge` |
| Fuzzy search | Case-insensitive substring match over src/dst URNs, optionally namespace-scoped |
| Direct neighbors view | `depth=1` shows just the immediate upstream + downstream |
| Recursive traversal | `depth=2..50` walks the recursive CTE, picks direction (upstream / downstream / both) |
| Click-to-recenter | Tap any node in the graph to make it the new pivot |
| Per-edge colors | `produces` (green), `consumes` (red), `derives_from` (dashed purple) |
| Node shapes | Dataset = circle, job = round-rectangle |
| Selected node stats | Upstream / downstream counts for the current node |

## Endpoints powering the UI

Defined in [`app/routes_ui.py`](../app/routes_ui.py).

```
GET /api/v1/namespaces?limit=500
  → {"namespaces": ["1_ws_7", "2_ws_14", ...]}

GET /api/v1/search?q=<substring>&namespace=<ns>&limit=50
  → {"query": "...", "namespace": "...", "results": [
        {"urn": "dataset:1_ws_7/...", "kind": "dataset"},
        {"urn": "job:1_ws_7/extract...", "kind": "job"}
     ]}
```

Search uses `LOWER(col) LIKE LOWER(:pat)` so it works against both
PostgreSQL and the SQLite test database. For production scale, add a
`pg_trgm` GIN index on `(src_urn, dst_urn)` to avoid the sequential
filter — measured sub-100 ms up to ~5M rows without it.

## Running

The UI is part of the main service, no separate process to run.

```bash
docker compose -f benchmark/docker-compose.yml up -d --build
open http://localhost:8000/ui
```

In CI / fresh checkout, the container auto-runs `alembic upgrade head` on
startup via [`docker-entrypoint.sh`](../docker-entrypoint.sh) — no manual
migration step needed anymore.

## What this UI is NOT

- Not a production-grade lineage browser. The old Marquez UI has table
  search, run history, and per-dataset facets — none of that is here yet.
- Not access-controlled. Anyone who can reach the service can browse the
  whole graph. Multi-tenant scoping by login is a follow-up.
- Not a perf product. cytoscape's COSE layout is fine up to a few hundred
  nodes per view; bigger subgraphs will look like spaghetti. Use the
  depth slider to keep views readable.
