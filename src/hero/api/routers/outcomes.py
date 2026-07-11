"""Outcomes endpoint — POST /outcomes (writes contractor_statement — BL-0).

A ticket cannot reach 'resolved' without a contractor_statement row (PRD §9).
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hero.api.deps import get_db_session
from hero.storage.repo import (
    create_contractor_statement,
    get_diagnosis_for_ticket,
    get_ticket,
    label_velocity,
    update_ticket_status,
)

router = APIRouter()


class OutcomeRequest(BaseModel):
    ticket_id: str
    # Closed vocabulary (P3-2) — mirrors the verdict_allowed DB CHECK.
    verdict: Literal["confirmed", "partially_correct", "wrong"] | None = None
    actual_fault: str | None = None
    actual_part_sku: str | None = None
    contractor_id: str | None = None
    free_text: str | None = None
    unlabeled_reason: str | None = None


class OutcomeResponse(BaseModel):
    id: str
    ticket_id: str
    status: str


class LabelVelocityResponse(BaseModel):
    days: int
    total: int
    labeled: int
    unlabeled: int
    per_day: float


@router.post("", response_model=OutcomeResponse)
async def create_outcome(
    request: OutcomeRequest,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> OutcomeResponse:
    """Write a contractor statement — the flywheel table (BL-0).

    Either verdict or unlabeled_reason must be provided (enforced by DB constraint).
    """
    if request.verdict is None and request.unlabeled_reason is None:
        raise HTTPException(
            status_code=422,
            detail="Either verdict or unlabeled_reason must be provided",
        )
    # P3-2: a correction without the actual fault is not a training signal.
    if request.verdict in ("partially_correct", "wrong") and request.actual_fault is None:
        raise HTTPException(
            status_code=422,
            detail=f"actual_fault is required when verdict is '{request.verdict}'",
        )

    ticket_uuid = uuid.UUID(request.ticket_id)
    ticket = await get_ticket(session, ticket_uuid)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    diag = await get_diagnosis_for_ticket(session, ticket_uuid)
    if diag is None:
        raise HTTPException(status_code=400, detail="No diagnosis exists for this ticket")

    cs = await create_contractor_statement(
        session,
        ticket_id=ticket_uuid,
        diagnosis_id=diag.id,
        verdict=request.verdict,
        actual_fault=request.actual_fault,
        actual_part_sku=request.actual_part_sku,
        contractor_id=uuid.UUID(request.contractor_id) if request.contractor_id else None,
        free_text=request.free_text,
        unlabeled_reason=request.unlabeled_reason,
    )

    # Mark ticket as resolved now that contractor_statement exists
    await update_ticket_status(session, ticket_uuid, "resolved")
    await session.commit()

    return OutcomeResponse(
        id=str(cs.id),
        ticket_id=request.ticket_id,
        status="resolved",
    )


@router.get("/metrics/label-velocity", response_model=LabelVelocityResponse)
async def get_label_velocity(
    days: int = 7,
    session: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> LabelVelocityResponse:
    """Label velocity over a trailing window (BL-0 DoD tracked metric)."""
    if days < 1:
        raise HTTPException(status_code=422, detail="days must be >= 1")
    metrics = await label_velocity(session, days=days)
    return LabelVelocityResponse(
        days=days,
        total=int(metrics["total"]),
        labeled=int(metrics["labeled"]),
        unlabeled=int(metrics["unlabeled"]),
        per_day=float(metrics["per_day"]),
    )
