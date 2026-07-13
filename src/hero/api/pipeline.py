"""Shared ticket-creation pipeline (P4-4) + background execution (BL-17/H1).

Both creation paths — operator POST /tickets and public tenant intake —
route through `run_and_persist`, so the persistence contract (diagnosis +
per-claim rows, work order, ledger events, triage stamp, status) cannot
diverge between them. Same spirit as the single resume path rule
(hero.api.resume).

Since BL-17 (H1) the graph runs in a background task: handlers call
`hero.api.background.spawn(run_ticket_pipeline(...))` and return immediately;
`ticket.pipeline_status` tracks the run (queued → running → awaiting_tenant |
complete | failed). A process death mid-run is picked up on next startup by
`recover_orphaned_runs` — the Postgres checkpointer (INV-6) makes the run
resumable from its last completed node.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hero.nova.bridge import post_run_update
from hero.storage.ledger import events_from_state
from hero.storage.models import Ticket
from hero.storage.repo import (
    append_ticket_events,
    create_work_order,
    get_ticket,
    persist_diagnosis_from_state,
    stamp_ticket_triage,
    update_pipeline_status,
    update_ticket_status,
)

logger = logging.getLogger(__name__)


def pipeline_status_from_result(result: dict[str, Any]) -> str:
    """awaiting_tenant while CLARIFY-interrupted, complete otherwise."""
    return "awaiting_tenant" if result.get("pending_question") else "complete"


async def persist_completion(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    run_id: str,
    result: dict[str, Any],
) -> str:
    """Persist everything a finished (or CLARIFY-parked) run produced.

    Diagnosis + per-claim rows (BL-6), the work order (BL-18/H2 — pinned to the
    id RESOLVE minted, so the ledger `procure` event references the row),
    ticket status, and pipeline_status. Does NOT commit and does NOT write
    ledger events — create and resume paths record those differently.
    Returns the resulting ticket status.
    """
    status = "diagnosed"
    if result.get("escalated"):
        status = "escalated"
    elif result.get("pending_question"):
        status = "clarifying"

    # Escalation is sticky (INV-1 spirit): a Nova guardrail may have escalated
    # this ticket mid-run (hazard in chat, Phase 5 STEP 3) — a completing run
    # never downgrades it back to diagnosed/clarifying. A human owns it now.
    current = await get_ticket(session, ticket_id)
    if current is not None and current.status == "escalated":
        status = "escalated"

    diag = await persist_diagnosis_from_state(
        session, ticket_id=ticket_id, run_id=run_id, state=result
    )

    wo_id = result.get("work_order_id")
    if not result.get("escalated") and wo_id:
        await create_work_order(
            session,
            ticket_id=ticket_id,
            diagnosis_id=diag.id if diag is not None else None,
            sku=result.get("sku"),
            body={"fault": diag.fault if diag is not None else None},
            work_order_id=uuid.UUID(str(wo_id)),
        )

    await update_ticket_status(session, ticket_id, status)
    await update_pipeline_status(session, ticket_id, pipeline_status_from_result(result))

    # Nova (Phase 5 STEP 3): chat-originated tickets hear back in the chat —
    # the CLARIFY question, the completion notice, or the escalation banner
    # (fixed copy; no-op for form/operator tickets).
    await post_run_update(
        session,
        ticket_id=ticket_id,
        status=status,
        pending_question=result.get("pending_question"),
    )
    return status


async def run_and_persist(
    graph: Any,
    session: AsyncSession,
    ticket: Ticket,
    *,
    media: list[dict[str, str | None]],  # sha256 is best-effort → None allowed
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
    status = await persist_completion(session, ticket_id=ticket.id, run_id=thread_id, result=result)
    await session.commit()
    return status


async def _mark_failed(
    session_factory: async_sessionmaker[AsyncSession], ticket_id: uuid.UUID
) -> None:
    """Best-effort failure stamp on a fresh session (the run's session may be dead)."""
    try:
        async with session_factory() as session:
            await update_pipeline_status(session, ticket_id, "failed")
            await session.commit()
    except Exception:  # never let the failure path raise
        logger.exception("Could not mark ticket %s pipeline_status=failed", ticket_id)


async def run_ticket_pipeline(
    graph: Any,
    ticket_id: uuid.UUID,
    *,
    media: list[dict[str, str | None]],
    sensor_readings: list[dict[str, object]],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Background entrypoint for a freshly created ticket (BL-17/H1)."""
    try:
        async with session_factory() as session:
            await update_pipeline_status(session, ticket_id, "running")
            await session.commit()
            ticket = await get_ticket(session, ticket_id)
            if ticket is None:  # deleted between commit and spawn — nothing to run
                return
            await run_and_persist(
                graph, session, ticket, media=media, sensor_readings=sensor_readings
            )
    except Exception:
        logger.exception("Pipeline run failed for ticket %s", ticket_id)
        await _mark_failed(session_factory, ticket_id)


async def resume_ticket_pipeline(
    graph: Any,
    ticket_id: uuid.UUID,
    *,
    answer: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Background entrypoint for a clarify answer — through the single resume
    path (hero.api.resume), same rule as the synchronous era."""
    from hero.api.resume import NotAwaitingClarificationError, resume_with_answer

    try:
        async with session_factory() as session:
            try:
                await resume_with_answer(graph, session, ticket_id=ticket_id, answer=answer)
            except NotAwaitingClarificationError:
                # Pre-checked by the handler; a race lost here is not a failure —
                # restore awaiting/complete truthfully from the ticket status.
                ticket = await get_ticket(session, ticket_id)
                clarifying = ticket is not None and ticket.status == "clarifying"
                restored = "awaiting_tenant" if clarifying else "complete"
                await update_pipeline_status(session, ticket_id, restored)
                await session.commit()
    except Exception:
        logger.exception("Pipeline resume failed for ticket %s", ticket_id)
        await _mark_failed(session_factory, ticket_id)


async def recover_orphaned_runs(
    graph: Any, session_factory: async_sessionmaker[AsyncSession]
) -> int:
    """Startup recovery (BL-17/H1): re-drive runs a dead process left behind.

    queued/running tickets are resumed from the Postgres checkpointer (INV-6):
    `ainvoke(None)` continues from the last completed node. Tickets whose
    lifecycle status already shows a finished run just get pipeline_status
    repaired. Returns the number of runs re-driven.
    """
    from sqlalchemy import select

    async with session_factory() as session:
        rows = await session.execute(
            select(Ticket.id, Ticket.status).where(
                Ticket.pipeline_status.in_(["queued", "running"])
            )
        )
        orphans = [(row[0], row[1]) for row in rows]

    recovered = 0
    for ticket_id, status in orphans:
        if status in ("diagnosed", "escalated", "resolved"):
            # Run finished; only the stamp was lost (crash inside the final commit window).
            async with session_factory() as session:
                await update_pipeline_status(session, ticket_id, "complete")
                await session.commit()
            continue
        if status == "clarifying":
            async with session_factory() as session:
                await update_pipeline_status(session, ticket_id, "awaiting_tenant")
                await session.commit()
            continue
        await _recover_one(graph, ticket_id, session_factory)
        recovered += 1
    return recovered


async def _recover_one(
    graph: Any, ticket_id: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Resume one interrupted run from its checkpoint (or from scratch if the
    crash happened before the first checkpoint was written)."""
    thread_id = f"ticket-{ticket_id}"
    config = {"configurable": {"thread_id": thread_id}}
    try:
        async with session_factory() as session:
            await update_pipeline_status(session, ticket_id, "running")
            await session.commit()
            ticket = await get_ticket(session, ticket_id)
            if ticket is None:
                return

            state = await graph.aget_state(config)
            if state is not None and state.values:
                # Checkpoint exists — continue from the last completed node.
                result = await graph.ainvoke(None, config=config)
                await append_ticket_events(
                    session,
                    ticket_id=ticket_id,
                    run_id=thread_id,
                    events=events_from_state(result),
                )
                await stamp_ticket_triage(
                    session,
                    ticket_id,
                    trade=result.get("trade"),
                    urgency=result.get("urgency"),
                    complexity=result.get("complexity"),
                )
                await persist_completion(
                    session, ticket_id=ticket_id, run_id=thread_id, result=result
                )
                await session.commit()
                logger.warning("Recovered orphaned run for ticket %s (from checkpoint)", ticket_id)
            else:
                # Died before the first checkpoint — rebuild INTAKE input from rows.
                from sqlalchemy import select

                from hero.storage.models import Media

                media_rows = await session.execute(
                    select(Media).where(Media.ticket_id == ticket_id)
                )
                media: list[dict[str, str | None]] = [
                    {
                        "object_key": m.object_key,
                        # media rows store the MIME type; MediaRef wants the coarse kind
                        "media_type": m.media_type.split("/")[0],
                        "sha256": m.sha256,
                    }
                    for m in media_rows.scalars()
                ]
                await run_and_persist(graph, session, ticket, media=media, sensor_readings=[])
                logger.warning("Recovered orphaned run for ticket %s (from scratch)", ticket_id)
    except Exception:
        logger.exception("Recovery failed for ticket %s", ticket_id)
        await _mark_failed(session_factory, ticket_id)
