"""CLARIFY node — HITL follow-up question, loop back to RETRIEVE.

Graph pauses here via interrupt(); human answer resumes at RETRIEVE.
clarify_rounds >= 3 → route to human dispatcher, not another loop.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt


def clarify(state: dict[str, Any]) -> dict[str, Any]:
    """Interrupt the graph to ask the tenant a clarifying question."""
    pending_question = state.get("pending_question")
    clarify_rounds = state.get("clarify_rounds", 0)

    if pending_question and clarify_rounds < 3:
        # Pause execution — the API will surface pending_question
        answer = interrupt({"question": pending_question})

        return {
            "pending_question": None,
            "clarify_rounds": clarify_rounds + 1,
            # The answer will be used by RETRIEVE on re-entry
            "description": state.get("description", "") + f"\n[Clarification: {answer}]",
        }

    return {"pending_question": None}
