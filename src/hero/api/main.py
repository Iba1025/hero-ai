"""FastAPI application — Hero.AI ticket pipeline API."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hero.api.routers import auth, outcomes, public, tickets, uploads
from hero.config import get_settings, region_guard
from hero.observability import flush


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown lifecycle."""
    settings = get_settings()
    region_guard(settings)
    if not settings.jwt_secret_key:
        logging.getLogger(__name__).warning(
            "JWT_SECRET_KEY unset — all authenticated endpoints will return 503 (P4-1)"
        )
    yield
    flush()  # drain buffered Langfuse spans (no-op when unconfigured)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hero.AI",
        description="AI-powered diagnostic + procurement for building maintenance",
        version="0.1.0",
        lifespan=lifespan,
    )

    # AUTH (P4-1): cookie-session JWT — see api/deps.get_current_user.
    # Every ticket/outcome/upload route requires a session; org scoping is
    # enforced in the query layer (repo.get_ticket_for_org). CORS allows the
    # separately-served SPA to send the httponly cookie.
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(tickets.router, prefix="/tickets", tags=["tickets"])
    app.include_router(outcomes.router, prefix="/outcomes", tags=["outcomes"])
    app.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
    # PUBLIC (P4-4): tenant intake + status — deliberately unauthenticated.
    # The unguessable slug is the credential; the router exposes nothing
    # org-scoped beyond a building name and a ticket's own plain status.
    app.include_router(public.router, prefix="/public", tags=["public"])

    return app


app = create_app()
