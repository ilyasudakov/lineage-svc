#!/usr/bin/env sh
# Run Alembic migrations on startup, then exec the CMD (uvicorn by default).
# Idempotent — Alembic stamps the version in `alembic_version` and noops if
# already at head.
set -e

echo "[entrypoint] running alembic upgrade head"
alembic upgrade head

echo "[entrypoint] launching: $*"
exec "$@"
