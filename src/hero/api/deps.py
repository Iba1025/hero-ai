"""Dependency injection for FastAPI — graph, adapters, DB session."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hero.adapters.stub_calibrator import StubCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
from hero.config import Settings, get_settings
from hero.graph.build import build_graph
from hero.interfaces.calibrator import Calibrator


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
