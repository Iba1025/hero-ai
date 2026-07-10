"""Cohere Rerank adapter — behind config flag only (DEC-8).

Not implemented in this phase. Kept as a config option per spec §1.
Self-hosted BGE is the default per INV-2 (data residency).
"""

from __future__ import annotations

from hero.graph.state import EvidenceChunk


class CohereReranker:
    """Placeholder for Cohere Rerank API adapter.

    Not implemented — self-hosted BGE is preferred per DEC-8 / INV-2.
    Set RERANKER_IMPL=cohere to trigger this; will fail loudly.
    """

    def rerank(
        self, query: str, candidates: list[EvidenceChunk], top_k: int = 5
    ) -> list[EvidenceChunk]:
        raise NotImplementedError(
            "Cohere Rerank adapter is not implemented. "
            "Use RERANKER_IMPL=bge (self-hosted, DEC-8) or RERANKER_IMPL=stub. "
            "Cohere is kept as a config option for future evaluation per spec §1, "
            "but self-hosted is preferred for data residency (INV-2)."
        )
