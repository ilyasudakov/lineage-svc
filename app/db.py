from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# asyncpg-specific tuning, applied only when the URL targets Postgres so the
# in-memory sqlite test fixture is unaffected.
#
#   prepared_statement_cache_size — how many prepared statements asyncpg keeps
#       per connection. Default is 100; bumping to 500 covers the full set of
#       upsert/select queries plus the dynamic recursive-CTE permutations.
#   statement_cache_size — same idea for query plans.
_connect_args: dict = {}
if settings.database_url.startswith("postgresql"):
    _connect_args["prepared_statement_cache_size"] = 500
    _connect_args["statement_cache_size"] = 500

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
    connect_args=_connect_args,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
