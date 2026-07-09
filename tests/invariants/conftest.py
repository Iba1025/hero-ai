"""Shared fixtures for invariant tests — Postgres via DATABASE_URL or testcontainers."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from hero.adapters.stub_calibrator import StubCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
from hero.graph.build import build_graph
from hero.storage.models import Base


def _has_postgres() -> bool:
    """True if DATABASE_URL is set or Docker is available for testcontainers."""
    if os.environ.get("DATABASE_URL"):
        return True
    try:
        import docker  # type: ignore[import-untyped]

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


requires_docker = pytest.mark.skipif(
    not _has_postgres(), reason="No Postgres available (no DATABASE_URL, no Docker)"
)


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """Async connection URL for Postgres.

    Prefers DATABASE_URL env var (CI service container).
    Falls back to testcontainers if Docker is available.
    """
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        # CI provides DATABASE_URL pointing to the service container
        return env_url

    # Local dev with Docker: spin up testcontainers
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

    container = PostgresContainer("postgres:16-alpine")
    container.start()
    url: str = container.get_connection_url()
    url = url.replace("psycopg2", "asyncpg").replace("postgresql://", "postgresql+asyncpg://")
    return url


@pytest.fixture
async def db_session(postgres_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Create tables, yield a session, drop tables."""
    engine = create_async_engine(postgres_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def stub_graph() -> Any:
    """Build a graph with stub adapters and in-memory checkpointer."""
    return build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=StubCalibrator(),
        vlm=StubVLM(),
        catalog=StubCatalogResolver(),
        checkpointer=MemorySaver(),
    )
