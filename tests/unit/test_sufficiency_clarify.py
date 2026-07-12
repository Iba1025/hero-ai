"""P4-5 (INV-5): sufficiency check + organic CLARIFY plumbing.

Covers:
- parse_sufficiency strict shapes and the generic-question gate (a generic
  question must never reach a tenant — SufficiencyParseError, fail open).
- clarify_allowed deterministic guardrail (P4-5b): hard-escalate trades and
  hazard-keyword descriptions never CLARIFY.
- RETRIEVE node: insufficient → pending_question set; sufficient → not set;
  fail-open on parse/call failure; sufficiency skipped (no VLM call, no tax)
  on fast path, preset pending_question, clarify cap, and hazard tickets.
- StubVLM.assess_sufficiency determinism: fires only on unresolvable-trade +
  vague-marker tickets, and never after a clarification round.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from hero.adapters.litellm_vlm import parse_sufficiency
from hero.adapters.stub_vlm import StubVLM
from hero.graph.nodes.retrieve import make_retrieve
from hero.graph.state import SufficiencyResult, TicketState
from hero.interfaces.vlm import SufficiencyParseError
from hero.safety.gate import clarify_allowed

# ---------------------------------------------------------------------------
# parse_sufficiency
# ---------------------------------------------------------------------------

CONCRETE_QUESTION = "Is the leak coming from under the sink or from the ceiling?"


def test_parse_sufficiency_sufficient() -> None:
    result = parse_sufficiency(json.dumps({"sufficient": True, "question": None}))
    assert result == SufficiencyResult(sufficient=True, question=None)


def test_parse_sufficiency_sufficient_drops_stray_question() -> None:
    """A question alongside sufficient=true is never surfaced."""
    result = parse_sufficiency(json.dumps({"sufficient": True, "question": CONCRETE_QUESTION}))
    assert result.question is None


def test_parse_sufficiency_insufficient_with_concrete_question() -> None:
    raw = json.dumps({"sufficient": False, "question": f"  {CONCRETE_QUESTION}  "})
    result = parse_sufficiency(raw)
    assert result.sufficient is False
    assert result.question == CONCRETE_QUESTION  # stripped


@pytest.mark.parametrize(
    "raw",
    [
        "not json {",
        json.dumps(["sufficient", True]),  # non-object
        json.dumps({"question": "x"}),  # missing sufficient
        json.dumps({"sufficient": "maybe"}),  # wrong type
        json.dumps({"sufficient": False, "question": None}),  # no question
        json.dumps({"sufficient": False, "question": "Where?"}),  # too short
    ],
)
def test_parse_sufficiency_bad_shapes(raw: str) -> None:
    with pytest.raises(SufficiencyParseError):
        parse_sufficiency(raw)


@pytest.mark.parametrize(
    "question",
    [
        "Can you please provide more details?",
        "Please describe the issue you are having.",
        "Could you clarify what is happening in the unit?",
        "Tell me more about the problem with the fixture.",
        "We need additional information to proceed with this ticket.",
    ],
)
def test_parse_sufficiency_rejects_generic_questions(question: str) -> None:
    """The generic-question gate: never surfaced to a tenant (P4-5)."""
    with pytest.raises(SufficiencyParseError):
        parse_sufficiency(json.dumps({"sufficient": False, "question": question}))


# ---------------------------------------------------------------------------
# clarify_allowed guardrail (P4-5b, INV-1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "trade",
    ["gas", "electrical_high_voltage", "structural", "water_intrusion"],
)
def test_clarify_never_allowed_on_hard_escalate_trades(trade: str) -> None:
    """Asking a tenant questions about a gas leak is a safety anti-pattern."""
    assert clarify_allowed(trade=trade, description="Routine-sounding description") is False


def test_clarify_never_allowed_on_hazard_keywords() -> None:
    """Hazard keyword in the description blocks CLARIFY even on a soft trade."""
    assert clarify_allowed(trade="electrical", description="The outlet is sparking") is False
    assert clarify_allowed(trade="appliance", description="I smell a gas leak") is False


def test_clarify_allowed_on_benign_ticket() -> None:
    assert clarify_allowed(trade="appliance", description="Dishwasher is not draining") is True
    assert clarify_allowed(trade=None, description="Odd noise from the closet") is True


# ---------------------------------------------------------------------------
# RETRIEVE node — sufficiency wiring, fail-open, skip conditions
# ---------------------------------------------------------------------------


class _SpySufficiencyVLM:
    """Records assess_sufficiency calls; returns a fixed result or raises."""

    def __init__(
        self, result: SufficiencyResult | None = None, exc: Exception | None = None
    ) -> None:
        self._result = result
        self._exc = exc
        self.calls = 0

    async def assess_sufficiency(self, state: TicketState) -> SufficiencyResult:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        assert self._result is not None
        return self._result


class _NoopEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]


class _PassthroughReranker:
    def rerank(self, query: str, candidates: list[Any], top_k: int = 5) -> list[Any]:
        return candidates[:top_k]


def _state(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ticket_id": "P45-TEST",
        "description": "Odd noise from the closet",
        "trade": "other",
    }
    base.update(overrides)
    return base


def _node(vlm: Any, fast_path: bool = False) -> Any:
    return make_retrieve(_NoopEmbedder(), _PassthroughReranker(), fast_path=fast_path, vlm=vlm)


def test_insufficient_sets_pending_question() -> None:
    vlm = _SpySufficiencyVLM(SufficiencyResult(sufficient=False, question=CONCRETE_QUESTION))
    out = asyncio.run(_node(vlm)(_state()))
    assert out["pending_question"] == CONCRETE_QUESTION
    assert len(out["evidence"]) == 5  # evidence still returned
    assert vlm.calls == 1


def test_sufficient_does_not_set_pending_question() -> None:
    vlm = _SpySufficiencyVLM(SufficiencyResult(sufficient=True))
    out = asyncio.run(_node(vlm)(_state()))
    assert "pending_question" not in out
    assert vlm.calls == 1


@pytest.mark.parametrize(
    "exc",
    [SufficiencyParseError("generic question rejected"), RuntimeError("provider down")],
)
def test_sufficiency_failure_fails_open(exc: Exception) -> None:
    """A bad sufficiency call must never block a ticket — proceed to DIAGNOSE."""
    vlm = _SpySufficiencyVLM(exc=exc)
    out = asyncio.run(_node(vlm)(_state()))
    assert "pending_question" not in out
    assert len(out["evidence"]) == 5


def test_no_sufficiency_on_fast_path() -> None:
    """Full path only — simple tickets never pay the sufficiency tax."""
    vlm = _SpySufficiencyVLM(SufficiencyResult(sufficient=False, question=CONCRETE_QUESTION))
    out = asyncio.run(_node(vlm, fast_path=True)(_state()))
    assert "pending_question" not in out
    assert vlm.calls == 0


def test_no_sufficiency_when_question_already_pending() -> None:
    """Preset pending_question (resume/injection paths) is never clobbered."""
    vlm = _SpySufficiencyVLM(SufficiencyResult(sufficient=False, question=CONCRETE_QUESTION))
    out = asyncio.run(_node(vlm)(_state(pending_question="Which unit are you in?")))
    assert "pending_question" not in out  # delta leaves the preset question alone
    assert vlm.calls == 0


def test_no_sufficiency_at_clarify_cap() -> None:
    """clarify_rounds cap unchanged: at the cap the question would be ignored."""
    vlm = _SpySufficiencyVLM(SufficiencyResult(sufficient=False, question=CONCRETE_QUESTION))
    out = asyncio.run(_node(vlm)(_state(clarify_rounds=3)))
    assert "pending_question" not in out
    assert vlm.calls == 0


@pytest.mark.parametrize(
    ("trade", "description"),
    [
        ("gas", "Something smells strange near the furnace closet"),
        ("structural", "Something is wrong with the wall, no idea what"),
        ("water_intrusion", "Something is dripping somewhere"),
        ("electrical", "The outlet is sparking and something is broken"),  # hazard keyword
    ],
)
def test_no_sufficiency_on_hazard_tickets(trade: str, description: str) -> None:
    """Guardrail consulted BEFORE the VLM call — hazards go straight through
    to DIAGNOSE → VERIFY → SAFETY_GATE and never pay the sufficiency tax."""
    vlm = _SpySufficiencyVLM(SufficiencyResult(sufficient=False, question=CONCRETE_QUESTION))
    out = asyncio.run(_node(vlm)(_state(trade=trade, description=description)))
    assert "pending_question" not in out
    assert vlm.calls == 0


def test_no_sufficiency_without_vlm() -> None:
    out = asyncio.run(_node(None)(_state()))
    assert "pending_question" not in out


# ---------------------------------------------------------------------------
# StubVLM.assess_sufficiency determinism
# ---------------------------------------------------------------------------

VAGUE_DESCRIPTION = "Something in the unit is broken and making a strange noise"


def _ticket(description: str, trade: str | None) -> TicketState:
    return TicketState(ticket_id="P45-STUB", description=description, trade=trade)


def test_stub_insufficient_on_vague_unresolvable_ticket() -> None:
    result = asyncio.run(StubVLM().assess_sufficiency(_ticket(VAGUE_DESCRIPTION, "other")))
    assert result.sufficient is False
    assert result.question is not None
    # The stub's question must itself pass the generic-question parse gate.
    parsed = parse_sufficiency(json.dumps({"sufficient": False, "question": result.question}))
    assert parsed.question == result.question


def test_stub_sufficient_when_trade_resolves() -> None:
    """Vague wording with a concrete trade is diagnosable — never ask."""
    result = asyncio.run(StubVLM().assess_sufficiency(_ticket(VAGUE_DESCRIPTION, "hvac")))
    assert result.sufficient is True


def test_stub_sufficient_on_concrete_description() -> None:
    result = asyncio.run(
        StubVLM().assess_sufficiency(_ticket("Radiator cold at the top, hot at bottom", "other"))
    )
    assert result.sufficient is True


def test_stub_sufficient_after_clarification_round() -> None:
    """The [Clarification: ...] suffix makes the loop-back pass — at most one
    organic round from the stub."""
    clarified = VAGUE_DESCRIPTION + "\n[Clarification: It's the dishwasher in the kitchen]"
    result = asyncio.run(StubVLM().assess_sufficiency(_ticket(clarified, "other")))
    assert result.sufficient is True
