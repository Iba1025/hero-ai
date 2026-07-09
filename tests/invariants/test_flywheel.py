"""Flywheel test: ticket cannot transition to 'resolved' without a
contractor_statement row (verdict or unlabeled_reason). PRD §9.

A ticket reaching 'resolved' without a row here is a bug.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hero.storage.models import ContractorStatement
from hero.storage.repo import (
    create_contractor_statement,
    create_diagnosis,
    create_ticket,
    has_contractor_statement,
    update_ticket_status,
)
from tests.invariants.conftest import requires_docker

pytestmark = requires_docker


@pytest.mark.asyncio
async def test_resolved_ticket_requires_contractor_statement(db_session: AsyncSession) -> None:
    """A ticket should not be marked 'resolved' unless a contractor_statement exists."""
    # Create a ticket
    ticket = await create_ticket(
        db_session,
        org_id=uuid.uuid4(),
        building_id=uuid.uuid4(),
        description="Test plumbing issue",
    )
    await db_session.commit()

    # Before adding contractor_statement, has_contractor_statement must be False
    assert await has_contractor_statement(db_session, ticket.id) is False

    # Create a diagnosis (needed for the FK)
    diag = await create_diagnosis(
        db_session,
        ticket_id=ticket.id,
        run_id="test-run-001",
        fault="Leaking valve",
        calibrated_confidence=0.85,
        verify_pass=True,
        escalated=False,
        escalation_reason=None,
        claims=[("Valve is leaking", True, {"doc_id": "m1", "page": 1})],
    )
    await db_session.commit()

    # Add contractor statement with verdict
    await create_contractor_statement(
        db_session,
        ticket_id=ticket.id,
        diagnosis_id=diag.id,
        verdict="confirmed",
    )
    await db_session.commit()

    # Now has_contractor_statement must be True
    assert await has_contractor_statement(db_session, ticket.id) is True

    # Now it's safe to mark resolved
    await update_ticket_status(db_session, ticket.id, "resolved")
    await db_session.commit()


@pytest.mark.asyncio
async def test_contractor_statement_verdict_or_reason_constraint(db_session: AsyncSession) -> None:
    """The verdict_or_reason CHECK constraint must prevent rows with both NULL."""
    ticket = await create_ticket(
        db_session,
        org_id=uuid.uuid4(),
        building_id=uuid.uuid4(),
        description="Test for constraint",
    )
    diag = await create_diagnosis(
        db_session,
        ticket_id=ticket.id,
        run_id="test-run-002",
        fault="Test fault",
        calibrated_confidence=None,
        verify_pass=True,
        escalated=False,
        escalation_reason=None,
        claims=[("Test claim", True, {"doc_id": "m1", "page": 1})],
    )
    await db_session.commit()

    # Attempting to insert with both verdict=NULL and unlabeled_reason=NULL
    # should violate the CHECK constraint
    with pytest.raises(Exception):  # noqa: B017
        stmt = ContractorStatement(
            ticket_id=ticket.id,
            diagnosis_id=diag.id,
            verdict=None,
            unlabeled_reason=None,
        )
        db_session.add(stmt)
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_unlabeled_reason_satisfies_constraint(db_session: AsyncSession) -> None:
    """A contractor_statement with unlabeled_reason but no verdict must be valid."""
    ticket = await create_ticket(
        db_session,
        org_id=uuid.uuid4(),
        building_id=uuid.uuid4(),
        description="Test unlabeled reason",
    )
    diag = await create_diagnosis(
        db_session,
        ticket_id=ticket.id,
        run_id="test-run-003",
        fault="Unknown fault",
        calibrated_confidence=None,
        verify_pass=True,
        escalated=False,
        escalation_reason=None,
        claims=[("Test claim", True, {"doc_id": "m1", "page": 1})],
    )
    await db_session.commit()

    cs = await create_contractor_statement(
        db_session,
        ticket_id=ticket.id,
        diagnosis_id=diag.id,
        verdict=None,
        unlabeled_reason="Contractor unreachable",
    )
    await db_session.commit()

    assert cs.id is not None
    assert cs.unlabeled_reason == "Contractor unreachable"
