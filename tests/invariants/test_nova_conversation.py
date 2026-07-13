"""Phase 5 STEP 3 — conversation persistence + sticky escalation, real Postgres.

INV-1 spirit: once a Nova guardrail escalates a ticket (hazard in chat while
a run is in flight), a completing run must NEVER downgrade it back to
diagnosed/clarifying. A human owns it now.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hero.api.pipeline import persist_completion
from hero.nova.bridge import COMPLETION_NOTICE
from hero.storage.ledger import assemble_ledger
from hero.storage.repo import (
    append_conversation_message,
    create_building,
    create_ticket,
    get_ticket,
    has_conversation,
    list_conversation_messages,
    list_ticket_events,
    update_ticket_status,
)
from tests.invariants.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.asyncio]


async def _make_ticket(db_session: AsyncSession) -> uuid.UUID:
    org_id = uuid.uuid4()
    building = await create_building(
        db_session, org_id=org_id, name="Maple Court", slug=f"b-{uuid.uuid4().hex[:8]}"
    )
    ticket = await create_ticket(
        db_session,
        org_id=org_id,
        building_id=building.id,
        description="Radiator cold in unit 4",
    )
    await db_session.commit()
    return ticket.id


async def test_escalation_is_sticky_over_a_completing_run(db_session: AsyncSession) -> None:
    """A guardrail escalated the ticket mid-run; the run then finishes with a
    would-be 'diagnosed' result — the status must stay escalated."""
    ticket_id = await _make_ticket(db_session)
    await update_ticket_status(db_session, ticket_id, "escalated")  # Nova guardrail stamp
    await db_session.commit()

    status = await persist_completion(
        db_session, ticket_id=ticket_id, run_id=f"ticket-{ticket_id}", result={}
    )
    await db_session.commit()
    assert status == "escalated"
    ticket = await get_ticket(db_session, ticket_id)
    assert ticket is not None
    assert ticket.status == "escalated"


async def test_completing_run_posts_into_existing_conversation(
    db_session: AsyncSession,
) -> None:
    """Chat-originated tickets hear back: a diagnosed completion appends the
    fixed completion notice; form tickets (no rows) get nothing."""
    ticket_id = await _make_ticket(db_session)
    assert await has_conversation(db_session, ticket_id) is False

    # Form ticket: persist_completion must NOT invent a conversation.
    await persist_completion(
        db_session, ticket_id=ticket_id, run_id=f"ticket-{ticket_id}", result={}
    )
    await db_session.commit()
    assert await list_conversation_messages(db_session, ticket_id) == []

    # Chat ticket: seed the opening exchange, complete again → notice appended.
    await append_conversation_message(
        db_session, ticket_id=ticket_id, sender="tenant", body="Radiator cold in unit 4"
    )
    await append_conversation_message(db_session, ticket_id=ticket_id, sender="nova", body="ack")
    await db_session.commit()

    await persist_completion(
        db_session, ticket_id=ticket_id, run_id=f"ticket-{ticket_id}", result={}
    )
    await db_session.commit()
    messages = await list_conversation_messages(db_session, ticket_id)
    assert [m.seq for m in messages] == [1, 2, 3]  # single-writer seq rule held
    assert messages[-1].kind == "completion"
    assert messages[-1].body == COMPLETION_NOTICE  # fixed copy — no diagnosis substance


async def test_ledger_joins_conversation_entries(db_session: AsyncSession) -> None:
    """Conversation rows appear in the assembled ledger as `conversation`
    entries — canonical in conversation_message, never in ticket_event."""
    ticket_id = await _make_ticket(db_session)
    await append_conversation_message(
        db_session,
        ticket_id=ticket_id,
        sender="tenant",
        body="can I withhold rent?",
        guardrail_reason="tenancy_legal:withhold rent",
    )
    await append_conversation_message(
        db_session, ticket_id=ticket_id, sender="nova", kind="redirect", body="fixed copy"
    )
    await db_session.commit()

    ticket = await get_ticket(db_session, ticket_id)
    assert ticket is not None
    entries = assemble_ledger(
        ticket,
        await list_ticket_events(db_session, ticket_id),
        [],
        [],
        conversation=await list_conversation_messages(db_session, ticket_id),
    )
    assert entries[0]["state"] == "intake"  # stable sort keeps intake first
    convo = [e for e in entries if e["state"] == "conversation"]
    assert [c["data"]["sender"] for c in convo] == ["tenant", "nova"]
    assert convo[0]["data"] == {
        "sender": "tenant",
        "kind": "chat",
        "body": "can I withhold rent?",
        "guardrail_reason": "tenancy_legal:withhold rent",
    }
    assert convo[1]["data"]["kind"] == "redirect"
