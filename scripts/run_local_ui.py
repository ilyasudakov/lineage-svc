"""Run the lineage-svc app locally on port 8001 against the docker lineage-pg.

Used by .claude/launch.json so the preview tool can render /ui without
rebuilding the docker container (which would interrupt the running benchmark).
"""

import os

os.environ.setdefault(
    "LINEAGE_DATABASE_URL",
    "postgresql+asyncpg://lineage:lineage@localhost:5433/lineage",
)
os.environ.setdefault("LINEAGE_LOG_LEVEL", "INFO")

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, log_level="info")
