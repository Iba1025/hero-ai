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
    fast_path: bool = False,
) -> Any:
    """Factory that returns a retrieve node with injected adapters.

    If qdrant_client is provided, uses real hybrid retrieval.
    Otherwise, produces stub evidence (for skeleton evals without Qdrant).
    fast_path=True builds the BL-4 fast-path node (BM25-only top 5, no
    rerank) — the TRIAGE conditional edge decides which node runs, so the
    node itself no longer reads state.complexity.
    """

    async def retrieve(state: dict[str, Any]) -> dict[str, Any]:
        description = state.get("description", "")

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

        # Stub fallback: fixed evidence chunks. Mirror the real paths'
        # retrieval_stage attribution (bm25/no-rerank vs fused+rerank).
        trade = state.get("trade", "other")
        candidates = [
            EvidenceChunk(
                doc_id=f"manual-{trade}-001",
                page=i,
                score=0.9 - (i * 0.05),
                retrieval_stage="bm25" if fast_path else "fused",
            )
            for i in range(1, 6)
        ]
        if fast_path:
            return {"evidence": [c.model_dump() for c in candidates]}
        reranked = reranker.rerank(description, candidates, top_k=5)
        return {"evidence": [c.model_dump() for c in reranked]}

    return retrieve
