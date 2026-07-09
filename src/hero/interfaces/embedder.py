"""Embedder Protocol — spec §6."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    model_id: str

    def embed_page(self, image: bytes) -> list[list[float]]:
        """Multi-vector patch embeddings for a page image."""
        ...

    def embed_query(self, text: str) -> list[list[float]]:
        """Multi-vector query embeddings."""
        ...
