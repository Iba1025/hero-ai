"""INV-5 (P4-5): organic CLARIFY — asks when it must, never when it must not.

Graph-level, stub adapters, MemorySaver:
- One organic round end to end: vague ticket → sufficiency says insufficient →
  interrupt with a concrete question → Command(resume=answer) → completes,
  exactly one round, clarified description carried into the loop-back.
- Hard-escalate trades NEVER clarify (safety anti-pattern: asking a tenant
  questions about a gas leak) — the sufficiency check is not even called.
- Hazard-keyword tickets on soft trades likewise go straight through.
- A triage "simple" verdict cannot skip the check (P4-5 rider): an
  insufficient fast-path ticket still asks, then loops into the full path.
- A sufficient full-path ticket pays the check but asks no question.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from hero.adapters.stub_calibrator import StubCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
from hero.graph.build import build_graph
from hero.graph.state import SufficiencyResult, TicketState, TriageResult

VAGUE_DESCRIPTION = "Something in the unit is broken and making a strange noise"
ANSWER = "It's the dishwasher in the kitchen"


class _CountingVLM(StubVLM):
    """StubVLM that counts sufficiency calls and can force insufficiency."""

    def __init__(self, always_insufficient: bool = False) -> None:
        self.sufficiency_calls = 0
        self._always_insufficient = always_insufficient

    async def assess_sufficiency(self, state: TicketState) -> SufficiencyResult:
        self.sufficiency_calls += 1
        if self._always_insufficient:
            return SufficiencyResult(
                sufficient=False, question="Which appliance or fixture is the problem?"
            )
        return await super().assess_sufficiency(state)


def _graph(vlm: StubVLM) -> Any:
    return build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=StubCalibrator(),
        vlm=vlm,
        catalog=StubCatalogResolver(),
        checkpointer=MemorySaver(),
    )


@pytest.mark.asyncio
async def test_organic_clarify_round_end_to_end() -> None:
    """Vague ticket → organic question → answer → resumed to completion."""
    vlm = _CountingVLM()
    graph = _graph(vlm)
    config = {"configurable": {"thread_id": "inv5-organic"}}

    result = await graph.ainvoke(
        {"ticket_id": "INV5-001", "description": VAGUE_DESCRIPTION},
        config=config,
    )

    # Interrupted at CLARIFY with the stub's concrete question — organically,
    # nothing was injected.
    assert vlm.sufficiency_calls == 1
    question = result.get("pending_question")
    assert question
    assert "which appliance" in question.lower()
    state = await graph.aget_state(config)
    assert state.next == ("clarify",)

    # Tenant answers → single organic round → completes.
    result = await graph.ainvoke(Command(resume=ANSWER), config=config)
    assert result.get("pending_question") is None
    assert result["clarify_rounds"] == 1
    assert f"[Clarification: {ANSWER}]" in result["description"]
    # P4-5 rider: the loop-back does NOT re-check — the tenant already
    # answered; at most one sufficiency call per ticket.
    assert vlm.sufficiency_calls == 1
    # Benign ticket completes the pipeline.
    assert result["verify_pass"] is True
    assert result["escalated"] is False
    assert result.get("work_order_id") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("trade", ["gas", "structural", "water_intrusion"])
async def test_hard_escalate_trades_never_clarify(trade: str) -> None:
    """Even a VLM that would ALWAYS ask is never consulted on a hard-escalate
    trade — the ticket goes straight through to the safety gate (INV-1)."""
    vlm = _CountingVLM(always_insufficient=True)
    graph = _graph(vlm)
    config = {"configurable": {"thread_id": f"inv5-hard-{trade}"}}

    result = await graph.ainvoke(
        {
            "ticket_id": f"INV5-{trade}",
            "description": "Something is wrong somewhere, no idea what",
            "trade": trade,
        },
        config=config,
    )

    assert vlm.sufficiency_calls == 0  # no question, no sufficiency tax
    assert result.get("pending_question") is None
    assert result["escalated"] is True
    assert result["escalation_reason"] == "hard_category"


@pytest.mark.asyncio
async def test_hazard_keyword_ticket_never_clarifies() -> None:
    """Hazard keyword on a soft trade: no question — escalates at the gate."""
    vlm = _CountingVLM(always_insufficient=True)
    graph = _graph(vlm)
    config = {"configurable": {"thread_id": "inv5-hazard"}}

    result = await graph.ainvoke(
        {
            "ticket_id": "INV5-HAZ",
            "description": "The outlet is sparking and something is broken",
        },
        config=config,
    )

    assert result.get("trade") == "electrical"  # soft trade — not hard-escalate
    assert vlm.sufficiency_calls == 0
    assert result.get("pending_question") is None
    assert result["escalated"] is True
    assert result["escalation_reason"] == "hazard_signal"


class _SimpleTriageVLM(_CountingVLM):
    """Triage always says 'simple' — routes every ticket to the fast path."""

    async def triage(self, description: str) -> TriageResult:
        return TriageResult(trade="other", urgency="routine", complexity="simple")


@pytest.mark.asyncio
async def test_triage_simple_verdict_cannot_skip_sufficiency() -> None:
    """INV-5 rider: a ticket the system would judge insufficient can never
    reach DIAGNOSE unasked merely because triage called it simple. The
    insufficient fast-path ticket CLARIFYs, then loops into the FULL path."""
    vlm = _SimpleTriageVLM()
    graph = _graph(vlm)
    config = {"configurable": {"thread_id": "inv5-fastpath"}}

    result = await graph.ainvoke(
        {"ticket_id": "INV5-FAST", "description": VAGUE_DESCRIPTION},
        config=config,
    )

    # Fast path taken — and the question was still asked.
    assert result["complexity"] == "simple"
    assert vlm.sufficiency_calls == 1
    assert result.get("pending_question")
    state = await graph.aget_state(config)
    assert state.next == ("clarify",)

    result = await graph.ainvoke(Command(resume=ANSWER), config=config)
    assert result.get("pending_question") is None
    assert result["clarify_rounds"] == 1
    # Loop-back re-entered the FULL retrieve path (BL-4) — evidence carries
    # full-path stage attribution, not bm25 — and did not re-check.
    assert all(e["retrieval_stage"] != "bm25" for e in result["evidence"])
    assert vlm.sufficiency_calls == 1
    assert result["escalated"] is False
    assert result.get("work_order_id") is not None


@pytest.mark.asyncio
async def test_sufficient_full_path_ticket_asks_no_question() -> None:
    """Plainly-sufficient ticket: the check runs, no question is asked."""
    vlm = _CountingVLM()
    graph = _graph(vlm)
    config = {"configurable": {"thread_id": "inv5-sufficient"}}

    result = await graph.ainvoke(
        {"ticket_id": "INV5-OK", "description": "HVAC not cooling on the third floor"},
        config=config,
    )

    assert vlm.sufficiency_calls == 1
    assert result.get("pending_question") is None
    assert result.get("clarify_rounds", 0) == 0
    assert result["escalated"] is False
