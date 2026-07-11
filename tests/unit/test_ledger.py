"""P4-3 ledger — event derivation (events_from_state) and assembly (assemble_ledger).

Honest-gap rule under test: states that didn't run produce no entry;
an interrupted run records nothing past clarify_pending.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from hero.storage.ledger import assemble_ledger, events_from_state

# ---------------------------------------------------------------------------
# events_from_state
# ---------------------------------------------------------------------------

_CHUNK = {"doc_id": "test-hvac-manual", "page": 2, "retrieval_stage": "reranked", "score": 0.91}

_COMPLETED_STATE: dict[str, Any] = {
    "ticket_id": "t-1",
    "trade": "hvac",
    "urgency": "urgent",
    "complexity": "standard",
    "evidence": [_CHUNK],
    "clarify_rounds": 0,
    "pending_question": None,
    "hypotheses": [
        {
            "fault": "Failing run capacitor",
            "calibrated_confidence": 0.72,
            "reasoning": ["hum then silence points at the capacitor"],
            "claims": [{"text": "Replace CP-35-440", "grounded": True}],
        }
    ],
    "verify_pass": True,
    "escalated": False,
    "escalation_reason": None,
    "work_order_id": "wo-1",
    "sku": "CP-35-440",
}


def test_completed_run_full_sequence() -> None:
    states = [s for s, _ in events_from_state(_COMPLETED_STATE)]
    assert states == ["triage", "retrieve", "diagnose", "verify", "safety_gate", "procure"]


def test_triage_payload_and_path() -> None:
    events = dict(events_from_state(_COMPLETED_STATE))
    assert events["triage"] == {
        "trade": "hvac",
        "urgency": "urgent",
        "complexity": "standard",
        "path": "full",
    }
    simple = {**_COMPLETED_STATE, "complexity": "simple"}
    assert dict(events_from_state(simple))["triage"]["path"] == "fast"


def test_retrieve_citations_carry_no_page_text() -> None:
    chunk_with_text = {**_CHUNK, "text": "page text must never enter the ledger"}
    state = {**_COMPLETED_STATE, "evidence": [chunk_with_text]}
    (citation,) = dict(events_from_state(state))["retrieve"]["citations"]
    assert citation == {
        "doc_id": "test-hvac-manual",
        "page": 2,
        "retrieval_stage": "reranked",
        "score": 0.91,
    }


def test_interrupted_run_stops_at_clarify_pending() -> None:
    state = {
        **_COMPLETED_STATE,
        "pending_question": "Where is the rattling coming from?",
        "hypotheses": [],
        "work_order_id": None,
        "sku": None,
    }
    events = events_from_state(state)
    assert [s for s, _ in events] == ["triage", "retrieve", "clarify_pending"]
    assert events[-1][1] == {"question": "Where is the rattling coming from?", "round": 1}


def test_resumed_run_skips_triage() -> None:
    states = [s for s, _ in events_from_state(_COMPLETED_STATE, resumed=True)]
    assert states == ["retrieve", "diagnose", "verify", "safety_gate", "procure"]


def test_escalated_run_has_no_procure_and_loud_gate() -> None:
    state = {
        **_COMPLETED_STATE,
        "escalated": True,
        "escalation_reason": "gas leak — hard escalation trade",
        "work_order_id": None,
        "sku": None,
    }
    events = events_from_state(state)
    assert [s for s, _ in events][-1] == "safety_gate"
    assert events[-1][1]["escalated"] is True
    assert "gas leak" in events[-1][1]["escalation_reason"]


def test_unparseable_diagnosis_records_gate_without_diagnose() -> None:
    """P3-1.5 path: DIAGNOSE produced nothing; the gate still records why."""
    state = {
        **_COMPLETED_STATE,
        "hypotheses": [],
        "escalated": True,
        "escalation_reason": "diagnosis_unparseable",
        "work_order_id": None,
        "sku": None,
    }
    states = [s for s, _ in events_from_state(state)]
    assert "diagnose" not in states
    assert "verify" not in states
    assert states[-1] == "safety_gate"


def test_empty_state_produces_no_events() -> None:
    assert events_from_state({"ticket_id": "t-1", "description": "x"}) == []


# ---------------------------------------------------------------------------
# assemble_ledger (fakes standing in for ORM rows)
# ---------------------------------------------------------------------------

_TS = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


class _FakeTicket:
    id = uuid.uuid4()
    description = "Rooftop AC rattling and shutting off"
    created_at = _TS


class _FakeEvent:
    def __init__(self, seq: int, state: str, payload: dict[str, Any]) -> None:
        self.seq = seq
        self.state = state
        self.payload = payload
        self.run_id = "ticket-t-1"
        self.created_at = _TS


class _FakeDiag:
    id = uuid.uuid4()
    fault = "Failing run capacitor"


class _FakeClaim:
    claim_text = "Replace capacitor CP-35-440"
    claim_type = "part_number"
    grounded = True

    def __init__(self) -> None:
        self.evidence: dict[str, Any] = {
            "chunks": [{"doc_id": "test-hvac-manual", "page": 2, "text": "never shown"}]
        }


class _FakeStatement:
    id = uuid.uuid4()
    verdict = "confirmed"
    actual_fault = None
    actual_part_sku = None
    free_text = "swapped it, runs fine"
    unlabeled_reason = None
    contractor_id = uuid.uuid4()
    created_at = _TS


def test_assemble_ledger_order_and_claim_join() -> None:
    events = [
        _FakeEvent(1, "triage", {"trade": "hvac"}),
        _FakeEvent(2, "verify", {"verify_pass": True}),
    ]
    entries = assemble_ledger(
        _FakeTicket(),  # type: ignore[arg-type]
        events,  # type: ignore[arg-type]
        [(_FakeDiag(), [_FakeClaim()])],  # type: ignore[list-item]
        [_FakeStatement()],  # type: ignore[list-item]
    )
    assert [e["state"] for e in entries] == ["intake", "triage", "verify", "outcome"]
    verify = entries[2]["data"]
    assert verify["fault"] == "Failing run capacitor"
    assert verify["claims"] == [
        {
            "text": "Replace capacitor CP-35-440",
            "claim_type": "part_number",
            "grounded": True,
            "citations": [{"doc_id": "test-hvac-manual", "page": 2}],
        }
    ]
    assert entries[3]["data"]["verdict"] == "confirmed"


def test_assemble_ledger_honest_gaps() -> None:
    """No events, no diagnosis, no outcome → intake only; nothing invented."""
    entries = assemble_ledger(_FakeTicket(), [], [], [])  # type: ignore[arg-type]
    assert [e["state"] for e in entries] == ["intake"]


def test_assemble_ledger_verify_without_diagnosis_row() -> None:
    """A verify event with no matching diagnosis row stays bare — absent, not invented."""
    entries = assemble_ledger(
        _FakeTicket(),  # type: ignore[arg-type]
        [_FakeEvent(1, "verify", {"verify_pass": False})],  # type: ignore[list-item]
        [],
        [],
    )
    assert entries[1]["data"] == {"verify_pass": False}
