"""Reranker Protocol — spec §6."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from hero.graph.state import EvidenceChunk


@runtime_checkable
class Reranker(Protocol):
    def rerank(
        self, query: str, candidates: list[EvidenceChunk], top_k: int = 5
    ) -> list[EvidenceChunk]:
        """Re-score and return the top-k evidence chunks."""
        ...
