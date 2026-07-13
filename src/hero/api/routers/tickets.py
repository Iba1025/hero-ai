"""Ticket endpoints — POST /tickets, GET /tickets/{id}, POST /tickets/{id}/clarify-answer."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hero.api.deps import AuthUser, get_current_user, get_db_session, get_graph, require_role
from hero.api.pipeline import run_and_persist
from hero.api.resume import NotAwaitingClarificationError, resume_with_answer
from hero.storage.ledger import assemble_ledger
from hero.storage.models import Ticket
from hero.storage.repo import (
    create_ticket as repo_create_ticket,
)
from hero.storage.repo import (
    get_diagnoses_with_claims,
    get_statements_for_ticket,
    get_ticket_for_org,
    list_ticket_events,
    list_tickets_for_org,
)

router = APIRouter()


class CreateTicketRequest(BaseModel):
    # org_id comes from the session token (P4-1) — never from the client.
    building_id: str
    description: str
    media: list[dict[str, str | None]] = Field(default_factory=list)  # sha256 may be null
    sensor_readings: list[dict[str, object]] = Field(default_factory=list)


class CreateTicketResponse(BaseModel):
    ticket_id: str
    thread_id: str
    status: str


class ClarifyAnswerRequest(BaseModel):
    answer: str


class TicketSummary(BaseModel):
    """List-view row (P4-2) — served from the ticket table, no checkpointer read."""

    ticket_id: str
    description: str
    status: str
    trade: str | None = None
    urgency: str | None = None
    complexity: str | None = None
    created_at: str


class TicketStatusResponse(BaseModel):
    ticket_id: str
    status: str
    trade: str | None = None
    urgency: str | None = None
    escalated: bool = False
    escalation_reason: str | None = None
    verify_pass: bool | None = None
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    work_order_id: str | None = None
    sku: str | None = None
    pending_question: str | None = None


@router.post("", response_model=CreateTicketResponse)
async def create_ticket(
    request: CreateTicketRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
    user: AuthUser = Depends(require_role("operator", "admin")),  # noqa: B008
) -> CreateTicketResponse:
    """Create a ticket row, run the graph, persist diagnosis + claims (DEC-6).

    Persistence goes through the shared pipeline (hero.api.pipeline) — the
    same one the public tenant intake uses (P4-4).
    """
    graph = await get_graph()

    ticket = await repo_create_ticket(
        session,
        org_id=user.org_id,
        building_id=uuid.UUID(request.building_id),
        description=request.description,
    )
    status = await run_and_persist(
        graph,
        session,
        ticket,
        media=request.media,
        sensor_readings=request.sensor_readings,
    )

    return CreateTicketResponse(
        ticket_id=str(ticket.id),
        thread_id=f"ticket-{ticket.id}",
        status=status,
    )


@router.get("", response_model=list[TicketSummary])
async def list_tickets(
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
    user: AuthUser = Depends(get_current_user),  # noqa: B008
) -> list[TicketSummary]:
    """Org-scoped ticket list (P4-2 cockpit). Any authenticated role."""
    tickets = await list_tickets_for_org(session, user.org_id)
    return [
        TicketSummary(
            ticket_id=str(t.id),
            description=t.description,
            status=t.status,
            trade=t.trade,
            urgency=t.urgency,
            complexity=t.complexity,
            created_at=t.created_at.isoformat(),
        )
        for t in tickets
    ]


@router.get("/{ticket_id}", response_model=TicketStatusResponse)
async def get_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
    user: AuthUser = Depends(get_current_user),  # noqa: B008
) -> TicketStatusResponse:
    """Get ticket status, diagnosis, and claims. Org-scoped (P4-1)."""
    await _require_ticket_in_org(session, ticket_id, user)

    graph = await get_graph()
    thread_id = f"ticket-{ticket_id}"
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if state is None or not state.values:
        raise HTTPException(status_code=404, detail="Ticket not found")

    values = state.values
    status = "open"
    if values.get("escalated"):
        status = "escalated"
    elif values.get("pending_question"):
        status = "clarifying"
    elif values.get("work_order_id"):
        # P3-2: never report 'resolved' from graph state alone — 'resolved' requires a
        # contractor_statement row and is only set by POST /outcomes (PRD §9).
        status = "diagnosed"

    return TicketStatusResponse(
        ticket_id=values.get("ticket_id", ticket_id),
        status=status,
        trade=values.get("trade"),
        urgency=values.get("urgency"),
        escalated=values.get("escalated", False),
        escalation_reason=values.get("escalation_reason"),
        verify_pass=values.get("verify_pass"),
        hypotheses=values.get("hypotheses", []),
        work_order_id=values.get("work_order_id"),
        sku=values.get("sku"),
        pending_question=values.get("pending_question"),
    )


async def _require_ticket_in_org(session: AsyncSession, ticket_id: str, user: AuthUser) -> Ticket:
    """Return the ticket, or 404 unless it exists in the caller's org (P4-1).

    404 (not 403) for cross-org ids — no cross-org existence leak. The org
    filter lives in the query (repo.get_ticket_for_org), not in caller code.
    """
    try:
        ticket_uuid = uuid.UUID(ticket_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Ticket not found") from exc
    ticket = await get_ticket_for_org(session, ticket_uuid, user.org_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


class LedgerEntry(BaseModel):
    state: str
    ts: str
    run_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class LedgerResponse(BaseModel):
    ticket_id: str
    building_id: str
    description: str
    status: str
    trade: str | None = None
    urgency: str | None = None
    complexity: str | None = None
    created_at: str
    entries: list[LedgerEntry]


@router.get("/{ticket_id}/ledger", response_model=LedgerResponse)
async def get_ticket_ledger(
    ticket_id: str,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
    user: AuthUser = Depends(require_role("operator", "admin")),  # noqa: B008
) -> LedgerResponse:
    """The full audit trail (P4-3) — every entry from persisted rows.

    Operator/admin only; contractors keep the narrower GET /tickets/{id} view.
    States that didn't run don't appear (honest gaps, P4-3c).
    """
    ticket = await _require_ticket_in_org(session, ticket_id, user)
    ticket_uuid = ticket.id
    entries = assemble_ledger(
        ticket,
        await list_ticket_events(session, ticket_uuid),
        await get_diagnoses_with_claims(session, ticket_uuid),
        await get_statements_for_ticket(session, ticket_uuid),
    )
    return LedgerResponse(
        ticket_id=str(ticket.id),
        building_id=str(ticket.building_id),
        description=ticket.description,
        status=ticket.status,
        trade=ticket.trade,
        urgency=ticket.urgency,
        complexity=ticket.complexity,
        created_at=ticket.created_at.isoformat(),
        entries=[LedgerEntry(**e) for e in entries],
    )


@router.post("/{ticket_id}/clarify-answer")
async def clarify_answer(
    ticket_id: str,
    request: ClarifyAnswerRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
    user: AuthUser = Depends(require_role("operator", "admin")),  # noqa: B008
) -> dict[str, str]:
    """Resume an interrupted run with a clarification answer. Org-scoped (P4-1).

    Delegates to the single resume path (hero.api.resume, spec §4) — the only
    place a resume may happen, so the ledger always records the round.
    """
    ticket = await _require_ticket_in_org(session, ticket_id, user)
    graph = await get_graph()
    try:
        await resume_with_answer(graph, session, ticket_id=ticket.id, answer=request.answer)
    except NotAwaitingClarificationError as exc:
        if exc.state_missing:
            raise HTTPException(status_code=404, detail="Ticket not found") from exc
        raise HTTPException(status_code=400, detail="Ticket is not awaiting clarification") from exc
    return {"status": "resumed", "ticket_id": ticket_id}
