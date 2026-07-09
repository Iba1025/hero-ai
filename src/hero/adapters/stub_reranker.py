"""Stub Reranker — deterministic fake for skeleton testing."""

from __future__ import annotations

from hero.graph.state import EvidenceChunk


class StubReranker:
    """Returns candidates sorted by existing score, truncated to top_k."""

    def rerank(
        self, query: str, candidates: list[EvidenceChunk], top_k: int = 5
    ) -> list[EvidenceChunk]:
        sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)
        return [
            c.model_copy(update={"retrieval_stage": "reranked"}) for c in sorted_candidates[:top_k]
        ]
