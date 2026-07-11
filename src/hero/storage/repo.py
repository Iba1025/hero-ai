"""Typed query layer — nodes never write raw SQL."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hero.storage.models import (
    ContractorStatement,
    Diagnosis,
    DiagnosisClaim,
    Media,
    Ticket,
    User,
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


async def get_ticket_for_org(
    session: AsyncSession, ticket_id: uuid.UUID, org_id: uuid.UUID
) -> Ticket | None:
    """Org-scoped ticket lookup (P4-1 invariant): the org filter lives in the
    query, not in caller-side checks — a cross-org id resolves to None."""
    result = await session.execute(
        select(Ticket).where(Ticket.id == ticket_id, Ticket.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def list_tickets_for_org(
    session: AsyncSession, org_id: uuid.UUID, *, limit: int = 100
) -> list[Ticket]:
    """Org-scoped ticket list (P4-2 cockpit), newest first. Same rule as
    get_ticket_for_org: the org filter lives in the query."""
    result = await session.execute(
        select(Ticket)
        .where(Ticket.org_id == org_id)
        .order_by(Ticket.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def stamp_ticket_triage(
    session: AsyncSession,
    ticket_id: uuid.UUID,
    *,
    trade: str | None,
    urgency: str | None,
    complexity: str | None,
) -> None:
    """Copy triage fields from final graph state onto the ticket row (P4-2)
    so list views don't need a checkpointer read per ticket."""
    ticket = await session.get(Ticket, ticket_id)
    if ticket is not None:
        ticket.trade = trade
        ticket.urgency = urgency
        ticket.complexity = complexity
        await session.flush()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    email: str,
    password_hash: str,
    role: str,
) -> User:
    user = User(org_id=org_id, email=email, password_hash=password_hash, role=role)
    session.add(user)
    await session.flush()
    return user


class FlywheelViolationError(Exception):
    """Raised when a ticket would reach 'resolved' without a contractor_statement (PRD §9).

    P3-2: previously this invariant held only because the /outcomes endpoint happened
    to write the statement before flipping the status — any other caller could bypass it.
    """


async def update_ticket_status(session: AsyncSession, ticket_id: uuid.UUID, status: str) -> None:
    if status == "resolved" and not await has_contractor_statement(session, ticket_id):
        raise FlywheelViolationError(
            f"Ticket {ticket_id} cannot reach 'resolved' without a contractor_statement (PRD §9)"
        )
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
    claims: list[tuple[str, str, bool, dict[str, object]]],
) -> Diagnosis:
    """Persist a diagnosis with its claim-level audit trail (DEC-6).

    claims: (claim_text, claim_type, grounded, evidence) per claim — claim_type
    records which grounding threshold applied (BL-6/DEC-19).
    """
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
    for claim_text, claim_type, grounded, evidence in claims:
        claim = DiagnosisClaim(
            diagnosis_id=diag.id,
            claim_text=claim_text,
            claim_type=claim_type,
            grounded=grounded,
            evidence=evidence,
        )
        session.add(claim)
    await session.flush()
    return diag


async def persist_diagnosis_from_state(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    run_id: str,
    state: dict[str, Any],
) -> Diagnosis | None:
    """Persist the primary hypothesis + per-claim results from final graph state (BL-6).

    Called by the API layer after a graph run completes — graph nodes never
    touch the DB. Picks the hypothesis with the highest calibrated_confidence
    (falls back to the first). Returns None when the run produced no hypotheses
    (e.g. interrupted at CLARIFY).
    """
    hypotheses: list[dict[str, Any]] = state.get("hypotheses") or []
    if not hypotheses:
        return None

    primary = max(
        hypotheses,
        key=lambda h: h.get("calibrated_confidence") or 0.0,
    )

    claims: list[tuple[str, str, bool, dict[str, object]]] = []
    for claim in primary.get("claims", []):
        claims.append(
            (
                claim.get("text", ""),
                claim.get("claim_type") or "descriptive",
                bool(claim.get("grounded")),
                {"chunks": claim.get("supporting_evidence", [])},
            )
        )

    return await create_diagnosis(
        session,
        ticket_id=ticket_id,
        run_id=run_id,
        fault=str(primary.get("fault", "")),
        calibrated_confidence=primary.get("calibrated_confidence"),
        verify_pass=bool(state.get("verify_pass")),
        escalated=bool(state.get("escalated")),
        escalation_reason=state.get("escalation_reason"),
        claims=claims,
    )


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


async def label_velocity(session: AsyncSession, *, days: int = 7) -> dict[str, float | int]:
    """Label-velocity metric (BL-0 DoD): statement counts over a trailing window.

    labeled = rows with a verdict (usable training signal);
    unlabeled = rows with only an unlabeled_reason (honest gap, not signal).
    Langfuse dashboard wiring lands with P3-4; this is the source metric.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    row = (
        await session.execute(
            select(
                func.count(ContractorStatement.id),
                func.count(ContractorStatement.verdict),
            ).where(ContractorStatement.created_at >= since)
        )
    ).one()
    total, labeled = int(row[0]), int(row[1])
    return {
        "days": days,
        "total": total,
        "labeled": labeled,
        "unlabeled": total - labeled,
        "per_day": total / days if days > 0 else 0.0,
    }
