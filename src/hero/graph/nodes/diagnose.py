"""DIAGNOSE node — VLM forms fault hypotheses.

Uses VLM Protocol only — no SDK imports (DEC-1).
"""

from __future__ import annotations

from typing import Any

from hero.graph.state import TicketState
from hero.interfaces.vlm import VLM


def make_diagnose(vlm: VLM) -> Any:
    """Factory that returns a diagnose node with VLM injected."""

    async def diagnose(state: dict[str, Any]) -> dict[str, Any]:
        ticket_state = TicketState(**state)
        hypotheses = await vlm.diagnose(ticket_state)
        return {"hypotheses": [h.model_dump() for h in hypotheses]}

    return diagnose
