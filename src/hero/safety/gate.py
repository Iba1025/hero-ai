"""Safety gate — pure deterministic functions (spec §9).

NO LLM calls in this module. Confidence is NOT an input (INV-1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hero.safety.hazards import HARD_ESCALATE_TRADES, HAZARD_KEYWORDS


@dataclass(frozen=True)
class SafetyDecision:
    escalate: bool
    reason: str | None


def safety_check(
    *,
    trade: str | None,
    verify_pass: bool,
    description: str,
    hypotheses: list[dict[str, Any]],
) -> SafetyDecision:
    """Deterministic safety gate per spec §9.

    Confidence is deliberately NOT a parameter (INV-1).
    """
    # 1. Hard category escalation (INV-1)
    if trade in HARD_ESCALATE_TRADES:
        return SafetyDecision(escalate=True, reason="hard_category")

    # 2. Verification failure
    if not verify_pass:
        return SafetyDecision(escalate=True, reason="verification_failed")

    # 3. Hazard keyword scan
    if _any_hazard_keywords(description, hypotheses):
        return SafetyDecision(escalate=True, reason="hazard_signal")

    return SafetyDecision(escalate=False, reason=None)


def _any_hazard_keywords(description: str, hypotheses: list[dict[str, Any]]) -> bool:
    """Scan description and hypothesis faults for hazard keywords."""
    text = description.lower()
    for hyp in hypotheses:
        fault = hyp.get("fault", "")
        text += " " + fault.lower()

    return any(kw in text for kw in HAZARD_KEYWORDS)
