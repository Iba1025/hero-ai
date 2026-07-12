"""Flywheel test: ticket cannot transition to 'resolved' without a
contractor_statement row (verdict or unlabeled_reason). PRD §9.

A ticket reaching 'resolved' without a row here is a bug.

Test strategies:
1. Structural: verify CHECK constraint exists in ORM model (no DB needed)
2. Graph-level: verify the pipeline produces diagnosable state (no DB needed)
3. DB-level: test CHECK enforcement + repo logic (Postgres via testcontainers, CI only)
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hero.storage.models import Base, ContractorStatement, DiagnosisClaim
from hero.storage.repo import (
    create_contractor_statement,
    create_diagnosis,
    create_ticket,
    has_contractor_statement,
    persist_diagnosis_from_state,
    update_ticket_status,
)
from tests.invariants.conftest import requires_docker

# ---------------------------------------------------------------------------
# Structural tests (no DB needed)
# ---------------------------------------------------------------------------


def test_contractor_statement_model_has_check_constraint() -> None:
    """The contractor_statement table must have verdict_or_reason CHECK."""
    table = Base.metadata.tables["contractor_statement"]
    check_names = [c.name for c in table.constraints if hasattr(c, "sqltext")]
    assert "verdict_or_reason" in check_names, (
        f"Missing verdict_or_reason CHECK constraint. Found: {check_names}"
    )


def test_contractor_statement_check_constraint_text() -> None:
    """The CHECK constraint must enforce: verdict IS NOT NULL OR unlabeled_reason IS NOT NULL."""
    table = Base.metadata.tables["contractor_statement"]
    checks = [c for c in table.constraints if hasattr(c, "sqltext")]
    verdict_check = next(c for c in checks if c.name == "verdict_or_reason")
    sql = str(verdict_check.sqltext)
    assert "verdict IS NOT NULL" in sql
    assert "unlabeled_reason IS NOT NULL" in sql


def test_verdict_vocabulary_constraint_exists() -> None:
    """P3-2: verdict is a closed vocabulary — free-text verdicts are unusable labels."""
    table = Base.metadata.tables["contractor_statement"]
    checks = {c.name: str(c.sqltext) for c in table.constraints if hasattr(c, "sqltext")}
    assert "verdict_allowed" in checks
    for verdict in ("confirmed", "partially_correct", "wrong"):
        assert verdict in checks["verdict_allowed"]


def test_correction_has_fault_constraint_exists() -> None:
    """P3-2: a correction (partially_correct|wrong) must carry actual_fault."""
    table = Base.metadata.tables["contractor_statement"]
    checks = {c.name: str(c.sqltext) for c in table.constraints if hasattr(c, "sqltext")}
    assert "correction_has_fault" in checks
    assert "actual_fault IS NOT NULL" in checks["correction_has_fault"]


def test_outcome_request_rejects_unknown_verdict() -> None:
    """P3-2: the API mirror of verdict_allowed — Pydantic Literal rejects free text."""
    from pydantic import ValidationError

    from hero.api.routers.outcomes import OutcomeRequest

    with pytest.raises(ValidationError):
        OutcomeRequest(ticket_id="t-1", verdict="probably right")  # type: ignore[arg-type]
    # The three allowed values construct fine.
    for verdict in ("confirmed", "partially_correct", "wrong"):
        OutcomeRequest(ticket_id="t-1", verdict=verdict)  # type: ignore[arg-type]


def test_contractor_statement_requires_diagnosis_fk() -> None:
    """contractor_statement.diagnosis_id must be a non-nullable FK."""
    table = Base.metadata.tables["contractor_statement"]
    diag_col = table.c.diagnosis_id
    assert diag_col.nullable is False
    fk_targets = [fk.target_fullname for fk in diag_col.foreign_keys]
    assert "diagnosis.id" in fk_targets


@pytest.mark.asyncio
async def test_pipeline_produces_diagnosable_state(stub_graph: Any) -> None:
    """A resolved ticket must pass through DIAGNOSE and VERIFY before RESOLVE,
    ensuring a diagnosis exists for the contractor_statement FK."""
    config = {"configurable": {"thread_id": "flywheel-diag-state"}}
    result = await stub_graph.ainvoke(
        {"ticket_id": "FW-001", "description": "Leaking faucet in bathroom"},
        config=config,
    )
    # Must have hypotheses (from DIAGNOSE) and verify_pass (from VERIFY)
    assert len(result.get("hypotheses", [])) >= 1
    assert result.get("verify_pass") is not None
    # Must have work_order_id (from RESOLVE, proving SAFETY_GATE passed)
    assert result.get("work_order_id") is not None


# ---------------------------------------------------------------------------
# DB-level tests (Postgres via testcontainers — CI only)
# ---------------------------------------------------------------------------


@requires_docker
@pytest.mark.asyncio
async def test_resolved_ticket_requires_contractor_statement(
    db_session: AsyncSession,
) -> None:
    """A ticket should not be marked 'resolved' unless a contractor_statement exists."""
    ticket = await create_ticket(
        db_session,
        org_id=uuid.uuid4(),
        building_id=uuid.uuid4(),
        description="Test plumbing issue",
    )
    await db_session.commit()

    assert await has_contractor_statement(db_session, ticket.id) is False

    diag = await create_diagnosis(
        db_session,
        ticket_id=ticket.id,
        run_id="test-run-001",
        fault="Leaking valve",
        calibrated_confidence=0.85,
        verify_pass=True,
        escalated=False,
        escalation_reason=None,
        claims=[("Valve is leaking", "descriptive", True, {"doc_id": "m1", "page": 1})],
    )
    await db_session.commit()

    await create_contractor_statement(
        db_session,
        ticket_id=ticket.id,
        diagnosis_id=diag.id,
        verdict="confirmed",
    )
    await db_session.commit()

    assert await has_contractor_statement(db_session, ticket.id) is True
    await update_ticket_status(db_session, ticket.id, "resolved")
    await db_session.commit()


@requires_docker
@pytest.mark.asyncio
async def test_unlabeled_reason_satisfies_flywheel(db_session: AsyncSession) -> None:
    """A contractor_statement with unlabeled_reason but no verdict is valid."""
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
        claims=[("Test claim", "descriptive", True, {"doc_id": "m1", "page": 1})],
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


@requires_docker
@pytest.mark.asyncio
async def test_persist_diagnosis_from_state_writes_claim_rows(db_session: AsyncSession) -> None:
    """BL-6/DEC-6: per-claim results (text, type, grounded, evidence) round-trip
    from final graph state into diagnosis_claim."""
    from sqlalchemy import select

    ticket = await create_ticket(
        db_session,
        org_id=uuid.uuid4(),
        building_id=uuid.uuid4(),
        description="Leaking P-trap",
    )
    await db_session.commit()

    state = {
        "verify_pass": False,
        "escalated": False,
        "escalation_reason": None,
        "hypotheses": [
            {
                "fault": "Corroded P-trap joint",
                "calibrated_confidence": 0.7,
                "claims": [
                    {
                        "text": "The P-trap joint is corroded",
                        "claim_type": "descriptive",
                        "grounded": True,
                        "supporting_evidence": [
                            {
                                "doc_id": "test-manual",
                                "page": 0,
                                "score": 0.99,
                                "retrieval_stage": "reranked",
                            }
                        ],
                    },
                    {
                        "text": "Order part PT-100-SS",
                        "claim_type": "part_number",
                        "grounded": False,
                        "supporting_evidence": [],
                    },
                ],
            }
        ],
    }

    diag = await persist_diagnosis_from_state(
        db_session, ticket_id=ticket.id, run_id="run-bl6", state=state
    )
    await db_session.commit()

    assert diag is not None
    assert diag.verify_pass is False

    rows = (
        (
            await db_session.execute(
                select(DiagnosisClaim).where(DiagnosisClaim.diagnosis_id == diag.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    by_text = {r.claim_text: r for r in rows}
    descriptive = by_text["The P-trap joint is corroded"]
    assert descriptive.claim_type == "descriptive"
    assert descriptive.grounded is True
    assert descriptive.evidence["chunks"][0]["doc_id"] == "test-manual"
    part = by_text["Order part PT-100-SS"]
    assert part.claim_type == "part_number"
    assert part.grounded is False


@requires_docker
@pytest.mark.asyncio
async def test_persist_diagnosis_noop_without_hypotheses(db_session: AsyncSession) -> None:
    """CLARIFY-interrupted runs (no hypotheses yet) persist nothing."""
    ticket = await create_ticket(
        db_session,
        org_id=uuid.uuid4(),
        building_id=uuid.uuid4(),
        description="Interrupted run",
    )
    await db_session.commit()
    diag = await persist_diagnosis_from_state(
        db_session,
        ticket_id=ticket.id,
        run_id="run-interrupted",
        state={"hypotheses": [], "pending_question": "Which unit?"},
    )
    assert diag is None


@requires_docker
@pytest.mark.asyncio
async def test_verdict_or_reason_constraint_enforced(db_session: AsyncSession) -> None:
    """CHECK constraint prevents rows with both verdict=NULL and unlabeled_reason=NULL."""
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
        claims=[("Test claim", "descriptive", True, {"doc_id": "m1", "page": 1})],
    )
    await db_session.commit()

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


# ---------------------------------------------------------------------------
# P3-2 flywheel hardening (DB-level)
# ---------------------------------------------------------------------------


async def _ticket_with_diagnosis(db_session: AsyncSession, run_id: str) -> tuple[Any, Any]:
    ticket = await create_ticket(
        db_session,
        org_id=uuid.uuid4(),
        building_id=uuid.uuid4(),
        description="P3-2 hardening fixture",
    )
    diag = await create_diagnosis(
        db_session,
        ticket_id=ticket.id,
        run_id=run_id,
        fault="Test fault",
        calibrated_confidence=None,
        verify_pass=True,
        escalated=False,
        escalation_reason=None,
        claims=[("Test claim", "descriptive", True, {"doc_id": "m1", "page": 1})],
    )
    await db_session.commit()
    return ticket, diag


@requires_docker
@pytest.mark.asyncio
async def test_resolve_without_statement_raises(db_session: AsyncSession) -> None:
    """P3-2: the repo layer itself refuses 'resolved' without a contractor_statement —
    the invariant no longer depends on the /outcomes endpoint's call order."""
    from hero.storage.repo import FlywheelViolationError

    ticket, _ = await _ticket_with_diagnosis(db_session, "p32-guard")
    with pytest.raises(FlywheelViolationError):
        await update_ticket_status(db_session, ticket.id, "resolved")
    # Non-resolved transitions remain unrestricted.
    await update_ticket_status(db_session, ticket.id, "diagnosed")
    await db_session.commit()


