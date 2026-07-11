"""BL-6 claim-level VERIFY tests (DEC-6).

Covers: claim classifier, evidence-text gathering, per-type thresholds,
real-evidence wiring into entailment, INV-4 (calibrated_confidence only from
Calibrator), and the no-sensor path (INV-7).
"""

from __future__ import annotations

from typing import Any

import pytest

from hero.graph.nodes.verify import make_verify
from hero.verification.claims import classify_claim, gather_evidence_text

# ---------------------------------------------------------------------------
# Claim classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Replace the PT-100-SS trap assembly",
        "The compatible part is FC-200-BR",
        "Model PL-2000 requires the stainless variant",
        "Install an XR16 condenser unit",
    ],
)
def test_part_number_claims_classified_strict(text: str) -> None:
    assert classify_claim(text) == "part_number"


@pytest.mark.parametrize(
    "text",
    [
        "Water is leaking under the kitchen sink",
        "The P-trap is corroded at the joint",
        "The HVAC system has a faulty component",
        "Replacement part is required",
    ],
)
def test_descriptive_claims_classified_default(text: str) -> None:
    assert classify_claim(text) == "descriptive"


# ---------------------------------------------------------------------------
# Evidence text gathering
# ---------------------------------------------------------------------------


def test_gather_evidence_text_uses_chunk_text() -> None:
    chunks = [
        {"doc_id": "manual-1", "page": 3, "text": "Tighten the slip nut to 40 Nm."},
        {"doc_id": "manual-1", "page": 4, "text": "Use PTFE tape on threads."},
    ]
    out = gather_evidence_text(chunks)
    assert "[manual-1 p3] Tighten the slip nut to 40 Nm." in out
    assert "[manual-1 p4] Use PTFE tape on threads." in out


def test_gather_evidence_text_no_text_falls_back_to_citation_only() -> None:
    out = gather_evidence_text([{"doc_id": "m", "page": 1, "text": None}])
    assert out == "[m p1]"  # never invents text


def test_gather_evidence_text_empty() -> None:
    assert gather_evidence_text([]) == "No evidence retrieved."


def test_gather_evidence_text_truncates_long_chunks() -> None:
    out = gather_evidence_text(
        [{"doc_id": "m", "page": 1, "text": "x" * 5000}], max_chars_per_chunk=100
    )
    assert len(out) < 200


# ---------------------------------------------------------------------------
# VERIFY node — scripted adapters
# ---------------------------------------------------------------------------


class ScriptedVLM:
    """Entailment verdicts keyed by claim text; records evidence_text received."""

    def __init__(self, verdicts: dict[str, bool]) -> None:
        self.verdicts = verdicts
        self.seen_evidence: list[str] = []

    async def check_entailment(self, claim: str, evidence_text: str) -> bool:
        self.seen_evidence.append(evidence_text)
        return self.verdicts.get(claim, True)


class MarkerCalibrator:
    def calibrate(self, raw_grounding_score: float, trade: str) -> float:
        return 0.123  # marker: proves the number came from the Calibrator (INV-4)

    def fit(self, outcomes: list[tuple[float, bool]]) -> None: ...

    def ece(self) -> float:
        return 0.0


