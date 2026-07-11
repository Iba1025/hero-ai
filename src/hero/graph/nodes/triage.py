"""TRIAGE node — urgency + trade + complexity classification (BL-4).

VLM-backed (verify tier, DEC-18 as amended) with deterministic fail-safes:

1. Keyword hazard override (INV-1): if the keyword scan detects a
   hard-escalate trade (gas/electrical/structural/water_intrusion) the
   VLM cannot classify it away. Urgency is likewise never downgraded
   below the keyword heuristic's verdict.
2. Any VLM failure (call error or unparseable output) falls back to the
   keyword classifier with complexity="standard" — a triage failure must
   never block a ticket or route it to the reduced fast path.
"""

from __future__ import annotations

import logging
from typing import Any

from hero.graph.state import Complexity, TradeCategory, Urgency
from hero.interfaces.vlm import VLM
from hero.safety.hazards import HARD_ESCALATE_TRADES

logger = logging.getLogger(__name__)

_TRADE_KEYWORDS: list[tuple[str, TradeCategory]] = [
    ("gas", "gas"),
    ("furnace", "hvac"),
    ("hvac", "hvac"),
    ("heat", "hvac"),
    ("air condition", "hvac"),
    ("ac ", "hvac"),
    ("pipe", "plumbing"),
    ("leak", "plumbing"),
    ("plumb", "plumbing"),
    ("drain", "plumbing"),
    ("toilet", "plumbing"),
    ("faucet", "plumbing"),
    ("water", "water_intrusion"),
    ("flood", "water_intrusion"),
    ("electric", "electrical"),
    ("wiring", "electrical"),
    ("outlet", "electrical"),
    ("circuit", "electrical"),
    ("structur", "structural"),
    ("crack", "structural"),
    ("foundation", "structural"),
    ("appliance", "appliance"),
    ("dishwasher", "appliance"),
    ("fridge", "appliance"),
    ("washer", "appliance"),
]

_EMERGENCY_KEYWORDS = ("gas", "flood", "fire", "emergency", "sparking")
_URGENT_KEYWORDS = ("leak", "no heat", "no hot water")

# Conservative fast-path cues for the fallback classifier: single-fixture,
# routine symptoms only. The VLM does the real 3-way call; this fallback
# never returns "complex".
_SIMPLE_HINTS = ("drip", "faucet", "tap", "flapper", "running toilet", "showerhead", "filter")

_URGENCY_RANK: dict[str, int] = {"routine": 0, "urgent": 1, "emergency": 2}


def keyword_triage(description: str) -> tuple[TradeCategory, Urgency, Complexity]:
    """Deterministic keyword classifier — fallback + INV-1 floor for VLM triage."""
    text = description.lower()

    trade: TradeCategory = "other"
    for keyword, t in _TRADE_KEYWORDS:
        if keyword in text:
            trade = t
            break

    urgency: Urgency = "routine"
    if any(w in text for w in _EMERGENCY_KEYWORDS):
        urgency = "emergency"
    elif any(w in text for w in _URGENT_KEYWORDS):
        urgency = "urgent"

    complexity: Complexity = "standard"
    if urgency == "routine" and len(text.split()) <= 25 and any(h in text for h in _SIMPLE_HINTS):
        complexity = "simple"

    return trade, urgency, complexity


def make_triage(vlm: VLM) -> Any:
    """Factory that returns a triage node function with VLM injected."""

    async def triage(state: dict[str, Any]) -> dict[str, Any]:
        description = state.get("description", "")
        kw_trade, kw_urgency, kw_complexity = keyword_triage(description)

        try:
            result = await vlm.triage(description)
            trade: str = result.trade
            urgency: str = result.urgency
            complexity: str = result.complexity
        except Exception:
            logger.warning(
                "[TRIAGE] VLM triage failed — keyword fallback (full path)", exc_info=True
            )
            trade, urgency, complexity = kw_trade, kw_urgency, "standard"

        # INV-1 fail-safes: the VLM cannot classify away a keyword-detected
        # hazard trade, nor downgrade urgency below the keyword verdict.
        if kw_trade in HARD_ESCALATE_TRADES and trade != kw_trade:
            logger.warning(
                "[TRIAGE] hazard override: keyword trade=%s beats vlm trade=%s", kw_trade, trade
            )
            trade = kw_trade
        if _URGENCY_RANK[kw_urgency] > _URGENCY_RANK[urgency]:
            urgency = kw_urgency

        # Respect pre-set trade (e.g., from intake or API) — existing contract.
        preset = state.get("trade")
        if preset and preset != "other":
            trade = preset

        return {
            "trade": trade,
            "urgency": urgency,
            "complexity": complexity,
        }

    return triage
