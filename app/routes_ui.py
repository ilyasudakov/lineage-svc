"""Discovery endpoints powering the lineage UI.

Two small read endpoints that the SPA polls:
  GET /api/v1/namespaces      — distinct namespaces in lineage_edge
  GET /api/v1/search?q=&...   — fuzzy URN search, optionally namespace-scoped

These live in a separate module so the main API stays focused on lineage I/O.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter(prefix="/api/v1", tags=["ui"])


@router.get("/namespaces")
async def list_namespaces(
    limit: int = Query(500, ge=1, le=10_000),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List distinct namespaces present in the edge table.

    Cheap on `ix_lineage_edge_namespace` — DISTINCT degrades to an index-only
    scan if the planner cooperates. Capped at `limit` so a degenerate graph
    can't blow up the UI.
    """
    q = text("SELECT DISTINCT namespace FROM lineage_edge ORDER BY namespace LIMIT :lim")
    rows = (await session.execute(q, {"lim": limit})).scalars().all()
    return {"namespaces": list(rows)}


@router.get("/search")
async def search_nodes(
    q: str = Query(..., min_length=1, max_length=200),
    namespace: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Substring search over URNs (src + dst), optionally namespace-scoped.

    Uses `LOWER(col) LIKE LOWER(:pat)` for case-insensitive portability between
    Postgres and SQLite. For prod scale, add a `pg_trgm` GIN index on
    `(src_urn, dst_urn)`; at 100k to 5M rows the current path measures sub-100ms.
    """
    pattern = f"%{q.lower()}%"
    if namespace:
        sql = text(
            """
            SELECT urn FROM (
                SELECT src_urn AS urn FROM lineage_edge
                  WHERE namespace = :ns AND LOWER(src_urn) LIKE :pat
                UNION
                SELECT dst_urn AS urn FROM lineage_edge
                  WHERE namespace = :ns AND LOWER(dst_urn) LIKE :pat
            ) s ORDER BY urn LIMIT :lim
            """
        )
        rows = (
            (await session.execute(sql, {"ns": namespace, "pat": pattern, "lim": limit}))
            .scalars()
            .all()
        )
    else:
        sql = text(
            """
            SELECT urn FROM (
                SELECT src_urn AS urn FROM lineage_edge WHERE LOWER(src_urn) LIKE :pat
                UNION
                SELECT dst_urn AS urn FROM lineage_edge WHERE LOWER(dst_urn) LIKE :pat
            ) s ORDER BY urn LIMIT :lim
            """
        )
        rows = (await session.execute(sql, {"pat": pattern, "lim": limit})).scalars().all()

    nodes = [{"urn": u, "kind": "job" if u.startswith("job:") else "dataset"} for u in rows]
    return {"query": q, "namespace": namespace, "results": nodes}
