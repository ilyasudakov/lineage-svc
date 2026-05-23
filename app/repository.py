from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LineageEdge
from app.schemas import Direction, Edge

# Chunk size for INSERT...VALUES — keeps individual statements under
# Postgres' protocol limits (parameters ≤ 65535) and avoids unbounded memory
# while still amortising the round trip. With 7 columns per row, 5_000 rows
# = 35_000 parameters — comfortably below the cap.
_UPSERT_CHUNK = 5_000


def _row(e: Edge) -> dict:
    return {
        "src_urn": e.src_urn,
        "dst_urn": e.dst_urn,
        "edge_type": e.edge_type,
        "job_urn": e.job_urn,
        "run_id": e.run_id,
        "namespace": e.namespace,
        "metadata": e.metadata,
    }


async def upsert_edges(session: AsyncSession, edges: list[Edge]) -> int:
    if not edges:
        return 0
    # Use Core table (not the ORM-mapped class): SQLAlchemy's ORM bulk path
    # mistakes our `metadata` DB column for the Table's `metadata` attribute.
    written = 0
    for start in range(0, len(edges), _UPSERT_CHUNK):
        chunk = edges[start : start + _UPSERT_CHUNK]
        rows = [_row(e) for e in chunk]
        stmt = insert(LineageEdge.__table__).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["src_urn", "dst_urn", "edge_type"],
            set_={
                "job_urn": stmt.excluded.job_urn,
                "run_id": stmt.excluded.run_id,
                "namespace": stmt.excluded.namespace,
                "metadata": stmt.excluded.metadata,
            },
        )
        await session.execute(stmt)
        written += len(rows)
    await session.commit()
    return written


async def direct_neighbors(session: AsyncSession, node: str) -> dict[str, list[dict[str, Any]]]:
    upstream_q = text(
        "SELECT src_urn, dst_urn, edge_type, job_urn, run_id, namespace "
        "FROM lineage_edge WHERE dst_urn = :node"
    )
    downstream_q = text(
        "SELECT src_urn, dst_urn, edge_type, job_urn, run_id, namespace "
        "FROM lineage_edge WHERE src_urn = :node"
    )
    up = (await session.execute(upstream_q, {"node": node})).mappings().all()
    down = (await session.execute(downstream_q, {"node": node})).mappings().all()
    return {"upstream": [dict(r) for r in up], "downstream": [dict(r) for r in down]}


async def traverse(
    session: AsyncSession, node: str, depth: int, direction: Direction
) -> list[dict[str, Any]]:
    """Recursive CTE traversal. Caps at `depth` hops."""
    if direction == "upstream":
        seed_col, next_col = "dst_urn", "src_urn"
    elif direction == "downstream":
        seed_col, next_col = "src_urn", "dst_urn"
    else:
        up = await traverse(session, node, depth, "upstream")
        down = await traverse(session, node, depth, "downstream")
        seen = set()
        out = []
        for e in up + down:
            key = (e["src_urn"], e["dst_urn"], e["edge_type"])
            if key not in seen:
                seen.add(key)
                out.append(e)
        return out

    q = text(
        f"""
        WITH RECURSIVE walk(src_urn, dst_urn, edge_type, job_urn, run_id, namespace, depth) AS (
            SELECT src_urn, dst_urn, edge_type, job_urn, run_id, namespace, 1
            FROM lineage_edge WHERE {seed_col} = :node
            UNION
            SELECT e.src_urn, e.dst_urn, e.edge_type, e.job_urn, e.run_id, e.namespace, w.depth + 1
            FROM lineage_edge e
            JOIN walk w ON e.{seed_col} = w.{next_col}
            WHERE w.depth < :depth
        )
        SELECT DISTINCT src_urn, dst_urn, edge_type, job_urn, run_id, namespace FROM walk
        """
    ).bindparams(bindparam("node"), bindparam("depth"))
    rows = (await session.execute(q, {"node": node, "depth": depth})).mappings().all()
    return [dict(r) for r in rows]
