"""INV-1: gas/HV/structural/water tickets escalate even with grounding rate 1.0.

Safety gate is hard, not advisory. For gas, high-voltage, structural,
and water-intrusion categories, escalate to a licensed trade REGARDLESS
of confidence score.
"""

from __future__ import annotations

from typing import Any

import pytest

from hero.safety.gate import safety_check


@pytest.mark.parametrize(
    "trade",
    ["gas", "electrical_high_voltage", "structural", "water_intrusion"],
)
def test_hard_escalation_trades_always_escalate(trade: str) -> None:
    """Even with perfect verification, hard-escalation trades must escalate."""
    decision = safety_check(
        trade=trade,
        verify_pass=True,  # perfect verification
        description="Routine maintenance check",
        hypotheses=[{"fault": "Minor issue", "claims": []}],
    )
    assert decision.escalate is True
    assert decision.reason == "hard_category"


@pytest.mark.parametrize(
    "trade",
    [
        "gas",
        "structural",
        "water_intrusion",
        # electrical_high_voltage is a safety sub-classification, not a valid
        # TradeCategory in TicketState — tested at safety_check unit level above
    ],
)
@pytest.mark.asyncio
async def test_hard_trades_escalate_in_graph(trade: str, stub_graph: Any) -> None:
    """End-to-end: hard-escalation trades terminate with escalation in the graph."""
    config = {"configurable": {"thread_id": f"inv1-{trade}"}}

    # Inject trade directly — triage will be overridden by the state
    result = await stub_graph.ainvoke(
        {
            "ticket_id": f"INV1-{trade}",
            "description": f"Test ticket for {trade}",
            "trade": trade,
        },
        config=config,
    )

    assert result["escalated"] is True
    assert result["escalation_reason"] == "hard_category"
    # Escalated tickets must NOT proceed to RESOLVE/PROCURE
    assert result.get("work_order_id") is None
    assert result.get("sku") is None


def test_non_hard_trade_does_not_auto_escalate() -> None:
    """A non-hard trade with passing verification should NOT escalate."""
    decision = safety_check(
        trade="plumbing",
        verify_pass=True,
        description="Dripping faucet",
        hypotheses=[{"fault": "Worn washer", "claims": []}],
    )
    assert decision.escalate is False


def test_verification_failure_escalates() -> None:
    """Failed verification must escalate regardless of trade."""
    decision = safety_check(
        trade="plumbing",
        verify_pass=False,
        description="Dripping faucet",
        hypotheses=[{"fault": "Worn washer", "claims": []}],
    )
    assert decision.escalate is True
    assert decision.reason == "verification_failed"


def test_hazard_keywords_escalate() -> None:
    """Hazard keywords in description trigger escalation."""
    decision = safety_check(
        trade="appliance",
        verify_pass=True,
        description="Dishwasher has a gas leak near the connection",
        hypotheses=[{"fault": "Faulty valve", "claims": []}],
    )
    assert decision.escalate is True
    assert decision.reason == "hazard_signal"
