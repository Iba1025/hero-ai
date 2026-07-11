"""FastAPI application — Hero.AI ticket pipeline API."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from hero.api.routers import outcomes, tickets, uploads
from hero.config import get_settings, region_guard
from hero.observability import flush


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown lifecycle."""
    settings = get_settings()
    region_guard(settings)
    yield
    flush()  # drain buffered Langfuse spans (no-op when unconfigured)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hero.AI",
        description="AI-powered diagnostic + procurement for building maintenance",
        version="0.1.0",
        lifespan=lifespan,
    )

    # AUTH TODO: add authentication middleware here
    # This is a clearly marked slot for auth middleware.
    # No auth in skeleton phase — add before production deployment.

    app.include_router(tickets.router, prefix="/tickets", tags=["tickets"])
    app.include_router(outcomes.router, prefix="/outcomes", tags=["outcomes"])
    app.include_router(uploads.router, prefix="/uploads", tags=["uploads"])

    return app


app = create_app()
