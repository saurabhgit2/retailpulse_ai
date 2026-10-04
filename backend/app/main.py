"""The FastAPI application.

Built by a factory function rather than as a module-level object, so tests can
create a fresh app with different settings instead of importing a global one.

Run it with:
    uvicorn app.main:app --reload
Interactive docs (generated from the Pydantic schemas): http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_error_handlers
from app.api.routes import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, new_request_id, request_id_var
from app.services.processing_service import recover_stuck_datasets

API_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Runs once at start-up and once at shutdown."""
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        recover_stuck_datasets()
    except Exception:  # noqa: BLE001 - never stop the app from starting
        logger.warning("Could not check for interrupted datasets (is the database running?)")
    logger.info("RetailPulse API ready in %s mode", settings.app_env)
    yield
    logger.info("RetailPulse API shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="RetailPulse AI API",
        version="0.3.0",
        summary="Retail analytics and forecasting platform (Phases 2-3: data pipeline).",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Which browser origins may call this API. Never "*" together with
    # credentials, and never a wildcard in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Give every request an ID, log it, and time it."""
        request_id_var.set(new_request_id())
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "%s %s -> %s in %.0fms",
            request.method, request.url.path, response.status_code, elapsed_ms,
        )
        response.headers["X-Request-ID"] = request_id_var.get()
        return response

    register_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    return app


app = create_app()
