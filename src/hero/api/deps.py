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


def _make_checkpointer(settings: Settings) -> Any:
    """Create the checkpointer. PostgresSaver by default (INV-6).

    MemorySaver ONLY when HERO_EVAL_MEMORY_CHECKPOINTER=1 is explicitly set.
    CI must never set this flag.
    """
    if settings.hero_eval_memory_checkpointer:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()

    from langgraph.checkpoint.postgres import PostgresSaver

    db_url = settings.database_url
    sync_url = db_url.replace("+asyncpg", "")
    # from_conn_string is a context manager; use psycopg.Connection directly
    import psycopg

    conn = psycopg.connect(sync_url, autocommit=True)
    saver = PostgresSaver(conn)
    saver.setup()
    return saver


@lru_cache(maxsize=1)
def get_graph() -> Any:
    """Build and cache the compiled graph.

    Uses PostgresSaver checkpointer (INV-6) — fails loudly without DATABASE_URL.
    """
    settings = get_settings()
    checkpointer = _make_checkpointer(settings)
    return build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=StubCalibrator(),
        vlm=StubVLM(),
        catalog=StubCatalogResolver(),
        checkpointer=checkpointer,
        grounding_threshold=settings.grounding_threshold,
    )
