import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.config import settings
from app.db import engine, get_session
from app.models import Base
from app.repository import direct_neighbors, traverse, upsert_edges
from app.schemas import Direction, OpenLineageEvent
from app.translator import translate

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("lineage-svc")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # PoC convenience: create tables on startup. Replace with Alembic for prod.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="lineage-svc", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/lineage", status_code=201)
async def ingest(event: OpenLineageEvent, session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    edges = translate(event)
    written = await upsert_edges(session, edges)
    return {"edges_written": written}


@app.get("/api/v1/lineage/direct")
async def get_direct(node: str, session: AsyncSession = Depends(get_session)) -> dict:
    return {"node": node, **(await direct_neighbors(session, node))}


@app.get("/api/v1/lineage")
async def get_lineage(
    node: str,
    depth: int = Query(3, ge=1, le=50),
    direction: Direction = "both",
    session: AsyncSession = Depends(get_session),
) -> dict:
    edges = await traverse(session, node, depth, direction)
    return {"node": node, "depth": depth, "direction": direction, "edges": edges}
