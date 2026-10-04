"""Liveness check. Deliberately unauthenticated: monitoring tools use it."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import get_settings

router = APIRouter(tags=["platform"])


@router.get("/health", summary="Service and database health")
def health(session: DbSession) -> dict[str, object]:
    try:
        session.execute(text("SELECT 1"))
        database_ok = True
    except Exception:  # noqa: BLE001 - health must report, not raise
        database_ok = False

    return {
        "status": "ok" if database_ok else "degraded",
        "database": "up" if database_ok else "down",
        "environment": get_settings().app_env,
    }
