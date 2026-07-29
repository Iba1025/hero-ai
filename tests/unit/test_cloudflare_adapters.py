"""Cloudflare Workers AI adapter contracts — faked HTTP client, CI-safe.

Same suites as every other adapter (test_adapter_contracts) so the lean-mode
Cloudflare variant is held to the identical Protocol contract as Bedrock,
self-hosted, and stub. Live-shape verification happens at the DEC-29 eval
gate; these tests pin the documented Workers AI request/response schema.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from hero.adapters.cloudflare_embedder import CloudflareBgeEmbedder
from hero.adapters.cloudflare_reranker import CloudflareBgeReranker
from hero.interfaces.embedder import Embedder
from hero.interfaces.reranker import Reranker
from tests.unit.test_adapter_contracts import EmbedderContractSuite, RerankerContractSuite

_DIM = 1024  # bge-m3


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeEmbedHttp:
    """Echoes the documented @cf/baai/bge-m3 response shape."""

    def __init__(self) -> None:
        self.last_json: dict[str, Any] | None = None

    def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
        self.last_json = json
        texts = json["text"]
        return _FakeResponse(
            {
                "success": True,
                "result": {
                    "shape": [len(texts), _DIM],
                    "data": [[0.1] * _DIM for _ in texts],
                },
            }
        )


class _FakeRerankHttp:
    """Echoes the documented @cf/baai/bge-reranker-base response shape.

    Scores are raw logits (can be negative) — the adapter must sigmoid them.
    """

    def __init__(self) -> None:
        self.last_json: dict[str, Any] | None = None

    def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
        self.last_json = json
        n = len(json["contexts"])
        ranked = [{"id": i, "score": 4.0 - i} for i in range(n)]  # logits, descending
        return _FakeResponse({"success": True, "result": {"response": ranked}})


class TestCloudflareBgeEmbedder(EmbedderContractSuite):
    """Text-only adapter — embed_page raises by design (same as Bedrock)."""

    def get_embedder(self) -> Embedder:
        return CloudflareBgeEmbedder(account_id="acct", api_token="t", client=_FakeEmbedHttp())

    def test_embed_page_returns_multi_vector(self) -> None:  # type: ignore[override]
        embedder = self.get_embedder()
        with pytest.raises(RuntimeError, match="text-only"):
            embedder.embed_page(self._page_image_bytes())
        result = embedder.embed_page_text("Section 4.2: compressor diagnostics")  # type: ignore[attr-defined]
        assert isinstance(result, list)
        assert len(result) == 1  # single vector as 1-element multivector
        assert len(result[0]) == _DIM
        assert all(isinstance(v, float) for v in result[0])

    def test_embed_page_texts_batch_shape(self) -> None:
        embedder = CloudflareBgeEmbedder(account_id="a", api_token="t", client=_FakeEmbedHttp())
        result = embedder.embed_page_texts_batch(["page one", "", "page three"])
        assert len(result) == 3  # blank page still gets a vector
        assert all(len(mv) == 1 for mv in result)

    def test_blank_text_never_sent_empty(self) -> None:
        http = _FakeEmbedHttp()
        embedder = CloudflareBgeEmbedder(account_id="a", api_token="t", client=http)
        embedder.embed_page_text("   ")
        assert http.last_json is not None
        assert http.last_json["text"] == ["[blank page]"]


class TestCloudflareBgeReranker(RerankerContractSuite):
    def get_reranker(self) -> Reranker:
        return CloudflareBgeReranker(account_id="acct", api_token="t", client=_FakeRerankHttp())

    def test_scores_are_sigmoided_into_unit_interval(self) -> None:
        reranker = CloudflareBgeReranker(account_id="a", api_token="t", client=_FakeRerankHttp())
        result = reranker.rerank("query", self._make_candidates(4), top_k=4)
        assert all(0.0 <= c.score <= 1.0 for c in result)
        # Fake's top logit is 4.0 → sigmoid(4.0); ordering preserved, stage stamped
        assert result[0].score == pytest.approx(1.0 / (1.0 + math.exp(-4.0)))
        assert [c.score for c in result] == sorted((c.score for c in result), reverse=True)
        assert all(c.retrieval_stage == "reranked" for c in result)

    def test_textless_chunks_get_fallback_documents(self) -> None:
        http = _FakeRerankHttp()
        reranker = CloudflareBgeReranker(account_id="a", api_token="t", client=http)
        reranker.rerank("query", self._make_candidates(2), top_k=2)
        assert http.last_json is not None
        assert all("Document doc-" in ctx["text"] for ctx in http.last_json["contexts"])

    def test_empty_candidates_short_circuit(self) -> None:
        class _ExplodingHttp:
            def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
                raise AssertionError("must not call the API for zero candidates")

        reranker = CloudflareBgeReranker(account_id="a", api_token="t", client=_ExplodingHttp())
        assert reranker.rerank("query", [], top_k=5) == []
