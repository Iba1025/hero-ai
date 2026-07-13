"""P4-3 ledger — derive ticket_event rows from graph state, assemble the trail.

Pure functions only: the API layer calls `events_from_state` after a graph run
and persists via repo.append_ticket_events; the ledger endpoint fetches rows
and calls `assemble_ledger`. Nodes never touch the DB.

Honest-gap rule (P4-3c): a state that did not run produces no event; missing
data is absent, never invented.
"""

from __future__ import annotations

from typing import Any

from hero.storage.models import (
    ContractorStatement,
    ConversationMessage,
    Diagnosis,
    DiagnosisClaim,
    Ticket,
    TicketEvent,
)

Event = tuple[str, dict[str, Any]]


def _citation(chunk: dict[str, Any]) -> dict[str, Any]:
    """Citation pointer only — page text stays in Qdrant, never in the ledger."""
    return {
        "doc_id": chunk.get("doc_id"),
        "page": chunk.get("page"),
        "retrieval_stage": chunk.get("retrieval_stage"),
        "score": chunk.get("score"),
    }


def events_from_state(state: dict[str, Any], *, resumed: bool = False) -> list[Event]:
    """Ordered ledger events for one graph run (ticket create or CLARIFY resume).

    resumed=True skips TRIAGE — it does not rerun after a CLARIFY resume
    (RETRIEVE onward does). An interrupted run ends at clarify_pending:
    nothing after it ran, so nothing after it is recorded.
    """
    events: list[Event] = []

    if not resumed and state.get("trade") is not None:
        events.append(
            (
                "triage",
                {
                    "trade": state.get("trade"),
                    "urgency": state.get("urgency"),
                    "complexity": state.get("complexity"),
                    "path": "fast" if state.get("complexity") == "simple" else "full",
                },
            )
        )

    evidence = state.get("evidence") or []
    if evidence:
        events.append(
            ("retrieve", {"citations": [_citation(c) for c in evidence], "count": len(evidence)})
        )

    if state.get("pending_question"):
        events.append(
            (
                "clarify_pending",
                {
                    "question": state.get("pending_question"),
                    "round": int(state.get("clarify_rounds") or 0) + 1,
                },
            )
        )
        return events  # interrupted — the run stopped here

    hypotheses = state.get("hypotheses") or []
    if hypotheses:
        events.append(
            (
                "diagnose",
                {
                    "hypotheses": [
                        {
                            "fault": h.get("fault"),
                            "calibrated_confidence": h.get("calibrated_confidence"),
                            "reasoning": h.get("reasoning") or [],
                            "n_claims": len(h.get("claims") or []),
                        }
                        for h in hypotheses
                    ]
                },
            )
        )
        events.append(("verify", {"verify_pass": state.get("verify_pass")}))

    # SAFETY_GATE runs after VERIFY; it also records the diagnosis_unparseable
    # escalation path where DIAGNOSE produced no hypotheses (P3-1.5).
    if hypotheses or state.get("escalated"):
        events.append(
            (
                "safety_gate",
                {
                    "escalated": bool(state.get("escalated")),
                    "escalation_reason": state.get("escalation_reason"),
                },
            )
        )

    if not state.get("escalated") and (state.get("work_order_id") or state.get("sku")):
        events.append(
            ("procure", {"work_order_id": state.get("work_order_id"), "sku": state.get("sku")})
        )

    return events


def _claim_row(claim: DiagnosisClaim) -> dict[str, Any]:
    evidence = claim.evidence if isinstance(claim.evidence, dict) else {}
    chunks = evidence.get("chunks")
    citations = [
        {"doc_id": c.get("doc_id"), "page": c.get("page")}
        for c in (chunks if isinstance(chunks, list) else [])
        if isinstance(c, dict)
    ]
    return {
        "text": claim.claim_text,
        "claim_type": claim.claim_type,
        "grounded": claim.grounded,
        "citations": citations,
    }


def assemble_ledger(
    ticket: Ticket,
    events: list[TicketEvent],
    diagnoses_with_claims: list[tuple[Diagnosis, list[DiagnosisClaim]]],
    statements: list[ContractorStatement],
    conversation: list[ConversationMessage] | None = None,
) -> list[dict[str, Any]]:
    """Chronological ledger entries, all from persisted rows.

    Nova conversation rows (Phase 5 STEP 3) are joined in as `conversation`
    entries — canonical in conversation_message, never duplicated into
    ticket_event (same rule as diagnosis_claim). Entries are stable-sorted by
    timestamp at the end so chat and pipeline events interleave truthfully;
    equal timestamps (rows from one transaction) keep construction order.

    Per-claim substance is canonical in diagnosis_claim (DEC-6) and joined
    onto verify entries positionally: the nth verify event corresponds to the
    nth diagnosis row — both exist exactly once per completed run, in order.
    (run_id cannot disambiguate: create and resume share one thread id.)

    Tripwire (P4-4 hardening): the positional join is only performed when
    verify-event count == diagnosis-row count. On mismatch, the join is
    skipped entirely and a loud `integrity_error` entry is emitted — never
    a silent mis-attribution. BL-9 (corrective retrieval loop) must revisit
    this join: a loop that runs VERIFY more than once per run breaks the
    one-verify-per-completed-run assumption the join rests on.
    """
    entries: list[dict[str, Any]] = [
        {
            "state": "intake",
            "ts": ticket.created_at.isoformat(),
            "run_id": None,
            "data": {"description": ticket.description},
        }
    ]

    n_verify = sum(1 for ev in events if ev.state == "verify")
    join_ok = n_verify == len(diagnoses_with_claims)
    if not join_ok:
        entries.append(
            {
                "state": "integrity_error",
                "ts": ticket.created_at.isoformat(),
                "run_id": None,
                "data": {
                    "verify_events": n_verify,
                    "diagnosis_rows": len(diagnoses_with_claims),
                    "message": (
                        "verify-event count != diagnosis-row count; "
                        "claim join skipped to avoid mis-attribution"
                    ),
                },
            }
        )

    verify_i = 0
    for ev in events:
        data: dict[str, Any] = dict(ev.payload)
        if ev.state == "verify":
            if join_ok:
                diag, claims = diagnoses_with_claims[verify_i]
                data["fault"] = diag.fault
                data["diagnosis_id"] = str(diag.id)
                data["claims"] = [_claim_row(c) for c in claims]
            verify_i += 1
        entries.append(
            {
                "state": ev.state,
                "ts": ev.created_at.isoformat(),
                "run_id": ev.run_id,
                "data": data,
            }
        )

    for s in statements:
        entries.append(
            {
                "state": "outcome",
                "ts": s.created_at.isoformat(),
                "run_id": None,
                "data": {
                    "statement_id": str(s.id),
                    "verdict": s.verdict,
                    "actual_fault": s.actual_fault,
                    "actual_part_sku": s.actual_part_sku,
                    "free_text": s.free_text,
                    "unlabeled_reason": s.unlabeled_reason,
                    "contractor_id": str(s.contractor_id) if s.contractor_id else None,
                },
            }
        )

    for m in conversation or []:
        entries.append(
            {
                "state": "conversation",
                "ts": m.created_at.isoformat(),
                "run_id": None,
                "data": {
                    "sender": m.sender,
                    "kind": m.kind,
                    "body": m.body,
                    "guardrail_reason": m.guardrail_reason,
                },
            }
        )

    entries.sort(key=lambda e: str(e["ts"]))  # stable — see docstring
    return entries
