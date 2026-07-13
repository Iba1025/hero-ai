"""Dependency injection for FastAPI — graph, adapters, DB session, auth."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hero.adapters.stub_calibrator import StubCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.api.resume import ResumeNotAllowedError, resume_sanctioned
from hero.auth.tokens import TokenError, decode_session_token
from hero.config import Settings, get_settings
from hero.graph.build import build_graph
from hero.interfaces.calibrator import Calibrator

SESSION_COOKIE = "hero_session"


@dataclass(frozen=True)
class AuthUser:
    """Authenticated principal, decoded from the signed session cookie."""

    id: uuid.UUID
    org_id: uuid.UUID
    role: str


def get_current_user(request: Request) -> AuthUser:
    """Decode the session cookie into an AuthUser. 401 on anything invalid.

    Stateless by design (P4-1): claims are signed, so no DB hit per request.
    Revocation = rotate JWT_SECRET_KEY.
    """
    settings = get_settings()
    if not settings.jwt_secret_key:
        raise HTTPException(status_code=503, detail="Auth not configured (JWT_SECRET_KEY unset)")
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        claims = decode_session_token(token, secret=settings.jwt_secret_key)
        return AuthUser(
            id=uuid.UUID(claims.user_id),
            org_id=uuid.UUID(claims.org_id),
            role=claims.role,
        )
    except (TokenError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc


def require_role(*roles: str) -> Callable[..., AuthUser]:
    """Dependency factory: 403 unless the caller's role is in `roles`."""

    def _check(user: AuthUser = Depends(get_current_user)) -> AuthUser:  # noqa: B008
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user

    return _check


@lru_cache(maxsize=1)
def _get_engine(database_url: str) -> Any:
    return create_async_engine(database_url)


