"""Contract tests for real adapters — skipped in CI (no model downloads).

Run locally with models cached:
    uv run pytest tests/unit/test_real_adapter_contracts.py -v

These use the SAME contract test suites as stubs (spec §10.1).
"""

from __future__ import annotations

import os

import pytest

from hero.interfaces.embedder import Embedder
from hero.interfaces.reranker import Reranker
from tests.unit.test_adapter_contracts import EmbedderContractSuite, RerankerContractSuite

requires_models = pytest.mark.skipif(
    os.environ.get("HERO_TEST_MODELS", "") != "1",
    reason="Set HERO_TEST_MODELS=1 to run real adapter tests (requires model downloads)",
)


@requires_models
class TestColModernVBertEmbedder(EmbedderContractSuite):
    def get_embedder(self) -> Embedder:
        from hero.adapters.colmodernvbert import ColModernVBertEmbedder

        return ColModernVBertEmbedder()


@requires_models
class TestBGEReranker(RerankerContractSuite):
    def get_reranker(self) -> Reranker:
        from hero.adapters.bge_reranker import BGEReranker

        return BGEReranker()


# ---------------------------------------------------------------------------
# Lean-mode Bedrock adapters (DEC-29) — live calls to ca-central-1.
# Gated separately from model downloads: need AWS credentials, cost ~$0.01.
# ---------------------------------------------------------------------------
requires_bedrock = pytest.mark.skipif(
    os.environ.get("HERO_TEST_BEDROCK", "") != "1",
    reason="Set HERO_TEST_BEDROCK=1 (with AWS creds for ca-central-1) to hit Bedrock live",
)


@requires_bedrock
class TestLiveBedrockCohereEmbedder(EmbedderContractSuite):
    def get_embedder(self) -> Embedder:
        from hero.adapters.bedrock_embedder import BedrockCohereEmbedder

        return BedrockCohereEmbedder()

    def test_embed_page_returns_multi_vector(self) -> None:  # type: ignore[override]
        # Text-only adapter (DEC-29): the page path is embed_page_text.
        embedder = self.get_embedder()
        with pytest.raises(RuntimeError, match="text-only"):
            embedder.embed_page(self._page_image_bytes())
        result = embedder.embed_page_text("Compressor short-cycles; check contactor")  # type: ignore[attr-defined]
        assert len(result) == 1
        assert len(result[0]) == 1024  # Embed v3 output dim


@requires_bedrock
class TestLiveCohereReranker(RerankerContractSuite):
    def get_reranker(self) -> Reranker:
        from hero.adapters.cohere_reranker import CohereReranker

        return CohereReranker()
