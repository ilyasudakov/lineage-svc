"""Pytest fixtures.

Integration tests use an in-process SQLite database via aiosqlite. SQLite does
not support PostgreSQL's `ON CONFLICT ... DO UPDATE` syntax via SQLAlchemy's
postgresql dialect, so the upsert path is exercised in a Postgres-backed
integration suite (docker-compose) — not here. These fixtures are kept for
read-path and schema tests.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s
    await engine.dispose()
