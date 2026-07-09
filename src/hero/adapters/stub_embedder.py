"""Stub Embedder — deterministic fake for skeleton testing."""

from __future__ import annotations


class StubEmbedder:
    """Returns fixed 128-dim multi-vector embeddings (single patch)."""

    model_id: str = "stub-embedder-v0"

    def embed_page(self, image: bytes) -> list[list[float]]:
        return [[0.1] * 128]

    def embed_query(self, text: str) -> list[list[float]]:
        return [[0.2] * 128]
