"""Root test conftest — shared fixtures for Qdrant + Postgres."""

from __future__ import annotations

import os

import pytest
from qdrant_client import QdrantClient


def _qdrant_url() -> str:
    """Qdrant URL from env (CI service container) or localhost default."""
    return os.environ.get("QDRANT_URL", "http://localhost:6333")


@pytest.fixture(scope="session")
def qdrant_client() -> QdrantClient:
    """Qdrant client for integration tests.

    Prefers QDRANT_URL env var (CI service container).
    Falls back to localhost:6333 (local dev).
    """
    url = _qdrant_url()
    client = QdrantClient(url=url, timeout=10)
    return client