@lru_cache(maxsize=1)
def _get_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = _get_engine(database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    settings = get_settings()
    factory = _get_session_factory(settings.database_url)
    async with factory() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Session factory for background pipeline runs (BL-17/H1): a run outlives
    the request that spawned it, so it opens sessions of its own."""
    settings = get_settings()
    return _get_session_factory(settings.database_url)


def make_calibrator(settings: Settings) -> Calibrator:
    """Select calibrator by CALIBRATOR_IMPL (DEC-5: platt default).

    Isotonic is selectable but self-gates: it stays in identity mode until
    fit with >= 1000 labels (see adapters/platt.py).
    """
    if settings.calibrator_impl == "platt":
        from hero.adapters.platt import PlattCalibrator

        return PlattCalibrator()
    if settings.calibrator_impl == "isotonic":
        from hero.adapters.platt import IsotonicCalibrator

        return IsotonicCalibrator()
    return StubCalibrator()


def make_embedder(settings: Settings) -> Any:
    """Select embedder by EMBEDDER_IMPL (BL-19/H3: config, not a code edit)."""
    if settings.embedder_impl == "colmodernvbert":
        from hero.adapters.colmodernvbert import ColModernVBertEmbedder

        return ColModernVBertEmbedder()
    if settings.embedder_impl == "colqwen3":
        raise ValueError("EMBEDDER_IMPL=colqwen3 has no adapter yet (BL-5 bake-off pending)")
    from hero.adapters.stub_embedder import StubEmbedder

    return StubEmbedder()


def make_reranker(settings: Settings) -> Any:
    """Select reranker by RERANKER_IMPL (DEC-8: self-hosted bge default for live)."""
    if settings.reranker_impl == "bge":
        from hero.adapters.bge_reranker import BGEReranker

        return BGEReranker()
    if settings.reranker_impl == "cohere":
        from hero.adapters.cohere_reranker import CohereReranker

        return CohereReranker()
    from hero.adapters.stub_reranker import StubReranker

    return StubReranker()


def make_vlm(settings: Settings) -> Any:
    """Select VLM by VLM_IMPL — tiered LiteLLM routing (DEC-18) or stub."""
    if settings.vlm_impl == "litellm":
        from hero.adapters.litellm_vlm import LiteLLMVLM

        return LiteLLMVLM(
            primary_model=settings.vlm_model_primary,
            verify_model=settings.vlm_model_verify,
            fallback_model=settings.vlm_model_fallback,
            triage_model=settings.vlm_model_triage,
            chat_model=settings.vlm_model_chat,
        )
    from hero.adapters.stub_vlm import StubVLM

    return StubVLM()


async def make_checkpointer(settings: Settings) -> Any:
    """Create the checkpointer. AsyncPostgresSaver by default (INV-6).

    MemorySaver ONLY when HERO_EVAL_MEMORY_CHECKPOINTER=1 is explicitly set.
    CI must never set this flag.
    """
    if settings.hero_eval_memory_checkpointer:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    db_url = settings.database_url.replace("+asyncpg", "")
    pool = AsyncConnectionPool(
        conninfo=db_url,
        open=False,
        kwargs={"autocommit": True},
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    return saver


class _ResumeGuardedGraph:
    """Single resume path rule (P4-4, spec §4): out-of-path resumes fail loudly.

    Delegates everything to the compiled graph except `ainvoke` of a
    Command(resume=...), which must come through hero.api.resume — the only
    path that snapshots the pending question and writes the ledger round.
    """

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)

    async def ainvoke(self, run_input: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(run_input, "resume", None) is not None and not resume_sanctioned():
            raise ResumeNotAllowedError(
                "Resume outside the single resume path — use "
                "hero.api.resume.resume_with_answer so the ledger records the round"
            )
        return await self._graph.ainvoke(run_input, *args, **kwargs)


_CHAT_VLM_SINGLETON: Any = None


def get_chat_vlm() -> Any:
    """Nova's conversational-tier VLM (Phase 5, DEC-23) — same settings-selected
    adapter family as the graph's (make_vlm), built once at startup (lifespan
    warms it; lazy build covers unit-test ASGI transports). Only hero.nova
    ever calls its `.chat` tier."""
    global _CHAT_VLM_SINGLETON
    if _CHAT_VLM_SINGLETON is None:
        _CHAT_VLM_SINGLETON = make_vlm(get_settings())
    return _CHAT_VLM_SINGLETON


def reset_chat_vlm() -> None:
    """Test hook: drop the singleton so the next build sees fresh settings."""
    global _CHAT_VLM_SINGLETON
    _CHAT_VLM_SINGLETON = None


_GRAPH_SINGLETON: Any = None


async def _build_api_graph() -> Any:
    """Assemble the serving graph: settings-selected adapters, Postgres
    checkpointer (INV-6), wrapped in the single-resume-path guard."""
    settings = get_settings()
    checkpointer = await make_checkpointer(settings)

    qdrant_client: Any | None = None
    if settings.embedder_impl != "stub":
        # Real retrieval needs Qdrant — fail loudly at startup, not per ticket.
        from qdrant_client import QdrantClient

        qdrant_client = QdrantClient(url=settings.qdrant_url, timeout=30)
        qdrant_client.get_collections()

    graph = build_graph(
        embedder=make_embedder(settings),
        reranker=make_reranker(settings),
        calibrator=make_calibrator(settings),
        vlm=make_vlm(settings),
        catalog=StubCatalogResolver(),
        checkpointer=checkpointer,
        grounding_threshold=settings.grounding_threshold,
        grounding_threshold_strict=settings.grounding_threshold_strict,
        qdrant_client=qdrant_client,
    )
    return _ResumeGuardedGraph(graph)


async def init_graph() -> Any:
    """Build the graph singleton at startup (BL-19/H3), called from the lifespan.

    Warming the checkpointer here (saver.setup() runs CREATE INDEX CONCURRENTLY)
    kills the first-ticket self-deadlock: no request transaction can be open yet.
    Model weights (live adapters) also load now — never on a user request.
    """
    global _GRAPH_SINGLETON
    if _GRAPH_SINGLETON is None:
        _GRAPH_SINGLETON = await _build_api_graph()
    return _GRAPH_SINGLETON


async def get_graph() -> Any:
    """The serving graph singleton. Lazily builds only when the lifespan did
    not run (unit-test ASGI transports); real serving always pre-builds."""
    if _GRAPH_SINGLETON is None:
        return await init_graph()
    return _GRAPH_SINGLETON


def reset_graph() -> None:
    """Test hook: drop the singleton so the next build sees fresh settings."""
    global _GRAPH_SINGLETON
    _GRAPH_SINGLETON = None
