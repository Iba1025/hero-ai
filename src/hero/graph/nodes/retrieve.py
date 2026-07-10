"""RETRIEVE node — hybrid retrieval over manual corpus (spec §7).

Uses real retrieval pipeline when Qdrant client is provided;
falls back to stub evidence when no Qdrant is available (skeleton evals).
Fast path (complexity=="simple"): BM25-only top 5, no rerank.
Corrective loop is BL-9 (not in this phase).
"""

from __future__ import annotations

from typing import Any

from hero.graph.state import EvidenceChunk
from hero.interfaces.embedder import Embedder
from hero.interfaces.reranker import Reranker


def make_retrieve(
    embedder: Embedder,
    reranker: Reranker,
    qdrant_client: Any | None = None,
) -> Any:
    """Factory that returns a retrieve node with injected adapters.

    If qdrant_client is provided, uses real hybrid retrieval.
    Otherwise, produces stub evidence (for skeleton evals without Qdrant).
    """

    async def retrieve(state: dict[str, Any]) -> dict[str, Any]:
        description = state.get("description", "")
        complexity = state.get("complexity")
        fast_path = complexity == "simple"

        # Real retrieval when Qdrant is available
        if qdrant_client is not None:
            from hero.retrieval.hybrid import retrieve_hybrid

            results = retrieve_hybrid(
                description,
                embedder=embedder,
                reranker=reranker,
                client=qdrant_client,
                fast_path=fast_path,
            )
            return {"evidence": [c.model_dump() for c in results]}

        # Stub fallback: fixed evidence chunks
        trade = state.get("trade", "other")
        candidates = [
            EvidenceChunk(
                doc_id=f"manual-{trade}-001",
                page=i,
                score=0.9 - (i * 0.05),
                retrieval_stage="fused",
            )
            for i in range(1, 6)
        ]
        reranked = reranker.rerank(description, candidates, top_k=5)
        return {"evidence": [c.model_dump() for c in reranked]}

    return retrieve
