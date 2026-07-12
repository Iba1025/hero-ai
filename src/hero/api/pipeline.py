"""Shared ticket-creation pipeline (P4-4).

Both creation paths — operator POST /tickets and public tenant intake —
route through `run_and_persist`, so the persistence contract (diagnosis +
per-claim rows, ledger events, triage stamp, status) cannot diverge between
them. Same spirit as the single resume path rule (hero.api.resume).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from hero.storage.ledger import events_from_state
from hero.storage.models import Ticket
from hero.storage.repo import (
    append_ticket_events,
    persist_diagnosis_from_state,
    stamp_ticket_triage,
    update_ticket_status,
)


async def run_and_persist(
    graph: Any,
    session: AsyncSession,
    ticket: Ticket,
    *,
    media: list[dict[str, str]],
    sensor_readings: list[dict[str, object]],
) -> str:
    """Run the graph for a freshly created ticket and persist everything.

    Returns the resulting ticket status. Commits the session.
    """
    ticket_id = str(ticket.id)
    thread_id = f"ticket-{ticket_id}"
    config = {"configurable": {"thread_id": thread_id}}

    input_state: dict[str, Any] = {
        "ticket_id": ticket_id,
        "description": ticket.description,
        "media": media,
        "sensor_readings": sensor_readings,
    }
    result = await graph.ainvoke(input_state, config=config)

    status = "diagnosed"
    if result.get("escalated"):
        status = "escalated"
    elif result.get("pending_question"):
        status = "clarifying"

    # Per-claim results → diagnosis_claim (BL-6). No-op while CLARIFY-interrupted.
    await persist_diagnosis_from_state(session, ticket_id=ticket.id, run_id=thread_id, state=result)
    # Ledger journal (P4-3): one row per pipeline state that actually ran.
    await append_ticket_events(
        session, ticket_id=ticket.id, run_id=thread_id, events=events_from_state(result)
    )
    # Triage runs before any CLARIFY interrupt, so trade/urgency are final here (P4-2).
    await stamp_ticket_triage(
        session,
        ticket.id,
        trade=result.get("trade"),
        urgency=result.get("urgency"),
        complexity=result.get("complexity"),
    )
    await update_ticket_status(session, ticket.id, status)
    await session.commit()
    return status
