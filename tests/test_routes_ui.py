"""Tests for UI discovery endpoints.

Uses an in-memory sqlite session and FastAPI dependency override; no docker
or real Postgres needed.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import get_session
from app.main import app
from app.models import Base, LineageEdge


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with maker() as session:
        session.add_all(
            [
                LineageEdge(
                    src_urn="dataset:ns1/in",
                    dst_urn="job:ns1/j",
                    edge_type="consumes",
                    namespace="ns1",
                ),
                LineageEdge(
                    src_urn="job:ns1/j",
                    dst_urn="dataset:ns1/out",
                    edge_type="produces",
                    namespace="ns1",
                ),
                LineageEdge(
                    src_urn="dataset:ns2/a",
                    dst_urn="dataset:ns2/b",
                    edge_type="derives_from",
                    namespace="ns2",
                ),
            ]
        )
        await session.commit()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_namespaces_returns_distinct_sorted(client: AsyncClient):
    r = await client.get("/api/v1/namespaces")
    assert r.status_code == 200
    assert r.json() == {"namespaces": ["ns1", "ns2"]}


async def test_search_finds_substring(client: AsyncClient):
    r = await client.get("/api/v1/search", params={"q": "in"})
    assert r.status_code == 200
    urns = [n["urn"] for n in r.json()["results"]]
    assert "dataset:ns1/in" in urns


async def test_search_namespace_scope_filters_other_namespaces(client: AsyncClient):
    # "/a" is unambiguous (won't match "dataset:" which contains 'a' otherwise).
    r = await client.get("/api/v1/search", params={"q": "/a", "namespace": "ns2"})
    urns = [n["urn"] for n in r.json()["results"]]
    assert urns == ["dataset:ns2/a"]
    # Empty when scoped to ns1 (no ns1 URN ends with /a)
    r2 = await client.get("/api/v1/search", params={"q": "/a", "namespace": "ns1"})
    assert r2.json()["results"] == []


async def test_search_kind_inferred_from_urn_prefix(client: AsyncClient):
    r = await client.get("/api/v1/search", params={"q": "j"})
    by_urn = {n["urn"]: n["kind"] for n in r.json()["results"]}
    assert by_urn["job:ns1/j"] == "job"


async def test_search_rejects_empty_query(client: AsyncClient):
    r = await client.get("/api/v1/search", params={"q": ""})
    assert r.status_code == 422


async def test_ui_index_serves_html(client: AsyncClient):
    r = await client.get("/ui")
    assert r.status_code == 200
    assert b"<title>data-lineage" in r.content
