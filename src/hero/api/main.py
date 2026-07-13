"""FastAPI application — Hero.AI ticket pipeline API."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hero.api import background
from hero.api.deps import get_chat_vlm, get_session_factory, init_graph
from hero.api.pipeline import recover_orphaned_runs
from hero.api.routers import auth, outcomes, public, tickets, uploads
from hero.config import get_settings, region_guard
from hero.observability import flush


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown lifecycle."""
    logger = logging.getLogger(__name__)
    settings = get_settings()
    region_guard(settings)
    if not settings.jwt_secret_key:
        logger.warning("JWT_SECRET_KEY unset — all authenticated endpoints will return 503 (P4-1)")
    # BL-19 (H3): build the graph BEFORE serving — checkpointer setup() runs its
    # CREATE INDEX CONCURRENTLY with no request transaction open (kills the
    # first-ticket self-deadlock), and live model weights load here, never on a
    # user request.
    graph = await init_graph()
    # Nova chat tier (Phase 5, DEC-23): build at startup, never on a request.
    get_chat_vlm()
    # BL-17 (H1): re-drive runs a dead process left queued/running — the
    # Postgres checkpointer (INV-6) resumes them from the last completed node.
    # Deliberately BLOCKING at pilot scale: the server does not accept requests
    # until orphans are re-driven (spec §3 serving lifecycle).
    recovered = await recover_orphaned_runs(graph, get_session_factory())
    if recovered:
        # WARNING so it surfaces under uvicorn's default log config — an
        # orphaned run means the previous process died mid-pipeline.
        logger.warning("Recovered %d orphaned pipeline run(s)", recovered)
    yield
    await background.drain()  # let in-flight pipeline runs finish (BL-17/H1)
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
