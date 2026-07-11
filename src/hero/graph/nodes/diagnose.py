"""DIAGNOSE node — VLM forms fault hypotheses.

Uses VLM Protocol only — no SDK imports (DEC-1).
"""

from __future__ import annotations

import logging
from typing import Any

from hero.graph.state import TicketState
from hero.interfaces.vlm import VLM, DiagnosisParseError

logger = logging.getLogger(__name__)


def make_diagnose(vlm: VLM) -> Any:
    """Factory that returns a diagnose node with VLM injected."""

    async def diagnose(state: dict[str, Any]) -> dict[str, Any]:
        ticket_state = TicketState(**state)
        # One retry on parse failure (P3-4): primary-tier output is
        # non-deterministic (DEC-20), so a second sample often parses.
        # This is a parse-shape retry only — provider/network retries
        # stay at the adapter layer (spec §11).
        for attempt in (1, 2):
            try:
                hypotheses = await vlm.diagnose(ticket_state)
                break
            except DiagnosisParseError:
                if attempt == 1:
                    logger.warning("[DIAGNOSE] unparseable response — retrying once (DEC-20)")
                    continue
                # Never emit a placeholder fault — escalate to a human
                # (P3-1.5). SAFETY_GATE preserves this reason; VERIFY still
                # runs (INV-8) but has no hypotheses to gate.
                return {
                    "hypotheses": [],
                    "escalated": True,
                    "escalation_reason": "diagnosis_unparseable",
                }
        return {"hypotheses": [h.model_dump() for h in hypotheses]}

    return diagnose
