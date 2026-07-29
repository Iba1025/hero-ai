"""Cohere Rerank 3.5 adapter on AWS Bedrock — lean mode (DEC-29).

API-hosted reranking on Bedrock **ca-central-1**: AWS docs list
``cohere.rerank-v3-5:0`` as single-region supported in ca-central-1
→ processing stays in Canada, no INV-2 gap. This supersedes the DEC-8-era
placeholder (self-hosted BGE remains in the codebase as the reversion path,
trigger recorded in DEC-29).

Per-call cost (documented for DEC-29): $2.00 per 1,000 queries — one rerank
call = one query ranking up to 100 chunks ≈ $0.002 per pipeline run.

Auth: standard AWS credential chain / long-term Bedrock API key (see
``bedrock_embedder`` — same ``AWS_BEARER_TOKEN_BEDROCK`` mechanism).
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3  # type: ignore[import-untyped]

from hero.graph.state import EvidenceChunk

_MAX_DOCS_PER_QUERY = 100  # Bedrock Cohere Rerank: one query ranks ≤100 chunks


class CohereReranker:
    """Reranker Protocol implementation on Bedrock Cohere Rerank 3.5 (DEC-29)."""

    def __init__(
        self,
        region: str = "ca-central-1",
        model_id: str = "cohere.rerank-v3-5:0",
        api_key: str = "",
        client: Any = None,
    ) -> None:
        self.model_id = model_id
        if api_key:
            os.environ.setdefault("AWS_BEARER_TOKEN_BEDROCK", api_key)
        self._client: Any = client or boto3.client("bedrock-runtime", region_name=region)

    def rerank(
        self, query: str, candidates: list[EvidenceChunk], top_k: int = 5
    ) -> list[EvidenceChunk]:
        """Re-score candidates via one Bedrock rerank call and return top-k."""
        if not candidates:
            return []

        # Same text fallback as BGEReranker: never crash on text-less chunks.
        candidates = candidates[:_MAX_DOCS_PER_QUERY]
        documents = [c.text or f"Document {c.doc_id}, page {c.page}" for c in candidates]

        body = json.dumps(
            {
                "query": query,
                "documents": documents,
                "top_n": min(top_k, len(candidates)),
                "api_version": 2,
            }
        )
        resp = self._client.invoke_model(modelId=self.model_id, body=body)
        payload = json.loads(resp["body"].read())

        return [
            candidates[r["index"]].model_copy(
                update={"score": float(r["relevance_score"]), "retrieval_stage": "reranked"}
            )
            for r in payload["results"]
        ]
