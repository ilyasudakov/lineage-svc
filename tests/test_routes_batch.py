"""Tests for the batch ingest endpoint."""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import get_session
from app.main import app
from app.models import Base


def _event(job: str, in_name: str, out_name: str, run: str = "r1", ns: str = "ns") -> dict:
    return {
        "eventType": "COMPLETE",
        "eventTime": "2026-05-23T00:00:00Z",
        "run": {"runId": run},
        "job": {"namespace": ns, "name": job},
        "inputs": [{"namespace": ns, "name": in_name}],
        "outputs": [{"namespace": ns, "name": out_name}],
    }


@pytest_asyncio.fixture
async def client_and_engine() -> AsyncIterator[tuple[AsyncClient, AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac,
        maker() as inspect,
    ):
        yield ac, inspect
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_batch_with_three_events_writes_nine_edges(client_and_engine):
    client, inspect = client_and_engine
    body = {"events": [_event("j1", "a", "b"), _event("j2", "c", "d"), _event("j3", "e", "f")]}
    r = await client.post("/api/v1/lineage:batch", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["events_received"] == 3
    assert data["edges_written"] == 9  # 3 events * 3 edge types

    row = (await inspect.execute(text("SELECT COUNT(*) FROM lineage_edge"))).scalar_one()
    assert row == 9


async def test_batch_dedupes_duplicate_events(client_and_engine):
    client, inspect = client_and_engine
    # Same event posted 5 times in one batch — only 3 rows should land.
    body = {"events": [_event("j1", "a", "b") for _ in range(5)]}
    r = await client.post("/api/v1/lineage:batch", json=body)
    assert r.status_code == 201
    assert r.json()["edges_written"] == 3
    row = (await inspect.execute(text("SELECT COUNT(*) FROM lineage_edge"))).scalar_one()
    assert row == 3


async def test_batch_with_overlapping_edges_across_events(client_and_engine):
    client, inspect = client_and_engine
    # Two different jobs that share a source dataset.
    # Each contributes (a→j, j→out, a→out). Distinct jobs → 6 unique edges total.
    body = {"events": [_event("j1", "a", "out1"), _event("j2", "a", "out2")]}
    r = await client.post("/api/v1/lineage:batch", json=body)
    assert r.json()["edges_written"] == 6
    row = (await inspect.execute(text("SELECT COUNT(*) FROM lineage_edge"))).scalar_one()
    assert row == 6


async def test_batch_is_idempotent_across_calls(client_and_engine):
    client, inspect = client_and_engine
    body = {"events": [_event("j1", "a", "b")]}
    for _ in range(3):
        r = await client.post("/api/v1/lineage:batch", json=body)
        assert r.status_code == 201
    row = (await inspect.execute(text("SELECT COUNT(*) FROM lineage_edge"))).scalar_one()
    assert row == 3  # not 9 — PK + ON CONFLICT dedup the cross-call repeats


async def test_batch_rejects_empty(client_and_engine):
    client, _ = client_and_engine
    r = await client.post("/api/v1/lineage:batch", json={"events": []})
    assert r.status_code == 422


async def test_batch_rejects_too_large(client_and_engine):
    client, _ = client_and_engine
    body = {"events": [_event(f"j{i}", f"a{i}", f"b{i}") for i in range(1001)]}
    r = await client.post("/api/v1/lineage:batch", json=body)
    assert r.status_code == 422


async def test_batch_invalid_event_shape_rejects_whole_batch(client_and_engine):
    client, inspect = client_and_engine
    # First event is valid, second is missing required `job` field.
    body = {
        "events": [
            _event("j1", "a", "b"),
            {"eventType": "COMPLETE", "eventTime": "2026-05-23T00:00:00Z", "run": {"runId": "r"}},
        ]
    }
    r = await client.post("/api/v1/lineage:batch", json=body)
    assert r.status_code == 422
    # Nothing landed — the whole batch is rejected before reaching the DB.
    row = (await inspect.execute(text("SELECT COUNT(*) FROM lineage_edge"))).scalar_one()
    assert row == 0
