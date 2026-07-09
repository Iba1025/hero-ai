"""Typed query layer — nodes never write raw SQL."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hero.storage.models import (
    ContractorStatement,
    Diagnosis,
    DiagnosisClaim,
    Media,
    Ticket,
    WorkOrder,
)


async def create_ticket(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    building_id: uuid.UUID,
    description: str,
) -> Ticket:
    ticket = Ticket(org_id=org_id, building_id=building_id, description=description)
    session.add(ticket)
    await session.flush()
    return ticket


async def get_ticket(session: AsyncSession, ticket_id: uuid.UUID) -> Ticket | None:
    return await session.get(Ticket, ticket_id)


async def update_ticket_status(session: AsyncSession, ticket_id: uuid.UUID, status: str) -> None:
    ticket = await session.get(Ticket, ticket_id)
    if ticket is not None:
        ticket.status = status
        await session.flush()


async def create_media(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    object_key: str,
    media_type: str,
    sha256: str,
) -> Media:
    media = Media(ticket_id=ticket_id, object_key=object_key, media_type=media_type, sha256=sha256)
    session.add(media)
    await session.flush()
    return media


async def create_diagnosis(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    run_id: str,
    fault: str,
    calibrated_confidence: float | None,
    verify_pass: bool,
    escalated: bool,
    escalation_reason: str | None,
    claims: list[tuple[str, bool, dict[str, object]]],
) -> Diagnosis:
    diag = Diagnosis(
        ticket_id=ticket_id,
        run_id=run_id,
        fault=fault,
        calibrated_confidence=calibrated_confidence,
        verify_pass=verify_pass,
        escalated=escalated,
        escalation_reason=escalation_reason,
    )
    session.add(diag)
    await session.flush()
    for claim_text, grounded, evidence in claims:
        claim = DiagnosisClaim(
            diagnosis_id=diag.id,
            claim_text=claim_text,
            grounded=grounded,
            evidence=evidence,
        )
        session.add(claim)
    await session.flush()
    return diag


async def get_diagnosis_for_ticket(session: AsyncSession, ticket_id: uuid.UUID) -> Diagnosis | None:
    result = await session.execute(
        select(Diagnosis)
        .where(Diagnosis.ticket_id == ticket_id)
        .order_by(Diagnosis.created_at.desc())
    )
    return result.scalars().first()


async def create_work_order(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    diagnosis_id: uuid.UUID | None,
    sku: str | None,
    body: dict[str, object],
) -> WorkOrder:
    wo = WorkOrder(ticket_id=ticket_id, diagnosis_id=diagnosis_id, sku=sku, body=body)
    session.add(wo)
    await session.flush()
    return wo


async def create_contractor_statement(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    diagnosis_id: uuid.UUID,
    verdict: str | None,
    actual_fault: str | None = None,
    actual_part_sku: str | None = None,
    contractor_id: uuid.UUID | None = None,
    free_text: str | None = None,
    unlabeled_reason: str | None = None,
) -> ContractorStatement:
    stmt = ContractorStatement(
        ticket_id=ticket_id,
        diagnosis_id=diagnosis_id,
        verdict=verdict,
        actual_fault=actual_fault,
        actual_part_sku=actual_part_sku,
        contractor_id=contractor_id,
        free_text=free_text,
        unlabeled_reason=unlabeled_reason,
    )
    session.add(stmt)
    await session.flush()
    return stmt


async def has_contractor_statement(session: AsyncSession, ticket_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(ContractorStatement.id).where(ContractorStatement.ticket_id == ticket_id).limit(1)
    )
    return result.scalar() is not None
