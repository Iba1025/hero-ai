"""RETRIEVE node — hybrid retrieval over manual corpus.

Stub: returns fixed evidence chunks. Real impl uses Embedder + Reranker
over Qdrant (spec §7). Corrective loop is BL-9 (not in skeleton).
"""

from __future__ import annotations

from typing import Any

from hero.graph.state import EvidenceChunk
from hero.interfaces.embedder import Embedder
from hero.interfaces.reranker import Reranker


def make_retrieve(embedder: Embedder, reranker: Reranker) -> Any:
    """Factory that returns a retrieve node with injected adapters."""

    async def retrieve(state: dict[str, Any]) -> dict[str, Any]:
        # Stub: produce fixed evidence chunks
        description = state.get("description", "")
        trade = state.get("trade", "other")

        # Simulate retrieval: generate candidate chunks
        candidates = [
            EvidenceChunk(
                doc_id=f"manual-{trade}-001",
                page=i,
                score=0.9 - (i * 0.05),
                retrieval_stage="fused",
            )
            for i in range(1, 6)
        ]

        # Run through reranker (stub just sorts by score)
        reranked = reranker.rerank(description, candidates, top_k=5)

        return {"evidence": [c.model_dump() for c in reranked]}

    return retrieve
