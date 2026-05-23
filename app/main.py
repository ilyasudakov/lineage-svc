import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse, Response

from app.config import settings
from app.db import engine, get_session
from app.repository import direct_neighbors, traverse, upsert_edges
from app.routes_ui import router as ui_router
from app.schemas import BatchIngestRequest, BatchIngestResponse, Direction, OpenLineageEvent
from app.translator import translate

logging.basicConfig(level=settings.log_level)
log = logging.getLogger("data-lineage")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="data-lineage", version="0.1.0", lifespan=lifespan)
app.include_router(ui_router)

_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/ui/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/ui", include_in_schema=False)
async def ui_index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/lineage", status_code=201)
async def ingest(
    event: OpenLineageEvent, session: AsyncSession = Depends(get_session)
) -> dict[str, int]:
    edges = translate(event)
    written = await upsert_edges(session, edges)
    return {"edges_written": written}


@app.post("/api/v1/lineage:batch", status_code=201, response_model=BatchIngestResponse)
async def ingest_batch(
    payload: BatchIngestRequest, session: AsyncSession = Depends(get_session)
) -> BatchIngestResponse:
    """Bulk ingest — translates every event, dedupes, upserts once per request.

    Designed for producer-side batching (DTS workers, fixture loaders) that
    would otherwise pay an HTTP round trip + transaction cost per event.
    See docs/benchmark/batch-ingest.md for measured numbers.
    """
    all_edges = []
    for event in payload.events:
        all_edges.extend(translate(event))

    # Cross-event dedup — same edge can appear via different events in one batch.
    seen: set[tuple[str, str, str]] = set()
    deduped = []
    for e in all_edges:
        key = (e.src_urn, e.dst_urn, e.edge_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    written = await upsert_edges(session, deduped)
    return BatchIngestResponse(events_received=len(payload.events), edges_written=written)


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