@requires_docker
@pytest.mark.asyncio
async def test_bogus_verdict_rejected_by_db(db_session: AsyncSession) -> None:
    """P3-2: verdict_allowed CHECK — free-text verdicts never reach the flywheel table."""
    ticket, diag = await _ticket_with_diagnosis(db_session, "p32-verdict")
    with pytest.raises(Exception):  # noqa: B017
        db_session.add(
            ContractorStatement(
                ticket_id=ticket.id,
                diagnosis_id=diag.id,
                verdict="probably right",
            )
        )
        await db_session.flush()
    await db_session.rollback()


@requires_docker
@pytest.mark.asyncio
async def test_correction_without_actual_fault_rejected_by_db(db_session: AsyncSession) -> None:
    """P3-2: correction_has_fault CHECK — 'wrong' without actual_fault is not a label."""
    ticket, diag = await _ticket_with_diagnosis(db_session, "p32-fault")
    # Capture IDs now — rollback() below expires the ORM instances, and a
    # lazy attribute refresh under asyncpg raises MissingGreenlet.
    ticket_id, diag_id = ticket.id, diag.id
    with pytest.raises(Exception):  # noqa: B017
        db_session.add(
            ContractorStatement(
                ticket_id=ticket_id,
                diagnosis_id=diag_id,
                verdict="wrong",
                actual_fault=None,
            )
        )
        await db_session.flush()
    await db_session.rollback()

    # With actual_fault the same correction is accepted.
    cs = await create_contractor_statement(
        db_session,
        ticket_id=ticket_id,
        diagnosis_id=diag_id,
        verdict="wrong",
        actual_fault="Cracked supply line, not the P-trap",
    )
    await db_session.commit()
    assert cs.id is not None


@requires_docker
@pytest.mark.asyncio
async def test_label_velocity_counts(db_session: AsyncSession) -> None:
    """P3-2 / BL-0 DoD: label velocity separates usable labels from unlabeled rows."""
    from hero.storage.repo import label_velocity

    ticket, diag = await _ticket_with_diagnosis(db_session, "p32-velocity")
    await create_contractor_statement(
        db_session, ticket_id=ticket.id, diagnosis_id=diag.id, verdict="confirmed"
    )
    await create_contractor_statement(
        db_session,
        ticket_id=ticket.id,
        diagnosis_id=diag.id,
        verdict=None,
        unlabeled_reason="Contractor unreachable",
    )
    await db_session.commit()

    metrics = await label_velocity(db_session, days=7)
    assert metrics["total"] == 2
    assert metrics["labeled"] == 1
    assert metrics["unlabeled"] == 1
    assert metrics["per_day"] == pytest.approx(2 / 7)
