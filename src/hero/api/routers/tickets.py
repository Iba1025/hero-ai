"""Ticket endpoints — POST /tickets, GET /tickets/{id}, POST /tickets/{id}/clarify-answer."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hero.api.deps import get_db_session, get_graph
from hero.storage.repo import (
    create_ticket as repo_create_ticket,
)
from hero.storage.repo import (
    persist_diagnosis_from_state,
    update_ticket_status,
)

router = APIRouter()


class CreateTicketRequest(BaseModel):
    org_id: str
    building_id: str
    description: str
    media: list[dict[str, str]] = Field(default_factory=list)
    sensor_readings: list[dict[str, object]] = Field(default_factory=list)


class CreateTicketResponse(BaseModel):
    ticket_id: str
    thread_id: str
    status: str


class ClarifyAnswerRequest(BaseModel):
    answer: str


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
) -> CreateTicketResponse:
    """Create a ticket row, run the graph, persist diagnosis + claims (DEC-6)."""
    graph = await get_graph()

    ticket = await repo_create_ticket(
        session,
        org_id=uuid.UUID(request.org_id),
        building_id=uuid.UUID(request.building_id),
        description=request.description,
    )
    ticket_id = str(ticket.id)
    thread_id = f"ticket-{ticket_id}"

    config = {"configurable": {"thread_id": thread_id}}

    input_state: dict[str, Any] = {
        "ticket_id": ticket_id,
        "description": request.description,
        "media": request.media,
        "sensor_readings": request.sensor_readings,
    }

    result = await graph.ainvoke(input_state, config=config)

    status = "diagnosed"
    if result.get("escalated"):
        status = "escalated"
    elif result.get("pending_question"):
        status = "clarifying"

    # Per-claim results → diagnosis_claim (BL-6). No-op while CLARIFY-interrupted.
    await persist_diagnosis_from_state(session, ticket_id=ticket.id, run_id=thread_id, state=result)
    await update_ticket_status(session, ticket.id, status)
    await session.commit()

    return CreateTicketResponse(
        ticket_id=ticket_id,
        thread_id=thread_id,
        status=status,
    )


@router.get("/{ticket_id}", response_model=TicketStatusResponse)
async def get_ticket(ticket_id: str) -> TicketStatusResponse:
    """Get ticket status, diagnosis, and claims."""
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
        status = "resolved"

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


@router.post("/{ticket_id}/clarify-answer")
async def clarify_answer(
    ticket_id: str,
    request: ClarifyAnswerRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> dict[str, str]:
    """Resume an interrupted run with a clarification answer."""
    graph = await get_graph()
    thread_id = f"ticket-{ticket_id}"
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if state is None or not state.values:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if not state.values.get("pending_question"):
        raise HTTPException(status_code=400, detail="Ticket is not awaiting clarification")

    # Resume the graph with the answer via Command
    from langgraph.types import Command

    result = await graph.ainvoke(Command(resume=request.answer), config=config)

    # Run may now be complete — persist diagnosis + per-claim results (BL-6).
    if not result.get("pending_question"):
        await persist_diagnosis_from_state(
            session, ticket_id=uuid.UUID(ticket_id), run_id=thread_id, state=result
        )
        status = "escalated" if result.get("escalated") else "diagnosed"
        await update_ticket_status(session, uuid.UUID(ticket_id), status)
        await session.commit()

    return {"status": "resumed", "ticket_id": ticket_id}
