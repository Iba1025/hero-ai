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
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
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


async def get_graph() -> Any:
    """Build the compiled graph.

    Uses AsyncPostgresSaver checkpointer (INV-6) — fails loudly without DATABASE_URL.
    """
    settings = get_settings()
    checkpointer = await make_checkpointer(settings)
    return build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=make_calibrator(settings),
        vlm=StubVLM(),
        catalog=StubCatalogResolver(),
        checkpointer=checkpointer,
        grounding_threshold=settings.grounding_threshold,
        grounding_threshold_strict=settings.grounding_threshold_strict,
    )
