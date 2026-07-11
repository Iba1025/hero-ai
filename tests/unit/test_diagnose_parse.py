"""P3-1.5: strict diagnosis parsing + diagnosis_unparseable escalation.

A diagnosis response that does not parse into the expected shape must never
become a placeholder fault ("Unknown fault") — it escalates to a human.
Also covers the claims/reasoning split (VERIFY does not gate reasoning)
and the bounded-concurrency entailment fan-out in VERIFY.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from hero.adapters.litellm_vlm import parse_diagnosis
from hero.graph.nodes.diagnose import make_diagnose
from hero.graph.nodes.safety_gate import safety_gate
from hero.graph.nodes.verify import make_verify
from hero.graph.state import TicketState
from hero.interfaces.vlm import DiagnosisParseError

# ---------------------------------------------------------------------------
# parse_diagnosis
# ---------------------------------------------------------------------------


def test_parse_valid_response_with_reasoning() -> None:
    raw = json.dumps(
        {
            "hypotheses": [
                {
                    "fault": "Loose P-trap connection",
                    "claims": [
                        {"text": "P-trap PT-100-SS connects drain to wall pipe [test-manual p0]"},
                        "Leaking under sink: check P-trap connections [test-manual p2]",
                    ],
                    "reasoning": ["Slip nuts loosen over time", "Run water to confirm"],
                }
            ]
        }
    )
    hypotheses = parse_diagnosis(raw)
    assert len(hypotheses) == 1
    hyp = hypotheses[0]
    assert hyp.fault == "Loose P-trap connection"
    assert len(hyp.claims) == 2
    assert hyp.claims[1].text.startswith("Leaking under sink")
    assert hyp.reasoning == ["Slip nuts loosen over time", "Run water to confirm"]
    # INV-4: parser never sets confidence
    assert hyp.calibrated_confidence is None


def test_parse_bare_list_and_missing_reasoning_ok() -> None:
    raw = json.dumps([{"fault": "f", "claims": [{"text": "c"}]}])
    hypotheses = parse_diagnosis(raw)
    assert hypotheses[0].reasoning == []


@pytest.mark.parametrize(
    "raw",
    [
        "this is not JSON at all",
        "{}",
        '{"hypotheses": []}',
        '{"hypotheses": "nope"}',
        '{"hypotheses": [42]}',
        '{"hypotheses": [{"claims": [{"text": "no fault key"}]}]}',
        '{"hypotheses": [{"fault": "", "claims": [{"text": "empty fault"}]}]}',
        '{"hypotheses": [{"fault": "f", "claims": []}]}',
        '{"hypotheses": [{"fault": "f"}]}',
        '{"hypotheses": [{"fault": "f", "claims": [{"note": "claim without text"}]}]}',
        '{"hypotheses": [{"fault": "f", "claims": [{"text": ""}]}]}',
        '{"hypotheses": [{"fault": "f", "claims": ["c"], "reasoning": "not a list"}]}',
    ],
)
def test_parse_invalid_shapes_raise(raw: str) -> None:
    with pytest.raises(DiagnosisParseError):
        parse_diagnosis(raw)


def test_parse_never_emits_placeholder_fault() -> None:
    """The old behavior turned unparseable output into fault='Unknown fault'."""
    with pytest.raises(DiagnosisParseError):
        parse_diagnosis("The P-trap is leaking, probably.")


# ---------------------------------------------------------------------------
# DIAGNOSE node escalation
# ---------------------------------------------------------------------------


class _UnparseableVLM:
    async def diagnose(self, state: TicketState) -> Any:
        raise DiagnosisParseError("bad shape")

    async def decompose_claims(self, hypothesis_text: str) -> list[str]:
        return []

    async def check_entailment(self, claim: str, evidence_text: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_diagnose_node_escalates_on_parse_error() -> None:
    node = make_diagnose(_UnparseableVLM())
    result = await node({"ticket_id": "t-1", "description": "leak"})
    assert result["hypotheses"] == []
    assert result["escalated"] is True
    assert result["escalation_reason"] == "diagnosis_unparseable"


def test_safety_gate_preserves_diagnosis_unparseable() -> None:
    result = safety_gate(
        {
            "trade": "plumbing",
            "verify_pass": False,
            "description": "leak",
            "hypotheses": [],
            "escalated": True,
            "escalation_reason": "diagnosis_unparseable",
        }
    )
    assert result == {"escalated": True, "escalation_reason": "diagnosis_unparseable"}


def test_safety_gate_still_escalates_verification_failure() -> None:
    result = safety_gate(
        {
            "trade": "plumbing",
            "verify_pass": False,
            "description": "leak",
            "hypotheses": [],
        }
    )
    assert result["escalated"] is True
    assert result["escalation_reason"] == "verification_failed"


# ---------------------------------------------------------------------------
# VERIFY: zero hypotheses fail; entailment fan-out is bounded + order-safe
# ---------------------------------------------------------------------------


class _IdentityCalibrator:
    def calibrate(self, grounding_rate: float, trade: str) -> float:
        return grounding_rate


class _CountingVLM:
    """Entailment stub that records concurrency and returns text-derived verdicts."""

    def __init__(self) -> None:
        self.current = 0
        self.max_concurrent = 0

    async def diagnose(self, state: TicketState) -> Any:
        raise NotImplementedError

    async def decompose_claims(self, hypothesis_text: str) -> list[str]:
        return []

    async def check_entailment(self, claim: str, evidence_text: str) -> bool:
        self.current += 1
        self.max_concurrent = max(self.max_concurrent, self.current)
        await asyncio.sleep(0.02)
        self.current -= 1
        return "grounded" in claim


@pytest.mark.asyncio
async def test_verify_zero_hypotheses_fails() -> None:
    node = make_verify(_CountingVLM(), _IdentityCalibrator(), 0.8)
    result = await node({"hypotheses": [], "trade": "plumbing", "evidence": []})
    assert result["verify_pass"] is False


@pytest.mark.asyncio
async def test_verify_entailment_concurrency_bounded_and_order_preserved() -> None:
    vlm = _CountingVLM()
    node = make_verify(vlm, _IdentityCalibrator(), 0.8)
    claims = [{"text": f"claim {i} {'grounded' if i % 2 == 0 else 'floating'}"} for i in range(12)]
    state = {
        "hypotheses": [{"fault": "f", "claims": claims}],
        "trade": "plumbing",
        "evidence": [{"doc_id": "d", "page": 0, "text": "evidence text"}],
    }
    result = await node(state)

    assert 1 < vlm.max_concurrent <= 5  # parallel, but bounded
    verdicts = [c["grounded"] for c in result["hypotheses"][0]["claims"]]
    assert verdicts == [i % 2 == 0 for i in range(12)]  # order preserved
