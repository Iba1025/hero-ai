"""TRIAGE node — urgency + trade + complexity classification.

Stub: assigns defaults. Real impl uses VLM (BL-4 adds complexity routing).
"""

from __future__ import annotations

from typing import Any

from hero.interfaces.vlm import VLM


def make_triage(vlm: VLM) -> Any:
    """Factory that returns a triage node function with VLM injected."""

    async def triage(state: dict[str, Any]) -> dict[str, Any]:
        # Stub: simple keyword-based classification
        description = state.get("description", "").lower()

        # Respect pre-set trade (e.g., from intake or API)
        trade = state.get("trade") or "other"
        if trade == "other":
            for keyword, t in [
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
            ]:
                if keyword in description:
                    trade = t
                    break

        urgency = "routine"
        if any(w in description for w in ["gas", "flood", "fire", "emergency", "sparking"]):
            urgency = "emergency"
        elif any(w in description for w in ["leak", "no heat", "no hot water"]):
            urgency = "urgent"

        complexity = "standard"

        return {
            "trade": trade,
            "urgency": urgency,
            "complexity": complexity,
        }

    return triage
