"""DIAGNOSE node — VLM forms fault hypotheses.

Uses VLM Protocol only — no SDK imports (DEC-1).
"""

from __future__ import annotations

from typing import Any

from hero.graph.state import TicketState
from hero.interfaces.vlm import VLM, DiagnosisParseError


def make_diagnose(vlm: VLM) -> Any:
    """Factory that returns a diagnose node with VLM injected."""

    async def diagnose(state: dict[str, Any]) -> dict[str, Any]:
        ticket_state = TicketState(**state)
        try:
            hypotheses = await vlm.diagnose(ticket_state)
        except DiagnosisParseError:
            # Never emit a placeholder fault — escalate to a human (P3-1.5).
            # SAFETY_GATE preserves this reason; VERIFY still runs (INV-8)
            # but has no hypotheses to gate.
            return {
                "hypotheses": [],
                "escalated": True,
                "escalation_reason": "diagnosis_unparseable",
            }
        return {"hypotheses": [h.model_dump() for h in hypotheses]}

    return diagnose
