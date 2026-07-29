"""Cloudflare Workers AI BGE reranker — lean mode, Cloudflare variant.

API-hosted reranking on Workers AI (``@cf/baai/bge-reranker-base``) — the
same model family as the self-hosted BGE cross-encoder baseline (BL-1), which
makes the DEC-29 eval-gate comparison as apples-to-apples as a hosted swap
can be.

⚠️ **Residency: recorded INV-2 exception, not compliance** — query text and
candidate chunk text cross the border (no Canadian residency commitment on
Workers AI). Founder-approved 2026-07-30 pending its DEC number; recorded in
``docs/residency.md``. Bedrock Rerank 3.5 in ca-central-1
(``cohere_reranker``) remains the INV-2-clean path and the migration target.

Scores: the model returns raw logits; we map them through a sigmoid so
``EvidenceChunk.score`` stays in [0, 1], consistent with the Cohere adapter's
``relevance_score``.

Pricing (documented): $0.0031 per M input tokens.
"""

from __future__ import annotations

import math
from typing import Any

import httpx

from hero.graph.state import EvidenceChunk

_MAX_DOCS_PER_QUERY = 100  # parity with the Bedrock rerank cap

_API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareBgeReranker:
    """Reranker Protocol implementation on Workers AI ``@cf/baai/bge-reranker-base``."""

    def __init__(
        self,
        account_id: str,
        api_token: str,
        model_id: str = "@cf/baai/bge-reranker-base",
        client: Any = None,
    ) -> None:
        self.model_id = model_id
        self._url = f"{_API_BASE}/accounts/{account_id}/ai/run/{model_id}"
        self._client: Any = client or httpx.Client(
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    def rerank(
        self, query: str, candidates: list[EvidenceChunk], top_k: int = 5
    ) -> list[EvidenceChunk]:
        """Re-score candidates via one Workers AI call and return top-k."""
        if not candidates:
            return []

        # Same text fallback as the other rerankers: never crash on text-less chunks.
        candidates = candidates[:_MAX_DOCS_PER_QUERY]
        contexts = [{"text": c.text or f"Document {c.doc_id}, page {c.page}"} for c in candidates]

        resp = self._client.post(
            self._url,
            json={
                "query": query,
                "contexts": contexts,
                "top_k": min(top_k, len(candidates)),
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success", False):
            raise RuntimeError(f"Workers AI rerank failed: {payload.get('errors')}")
        result = payload["result"]
        # {"response": [{"id": <context index>, "score": <logit>}, ...]}
        ranked = result.get("response")
        if ranked is None:
            raise RuntimeError(f"Workers AI rerank: unrecognised result shape {result!r:.200}")

        ordered = sorted(ranked, key=lambda r: float(r["score"]), reverse=True)
        return [
            candidates[int(r["id"])].model_copy(
                update={
                    "score": 1.0 / (1.0 + math.exp(-float(r["score"]))),  # sigmoid → [0,1]
                    "retrieval_stage": "reranked",
                }
            )
            for r in ordered[: min(top_k, len(candidates))]
        ]
