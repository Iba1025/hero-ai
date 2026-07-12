"""Single resume path rule (P4-4 hardening) — the ONLY way to resume a run.

A CLARIFY-interrupted run may only be resumed via `resume_with_answer`: it
snapshots the pending question BEFORE resuming (the question is not
recoverable from state history afterwards) and appends the `clarify_answered`
+ resumed-run events to the ledger, then persists diagnosis/status when the
run completes. Any other `Command(resume=...)` through the API graph
(`deps.get_graph` wraps the compiled graph in `_ResumeGuardedGraph`) raises
`ResumeNotAllowedError` — a resume that bypassed this path would leave the
ledger missing the question. Spec §4 "Single resume path rule".
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from hero.storage.ledger import events_from_state
from hero.storage.repo import (
    append_ticket_events,
    persist_diagnosis_from_state,
    update_ticket_status,
)

_SANCTIONED: ContextVar[bool] = ContextVar("hero_resume_sanctioned", default=False)


class ResumeNotAllowedError(RuntimeError):
    """A Command(resume=...) bypassed resume_with_answer (single resume path rule)."""


class NotAwaitingClarificationError(RuntimeError):
    """The run has no pending question — or no checkpointed state at all."""

    def __init__(self, *, state_missing: bool = False) -> None:
        super().__init__("Ticket is not awaiting clarification")
        self.state_missing = state_missing


def resume_sanctioned() -> bool:
    """True only inside resume_with_answer's graph invocation (contextvar token)."""
    return _SANCTIONED.get()


async def resume_with_answer(
    graph: Any,
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    answer: str,
) -> dict[str, Any]:
    """Resume the interrupted run and record the full CLARIFY round in the ledger.

    Commits the session. Raises NotAwaitingClarificationError if there is no
    pending question (state_missing=True when there is no run state at all).
    """
    from langgraph.types import Command

    thread_id = f"ticket-{ticket_id}"
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if state is None or not state.values:
        raise NotAwaitingClarificationError(state_missing=True)
    question = state.values.get("pending_question")
    if not question:
        raise NotAwaitingClarificationError()

    token = _SANCTIONED.set(True)
    try:
        result: dict[str, Any] = await graph.ainvoke(Command(resume=answer), config=config)
    finally:
        _SANCTIONED.reset(token)

    # Ledger (P4-3): record the answered round, then whatever the resume ran.
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "clarify_answered",
            {
                "question": question,
                "answer": answer,
                "round": int(result.get("clarify_rounds") or 0),
            },
        )
    ]
    events += events_from_state(result, resumed=True)
    await append_ticket_events(session, ticket_id=ticket_id, run_id=thread_id, events=events)

    # Run may now be complete — persist diagnosis + per-claim results (BL-6).
    if not result.get("pending_question"):
        await persist_diagnosis_from_state(
            session, ticket_id=ticket_id, run_id=thread_id, state=result
        )
        status = "escalated" if result.get("escalated") else "diagnosed"
        await update_ticket_status(session, ticket_id, status)
    await session.commit()
    return result