def _state(claims: list[str], evidence: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Ticket state with NO sensor data — VERIFY must work without it (INV-7)."""
    return {
        "trade": "plumbing",
        "hypotheses": [{"fault": "test fault", "claims": [{"text": c} for c in claims]}],
        "evidence": evidence if evidence is not None else [],
    }


EVIDENCE = [
    {
        "doc_id": "test-manual",
        "page": 0,
        "score": 0.99,
        "retrieval_stage": "reranked",
        "text": "The PT-100-SS P-trap installs under the sink with slip nuts.",
    }
]


@pytest.mark.asyncio
async def test_entailment_receives_real_evidence_text() -> None:
    """BL-6: EvidenceChunk.text is wired into check_entailment — no stub strings."""
    vlm = ScriptedVLM({})
    verify = make_verify(vlm, MarkerCalibrator(), 0.8, 1.0)
    await verify(_state(["Water is leaking"], EVIDENCE))
    assert len(vlm.seen_evidence) == 1
    assert "PT-100-SS P-trap installs under the sink" in vlm.seen_evidence[0]
    assert "stub evidence" not in vlm.seen_evidence[0]


@pytest.mark.asyncio
async def test_all_grounded_passes_and_sets_claim_fields() -> None:
    vlm = ScriptedVLM({})
    verify = make_verify(vlm, MarkerCalibrator(), 0.8, 1.0)
    result = await verify(_state(["Water is leaking", "Replace the PT-100-SS trap"], EVIDENCE))

    assert result["verify_pass"] is True
    claims = result["hypotheses"][0]["claims"]
    assert claims[0]["claim_type"] == "descriptive"
    assert claims[1]["claim_type"] == "part_number"
    for c in claims:
        assert c["grounded"] is True
        assert c["supporting_evidence"] == [
            {"doc_id": "test-manual", "page": 0, "score": 0.99, "retrieval_stage": "reranked"}
        ]  # citations only — text stripped


@pytest.mark.asyncio
async def test_descriptive_claims_pass_at_080() -> None:
    """4/5 descriptive claims grounded → 0.8 rate → passes at threshold 0.8."""
    claims = [f"descriptive claim {i}" for i in range(5)]
    vlm = ScriptedVLM({"descriptive claim 4": False})
    verify = make_verify(vlm, MarkerCalibrator(), 0.8, 1.0)
    result = await verify(_state(claims, EVIDENCE))
    assert result["verify_pass"] is True


@pytest.mark.asyncio
async def test_descriptive_claims_fail_below_080() -> None:
    """3/5 descriptive claims grounded → 0.6 rate → fails threshold 0.8."""
    claims = [f"descriptive claim {i}" for i in range(5)]
    vlm = ScriptedVLM({"descriptive claim 3": False, "descriptive claim 4": False})
    verify = make_verify(vlm, MarkerCalibrator(), 0.8, 1.0)
    result = await verify(_state(claims, EVIDENCE))
    assert result["verify_pass"] is False


@pytest.mark.asyncio
async def test_ungrounded_part_number_claim_fails_despite_high_overall_rate() -> None:
    """Part-number claims require 1.0 — one ungrounded part claim sinks the hypothesis
    even when the overall grounding rate clears 0.8."""
    claims = [f"descriptive claim {i}" for i in range(8)] + ["Order part FC-200-BR"]
    vlm = ScriptedVLM({"Order part FC-200-BR": False})  # overall rate 8/9 ≈ 0.89
    verify = make_verify(vlm, MarkerCalibrator(), 0.8, 1.0)
    result = await verify(_state(claims, EVIDENCE))
    assert result["verify_pass"] is False
    part_claim = result["hypotheses"][0]["claims"][-1]
    assert part_claim["claim_type"] == "part_number"
    assert part_claim["grounded"] is False
    assert part_claim["supporting_evidence"] == []


@pytest.mark.asyncio
async def test_calibrated_confidence_only_from_calibrator() -> None:
    """INV-4: the confidence on a hypothesis is exactly the Calibrator output."""
    verify = make_verify(ScriptedVLM({}), MarkerCalibrator(), 0.8, 1.0)
    result = await verify(_state(["Water is leaking"], EVIDENCE))
    assert result["hypotheses"][0]["calibrated_confidence"] == 0.123


@pytest.mark.asyncio
async def test_verify_works_with_no_evidence_and_no_sensors() -> None:
    """INV-7-adjacent: empty evidence and zero sensor data must not crash VERIFY."""
    vlm = ScriptedVLM({})
    verify = make_verify(vlm, MarkerCalibrator(), 0.8, 1.0)
    result = await verify(_state(["Water is leaking"], evidence=[]))
    assert vlm.seen_evidence == ["No evidence retrieved."]
    assert result["verify_pass"] in (True, False)  # deterministic, no exception


@pytest.mark.asyncio
async def test_hypothesis_with_zero_claims_fails() -> None:
    verify = make_verify(ScriptedVLM({}), MarkerCalibrator(), 0.8, 1.0)
    result = await verify(
        {"trade": "plumbing", "hypotheses": [{"fault": "f", "claims": []}], "evidence": []}
    )
    assert result["verify_pass"] is False
