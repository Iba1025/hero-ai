"""Protocol contract tests — every adapter (stub or real) must pass these.

Run the same suite against every implementation via parametrize.
This is what makes the DEC-2 bake-off cheap (spec §10.1).
"""

from __future__ import annotations

import pytest

from hero.adapters.stub_calibrator import StubCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
from hero.graph.state import EvidenceChunk, TicketState
from hero.interfaces.calibrator import Calibrator
from hero.interfaces.catalog import CatalogResolver
from hero.interfaces.embedder import Embedder
from hero.interfaces.reranker import Reranker
from hero.interfaces.vlm import VLM


# ---------------------------------------------------------------------------
# Embedder contract
# ---------------------------------------------------------------------------
class EmbedderContractSuite:
    """Contract tests for any Embedder implementation."""

    def get_embedder(self) -> Embedder:
        raise NotImplementedError

    def test_satisfies_protocol(self) -> None:
        embedder = self.get_embedder()
        assert isinstance(embedder, Embedder)

    def test_has_model_id(self) -> None:
        embedder = self.get_embedder()
        assert isinstance(embedder.model_id, str)
        assert len(embedder.model_id) > 0

    @staticmethod
    def _page_image_bytes() -> bytes:
        """A valid minimal PNG — real embedders decode it, stubs ignore content."""
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(buf, format="PNG")
        return buf.getvalue()

    def test_embed_page_returns_multi_vector(self) -> None:
        embedder = self.get_embedder()
        result = embedder.embed_page(self._page_image_bytes())
        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], list)
        assert all(isinstance(v, float) for v in result[0])

    def test_embed_query_returns_multi_vector(self) -> None:
        embedder = self.get_embedder()
        result = embedder.embed_query("leaking pipe")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], list)
        assert all(isinstance(v, float) for v in result[0])


class TestStubEmbedder(EmbedderContractSuite):
    def get_embedder(self) -> Embedder:
        return StubEmbedder()


class _FakeBedrockBody:
    def __init__(self, payload: dict[str, object]) -> None:
        import json

        self._raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._raw


class _FakeBedrockEmbedClient:
    """Offline stand-in for bedrock-runtime — echoes Cohere Embed v3 shape."""

    def invoke_model(self, modelId: str, body: str) -> dict[str, object]:
        import json

        texts = json.loads(body)["texts"]
        return {"body": _FakeBedrockBody({"embeddings": [[0.1] * 1024 for _ in texts]})}


class TestBedrockCohereEmbedder(EmbedderContractSuite):
    """Lean-mode adapter (DEC-29) against a faked Bedrock client — CI-safe.

    The model is TEXT-ONLY: embed_page(image) raises by design, and ingestion
    routes page text via embed_page_text — so that one contract test is
    overridden to assert the documented raise + the text path instead.
    """

    def get_embedder(self) -> Embedder:
        from hero.adapters.bedrock_embedder import BedrockCohereEmbedder

        return BedrockCohereEmbedder(client=_FakeBedrockEmbedClient())

    def test_embed_page_returns_multi_vector(self) -> None:  # type: ignore[override]
        embedder = self.get_embedder()
        with pytest.raises(RuntimeError, match="text-only"):
            embedder.embed_page(self._page_image_bytes())
        # The page path for this adapter is text (DEC-29):
        result = embedder.embed_page_text("Section 4.2: compressor diagnostics")  # type: ignore[attr-defined]
        assert isinstance(result, list)
        assert len(result) == 1  # single vector as 1-element multivector
        assert all(isinstance(v, float) for v in result[0])

    def test_embed_page_texts_batch_shape(self) -> None:
        from hero.adapters.bedrock_embedder import BedrockCohereEmbedder

        embedder = BedrockCohereEmbedder(client=_FakeBedrockEmbedClient())
        result = embedder.embed_page_texts_batch(["page one", "", "page three"])
        assert len(result) == 3  # blank page still gets a vector
        assert all(len(mv) == 1 for mv in result)


# ---------------------------------------------------------------------------
# Reranker contract
# ---------------------------------------------------------------------------
class RerankerContractSuite:
    """Contract tests for any Reranker implementation."""

    def get_reranker(self) -> Reranker:
        raise NotImplementedError

    def _make_candidates(self, n: int = 10) -> list[EvidenceChunk]:
        return [
            EvidenceChunk(
                doc_id=f"doc-{i}",
                page=i,
                score=float(i) / n,
                retrieval_stage="fused",
            )
            for i in range(n)
        ]

    def test_satisfies_protocol(self) -> None:
        reranker = self.get_reranker()
        assert isinstance(reranker, Reranker)

    def test_rerank_returns_top_k(self) -> None:
        reranker = self.get_reranker()
        candidates = self._make_candidates(10)
        result = reranker.rerank("query", candidates, top_k=5)
        assert len(result) == 5

    def test_rerank_returns_evidence_chunks(self) -> None:
        reranker = self.get_reranker()
        candidates = self._make_candidates(3)
        result = reranker.rerank("query", candidates, top_k=3)
        for chunk in result:
            assert isinstance(chunk, EvidenceChunk)

    def test_rerank_handles_fewer_than_top_k(self) -> None:
        reranker = self.get_reranker()
        candidates = self._make_candidates(2)
        result = reranker.rerank("query", candidates, top_k=5)
        assert len(result) == 2


class TestStubReranker(RerankerContractSuite):
    def get_reranker(self) -> Reranker:
        return StubReranker()


