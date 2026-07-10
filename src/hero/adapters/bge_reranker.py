"""BGE cross-encoder reranker — BL-1, self-hosted (DEC-8).

Uses BAAI/bge-reranker-v2-m3 for cross-encoder reranking.
Processes (query, document_text) pairs and re-scores candidates.

Model download: ~600MB from HuggingFace Hub on first use.
"""

from __future__ import annotations

from typing import Any

from sentence_transformers import CrossEncoder

from hero.graph.state import EvidenceChunk


class BGEReranker:
    """Reranker Protocol implementation using BGE cross-encoder.

    Self-hosted per DEC-8 (INV-2 data residency).
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._model: Any = CrossEncoder(model_name, device=device)

    def rerank(
        self, query: str, candidates: list[EvidenceChunk], top_k: int = 5
    ) -> list[EvidenceChunk]:
        """Re-score candidates using cross-encoder and return top-k."""
        if not candidates:
            return []

        # Build (query, doc_text) pairs
        # Use doc_id:page as fallback text if no text payload available
        pairs: list[list[str]] = []
        for c in candidates:
            # In a real system, we'd fetch the text from Qdrant payload
            # For now, use the chunk metadata as proxy
            doc_text = f"Document {c.doc_id}, page {c.page}"
            pairs.append([query, doc_text])

        # Score all pairs
        scores = self._model.predict(pairs)

        # Pair scores with chunks and sort
        scored = sorted(
            zip(scores, candidates, strict=False),
            key=lambda x: float(x[0]),
            reverse=True,
        )

        return [
            chunk.model_copy(update={"score": float(score), "retrieval_stage": "reranked"})
            for score, chunk in scored[:top_k]
        ]
