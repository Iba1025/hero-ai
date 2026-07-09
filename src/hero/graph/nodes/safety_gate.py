"""SAFETY_GATE node — hard escalation check (INV-1).

Delegates to the pure safety.gate module — no LLM calls.
VERIFY is mandatory before this node (INV-8).
"""

from __future__ import annotations

from typing import Any

from hero.safety.gate import safety_check


def safety_gate(state: dict[str, Any]) -> dict[str, Any]:
    """Run the deterministic safety gate. Confidence is NOT an input (INV-1)."""
    trade = state.get("trade")
    verify_pass = state.get("verify_pass", False)
    description = state.get("description", "")
    hypotheses = state.get("hypotheses", [])

    decision = safety_check(
        trade=trade,
        verify_pass=verify_pass,
        description=description,
        hypotheses=hypotheses,
    )

    return {
        "escalated": decision.escalate,
        "escalation_reason": decision.reason,
    }