class _FakeBedrockRerankClient:
    """Offline stand-in for bedrock-runtime — echoes Cohere Rerank 3.5 shape."""

    def invoke_model(self, modelId: str, body: str) -> dict[str, object]:
        import json

        req = json.loads(body)
        n = min(req["top_n"], len(req["documents"]))
        results = [{"index": i, "relevance_score": 1.0 - i * 0.1} for i in range(n)]
        return {"body": _FakeBedrockBody({"results": results})}


class TestCohereReranker(RerankerContractSuite):
    """Lean-mode Bedrock Rerank 3.5 adapter (DEC-29) — faked client, CI-safe."""

    def get_reranker(self) -> Reranker:
        from hero.adapters.cohere_reranker import CohereReranker

        return CohereReranker(client=_FakeBedrockRerankClient())

    def test_rerank_sets_reranked_stage(self) -> None:
        reranker = self.get_reranker()
        result = reranker.rerank("query", self._make_candidates(4), top_k=2)
        assert all(c.retrieval_stage == "reranked" for c in result)


# ---------------------------------------------------------------------------
# Calibrator contract
# ---------------------------------------------------------------------------
class CalibratorContractSuite:
    """Contract tests for any Calibrator implementation."""

    def get_calibrator(self) -> Calibrator:
        raise NotImplementedError

    def test_satisfies_protocol(self) -> None:
        calibrator = self.get_calibrator()
        assert isinstance(calibrator, Calibrator)

    def test_calibrate_returns_float(self) -> None:
        calibrator = self.get_calibrator()
        result = calibrator.calibrate(0.85, "plumbing")
        assert isinstance(result, float)

    def test_calibrate_in_valid_range(self) -> None:
        calibrator = self.get_calibrator()
        result = calibrator.calibrate(0.5, "hvac")
        assert 0.0 <= result <= 1.0

    def test_ece_returns_float(self) -> None:
        calibrator = self.get_calibrator()
        result = calibrator.ece()
        assert isinstance(result, float)
        assert result >= 0.0

    def test_fit_accepts_outcomes(self) -> None:
        calibrator = self.get_calibrator()
        outcomes = [(0.9, True), (0.3, False), (0.7, True)]
        calibrator.fit(outcomes)  # should not raise


class TestStubCalibrator(CalibratorContractSuite):
    def get_calibrator(self) -> Calibrator:
        return StubCalibrator()


class TestPlattCalibrator(CalibratorContractSuite):
    """Real Platt adapter (BL-2) — same contract as stub. sklearn only, no downloads."""

    def get_calibrator(self) -> Calibrator:
        from hero.adapters.platt import PlattCalibrator

        return PlattCalibrator()


class TestIsotonicCalibrator(CalibratorContractSuite):
    """Isotonic adapter (DEC-5 gated) — same contract as stub."""

    def get_calibrator(self) -> Calibrator:
        from hero.adapters.platt import IsotonicCalibrator

        return IsotonicCalibrator()


# ---------------------------------------------------------------------------
# VLM contract
# ---------------------------------------------------------------------------
class VLMContractSuite:
    """Contract tests for any VLM implementation."""

    def get_vlm(self) -> VLM:
        raise NotImplementedError

    def _make_state(self) -> TicketState:
        return TicketState(
            ticket_id="test-001",
            description="Water leaking from ceiling",
            trade="plumbing",
        )

    @pytest.mark.asyncio
    async def test_satisfies_protocol(self) -> None:
        vlm = self.get_vlm()
        assert isinstance(vlm, VLM)

    @pytest.mark.asyncio
    async def test_diagnose_returns_hypotheses(self) -> None:
        vlm = self.get_vlm()
        state = self._make_state()
        result = await vlm.diagnose(state)
        assert isinstance(result, list)
        assert len(result) >= 1
        for hyp in result:
            assert hasattr(hyp, "fault")
            assert hasattr(hyp, "claims")
            assert len(hyp.claims) >= 1

    @pytest.mark.asyncio
    async def test_diagnose_no_model_confidence(self) -> None:
        """INV-4: hypotheses must not carry model self-reported confidence."""
        vlm = self.get_vlm()
        state = self._make_state()
        result = await vlm.diagnose(state)
        for hyp in result:
            # calibrated_confidence may be set later by Calibrator, but
            # at diagnosis time it should be None
            assert hyp.calibrated_confidence is None

    @pytest.mark.asyncio
    async def test_decompose_claims_returns_strings(self) -> None:
        vlm = self.get_vlm()
        result = await vlm.decompose_claims("The compressor has failed")
        assert isinstance(result, list)
        assert all(isinstance(c, str) for c in result)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_check_entailment_returns_bool(self) -> None:
        vlm = self.get_vlm()
        result = await vlm.check_entailment("compressor failed", "Section 4.2: compressor issues")
        assert isinstance(result, bool)


class TestStubVLM(VLMContractSuite):
    def get_vlm(self) -> VLM:
        return StubVLM()


# ---------------------------------------------------------------------------
# CatalogResolver contract
# ---------------------------------------------------------------------------
class CatalogResolverContractSuite:
    """Contract tests for any CatalogResolver implementation."""

    def get_resolver(self) -> CatalogResolver:
        raise NotImplementedError

    @pytest.mark.asyncio
    async def test_satisfies_protocol(self) -> None:
        resolver = self.get_resolver()
        assert isinstance(resolver, CatalogResolver)

    @pytest.mark.asyncio
    async def test_resolve_returns_sku_or_none(self) -> None:
        resolver = self.get_resolver()
        result = await resolver.resolve("replacement compressor", "hvac")
        assert result is None or isinstance(result, str)


class TestStubCatalogResolver(CatalogResolverContractSuite):
    def get_resolver(self) -> CatalogResolver:
        return StubCatalogResolver()
