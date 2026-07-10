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
