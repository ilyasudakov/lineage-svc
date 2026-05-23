"""Read-path tests against an in-memory SQLite.

Write path uses Postgres-only ON CONFLICT and is covered by the
docker-compose integration suite, not here.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LineageEdge
from app.repository import direct_neighbors, traverse


async def _seed(session: AsyncSession, rows: list[dict]) -> None:
    for r in rows:
        session.add(LineageEdge(**r))
    await session.commit()


async def test_direct_neighbors_returns_up_and_down(session: AsyncSession):
    await _seed(
        session,
        [
            {"src_urn": "a", "dst_urn": "b", "edge_type": "produces", "namespace": "n"},
            {"src_urn": "b", "dst_urn": "c", "edge_type": "produces", "namespace": "n"},
            {"src_urn": "x", "dst_urn": "b", "edge_type": "consumes", "namespace": "n"},
        ],
    )
    result = await direct_neighbors(session, "b")
    up_srcs = {e["src_urn"] for e in result["upstream"]}
    down_dsts = {e["dst_urn"] for e in result["downstream"]}
    assert up_srcs == {"a", "x"}
    assert down_dsts == {"c"}


async def test_traverse_downstream_respects_depth(session: AsyncSession):
    await _seed(
        session,
        [
            {"src_urn": "a", "dst_urn": "b", "edge_type": "produces", "namespace": "n"},
            {"src_urn": "b", "dst_urn": "c", "edge_type": "produces", "namespace": "n"},
            {"src_urn": "c", "dst_urn": "d", "edge_type": "produces", "namespace": "n"},
        ],
    )
    edges = await traverse(session, "a", depth=2, direction="downstream")
    nodes = {e["dst_urn"] for e in edges}
    assert nodes == {"b", "c"}  # depth=2 reaches a→b and b→c, not c→d
