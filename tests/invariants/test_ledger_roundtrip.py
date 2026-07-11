"""P4-3 DB round-trip: ticket_event journal → assembled ledger, real Postgres.

Covers the persistence path the ASGI tests fake: append (seq continuation),
ordered read-back, claim join from diagnosis_claim, and the outcome entry.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hero.storage.ledger import assemble_ledger, events_from_state
from hero.storage.repo import (
    append_ticket_events,
    create_contractor_statement,
    create_diagnosis,
    create_ticket,
    get_diagnoses_with_claims,
    get_statements_for_ticket,
    list_ticket_events,
)
from tests.invariants.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.asyncio]

ORG = uuid.uuid4()

_STATE = {
    "trade": "hvac",
    "urgency": "urgent",
    "complexity": "complex",
    "evidence": [
        {"doc_id": "test-hvac-manual", "page": 2, "retrieval_stage": "reranked", "score": 0.9}
    ],
    "hypotheses": [
        {"fault": "Failing capacitor", "calibrated_confidence": 0.7, "claims": [{}]},
    ],
    "verify_pass": True,
    "escalated": False,
    "work_order_id": "wo-1",
    "sku": "CP-35-440",
}


async def test_ledger_db_roundtrip(db_session: AsyncSession) -> None:
    ticket = await create_ticket(
        db_session, org_id=ORG, building_id=uuid.uuid4(), description="AC rattling"
    )
    run_id = f"ticket-{ticket.id}"

    # First run interrupted at CLARIFY, then the resumed run — two appends,
    # seq must continue across them.
    interrupted = {**_STATE, "hypotheses": [], "pending_question": "Which unit?"}
    await append_ticket_events(
        db_session, ticket_id=ticket.id, run_id=run_id, events=events_from_state(interrupted)
    )
    resumed = [("clarify_answered", {"question": "Which unit?", "answer": "Rooftop", "round": 1})]
    resumed += events_from_state(_STATE, resumed=True)
    await append_ticket_events(db_session, ticket_id=ticket.id, run_id=run_id, events=resumed)

    diag = await create_diagnosis(
        db_session,
        ticket_id=ticket.id,
        run_id=run_id,
        fault="Failing capacitor",
        calibrated_confidence=0.7,
        verify_pass=True,
        escalated=False,
        escalation_reason=None,
        claims=[
            (
                "Replace CP-35-440",
                "part_number",
                True,
                {"chunks": [{"doc_id": "test-hvac-manual", "page": 2}]},
            )
        ],
    )
    await create_contractor_statement(
        db_session,
        ticket_id=ticket.id,
        diagnosis_id=diag.id,
        verdict="confirmed",
        contractor_id=uuid.uuid4(),
    )

    events = await list_ticket_events(db_session, ticket.id)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))

    entries = assemble_ledger(
        ticket,
        events,
        await get_diagnoses_with_claims(db_session, ticket.id),
        await get_statements_for_ticket(db_session, ticket.id),
    )
    assert [e["state"] for e in entries] == [
        "intake",
        "triage",
        "retrieve",
        "clarify_pending",
        "clarify_answered",
        "retrieve",
        "diagnose",
        "verify",
        "safety_gate",
        "procure",
        "outcome",
    ]
    verify_entry = next(e for e in entries if e["state"] == "verify")
    assert verify_entry["data"]["claims"][0]["grounded"] is True
    assert verify_entry["data"]["claims"][0]["citations"] == [
        {"doc_id": "test-hvac-manual", "page": 2}
    ]
    assert entries[-1]["data"]["verdict"] == "confirmed"
