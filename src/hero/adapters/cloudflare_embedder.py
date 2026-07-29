"""Cloudflare Workers AI BGE-M3 embedder — lean mode, Cloudflare variant.

API-hosted TEXT-ONLY embedding on Workers AI (``@cf/baai/bge-m3``, 1024-dim).

⚠️ **Residency: this is a recorded INV-2 exception, not compliance.** Workers
AI runs inference on Cloudflare's global network with no Canadian residency
commitment — page text and query text cross the border. Founder-approved
2026-07-30 as a pilot exception alongside DEC-28 (R2), recorded as DEC-87;
recorded in ``docs/residency.md``. The Bedrock ca-central-1 adapter
(``bedrock_embedder``) remains the INV-2-clean path and the migration target.

Lean-mode retrieval shape (DEC-29 unchanged): single-vector dense over the
already-extracted page text + the existing BM25 sparse, hybrid preserved in
Qdrant. Each embedding is a **1-element multivector** so the MaxSim collection
schema is untouched (MaxSim over 1x1 degenerates to cosine).

Text-only, so ``embed_page(image)`` raises loudly; ingestion routes page text
via ``embed_page_text`` / ``embed_page_texts_batch`` (same duck-typed pattern
as the Bedrock adapter).

Pricing (documented): $0.012 per M input tokens — confirm against the first
Cloudflare invoice.

Auth: Cloudflare API token with Workers AI permission (Bearer). The R2 S3
keys cannot call Workers AI — this is a separate credential.
"""

from __future__ import annotations

from typing import Any

import httpx

_MAX_TEXTS_PER_CALL = 96  # parity with the Bedrock adapter's batching

_API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareBgeEmbedder:
    """Embedder Protocol implementation on Workers AI ``@cf/baai/bge-m3``."""

    def __init__(
        self,
        account_id: str,
        api_token: str,
        model_id: str = "@cf/baai/bge-m3",
        client: Any = None,
    ) -> None:
        self.model_id = model_id
        self._url = f"{_API_BASE}/accounts/{account_id}/ai/run/{model_id}"
        self._client: Any = client or httpx.Client(
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    # -- Workers AI call ----------------------------------------------------
    def _embed(self, texts: list[str]) -> list[list[float]]:
        # Blank PDF pages still need a point; never send empty strings.
        safe = [t.strip() or "[blank page]" for t in texts]
        out: list[list[float]] = []
        for start in range(0, len(safe), _MAX_TEXTS_PER_CALL):
            resp = self._client.post(
                self._url,
                json={
                    "text": safe[start : start + _MAX_TEXTS_PER_CALL],
                    "truncate_inputs": True,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("success", False):
                raise RuntimeError(f"Workers AI embed failed: {payload.get('errors')}")
            result = payload["result"]
            # bge-m3 returns {"shape": [n, 1024], "data": [[...], ...]}; some
            # deployments nest as {"response": {...}} — accept both.
            data = result.get("data") or result.get("response", {}).get("data")
            if data is None:
                raise RuntimeError(f"Workers AI embed: unrecognised result shape {result!r:.200}")
            out.extend([[float(v) for v in emb] for emb in data])
        return out

    # -- Embedder Protocol --------------------------------------------------
    def embed_page(self, image: bytes) -> list[list[float]]:
        raise RuntimeError(
            "CloudflareBgeEmbedder is text-only: @cf/baai/bge-m3 takes no images. "
            "Ingestion routes extracted page text via embed_page_text; for visual "
            "page embedding use EMBEDDER_IMPL=colmodernvbert (self-hosted)."
        )

    def embed_query(self, text: str) -> list[list[float]]:
        """1-element multivector for a query (MaxSim degenerates to cosine)."""
        return [self._embed([text])[0]]

    # -- text-page extensions (duck-typed, used by ingestion) ---------------
    def embed_page_text(self, text: str) -> list[list[float]]:
        """1-element multivector for a page's extracted text."""
        return [self._embed([text])[0]]

    def embed_page_texts_batch(self, texts: list[str]) -> list[list[list[float]]]:
        """Batched page-text embedding — one API call per 96 pages."""
        return [[emb] for emb in self._embed(texts)]
