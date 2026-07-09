"""Dependency injection for FastAPI — graph, adapters, DB session."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hero.adapters.stub_calibrator import StubCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
from hero.config import get_settings
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


@lru_cache(maxsize=1)
def get_graph() -> Any:
    """Build and cache the compiled graph with stub adapters.

    In skeleton phase: all adapters are stubs, checkpointer is MemorySaver.
    Production: swap to PostgresSaver and real adapters based on config.
    """
    settings = get_settings()
    return build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=StubCalibrator(),
        vlm=StubVLM(),
        catalog=StubCatalogResolver(),
        checkpointer=MemorySaver(),
        grounding_threshold=settings.grounding_threshold,
    )
