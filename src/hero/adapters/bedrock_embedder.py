"""Bedrock Cohere Embed v3 adapter — lean mode (DEC-29).

API-hosted embedding on AWS Bedrock **ca-central-1** (in-region per AWS docs
→ no INV-2 gap). Model: ``cohere.embed-multilingual-v3`` — TEXT-ONLY, 512-token
context (``truncate: END`` guards overflow).

Lean-mode retrieval shape (DEC-29): single-vector dense over the already-
extracted page text + the existing BM25 sparse, hybrid preserved in Qdrant.
Each embedding is returned as a **1-element multivector** so the MaxSim
collection schema is untouched (MaxSim over 1x1 degenerates to cosine).

Because the model is text-only, ``embed_page(image)`` raises loudly; ingestion
routes page text via ``embed_page_text`` / ``embed_page_texts_batch`` (same
duck-typed pattern as ``embed_pages_batch``). The self-hosted ColPali adapter
remains the visual-signal path (reversion trigger in DEC-29).

Per-call cost (documented for DEC-29): listed on-demand rate $0.0001 per 1K
input tokens ≈ $0.00005/page at the 512-token cap, ≈ $0.000002/query —
confirm against the first AWS invoice.

Auth: standard AWS credential chain. For a long-term Bedrock API key, pass
``api_key`` (exported as ``AWS_BEARER_TOKEN_BEDROCK``, the only mechanism
botocore supports for bearer auth).
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3  # type: ignore[import-untyped]

_MAX_TEXTS_PER_CALL = 96  # Bedrock Cohere Embed limit


class BedrockCohereEmbedder:
    """Embedder Protocol implementation on Bedrock Cohere Embed v3 (DEC-29)."""

    def __init__(
        self,
        region: str = "ca-central-1",
        model_id: str = "cohere.embed-multilingual-v3",
        api_key: str = "",
        client: Any = None,
    ) -> None:
        self.model_id = model_id
        if api_key:
            # botocore reads long-term Bedrock API keys ONLY from this env var.
            os.environ.setdefault("AWS_BEARER_TOKEN_BEDROCK", api_key)
        self._client: Any = client or boto3.client("bedrock-runtime", region_name=region)

    # -- Bedrock call -------------------------------------------------------
    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        # Cohere rejects empty strings; blank PDF pages still need a point.
        safe = [t.strip() or "[blank page]" for t in texts]
        out: list[list[float]] = []
        for start in range(0, len(safe), _MAX_TEXTS_PER_CALL):
            body = json.dumps(
                {
                    "texts": safe[start : start + _MAX_TEXTS_PER_CALL],
                    "input_type": input_type,
                    "truncate": "END",
                }
            )
            resp = self._client.invoke_model(modelId=self.model_id, body=body)
            payload = json.loads(resp["body"].read())
            out.extend([[float(v) for v in emb] for emb in payload["embeddings"]])
        return out

    # -- Embedder Protocol --------------------------------------------------
    def embed_page(self, image: bytes) -> list[list[float]]:
        raise RuntimeError(
            "BedrockCohereEmbedder is text-only (DEC-29): cohere.embed-multilingual-v3 "
            "takes no images. Ingestion routes extracted page text via embed_page_text; "
            "for visual page embedding use EMBEDDER_IMPL=colmodernvbert (self-hosted)."
        )

    def embed_query(self, text: str) -> list[list[float]]:
        """1-element multivector for a query (MaxSim degenerates to cosine)."""
        return [self._embed([text], "search_query")[0]]

    # -- text-page extensions (duck-typed, used by ingestion) ---------------
    def embed_page_text(self, text: str) -> list[list[float]]:
        """1-element multivector for a page's extracted text."""
        return [self._embed([text], "search_document")[0]]

    def embed_page_texts_batch(self, texts: list[str]) -> list[list[list[float]]]:
        """Batched page-text embedding — one API call per 96 pages."""
        return [[emb] for emb in self._embed(texts, "search_document")]
