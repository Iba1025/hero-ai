"""Nova ↔ pipeline bridge (Phase 5 STEP 3, DEC-23/24).

Chat-first tenant intake over the SAME machinery as the P4-4 form: the first
allowed message creates the ticket and the full verified pipeline is spawned
immediately (depth unchanged — DEC-23); Nova acknowledges with fixed copy.
From then on every tenant message routes deterministically:

1. Guardrails (hero.nova.guardrails) — a hazard escalates the ticket with the
   fixed banner (never generated copy); blocked topics get fixed redirect copy.
2. A pending CLARIFY question while the run is parked (awaiting_tenant) → the
   message IS the clarify answer; the caller resumes it ONLY through
   hero.api.resume (single resume path — extended, never bypassed).
3. Otherwise → the conversational tier via nova_turn (token/message caps).

Pipeline → chat: hero.api.pipeline.persist_completion calls post_run_update,
which posts fixed-copy updates into chat-originated conversations (the CLARIFY
question, the completion notice, the escalation banner). Plain language only —
no diagnosis substance ever crosses the public boundary (P4-4 rule).

Honest gap (pilot): a tenant message sent while the run is in flight gets a
conversational reply but does NOT feed the pipeline — only clarify answers do
(via the resume path). The operator sees every message in the ledger.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from hero.config import Settings, get_settings
from hero.interfaces.vlm import VLM
from hero.nova.chat import nova_turn
from hero.nova.guardrails import GuardrailDecision, check_message
from hero.storage.models import ConversationMessage, Ticket
from hero.storage.repo import (
    append_conversation_message,
    list_conversation_messages,
    update_ticket_status,
)

# ── Fixed copy — reviewed like code, never generated (same rule as DEC-24) ──

INTAKE_ACK = (
    "Got it — I've logged this for the building team and I'm checking the "
    "equipment's manuals now. That usually takes about half a minute; updates "
    "will appear right here. If anything changes, just tell me."
)

RESUME_ACK = (
    "Thanks — I've passed that along and I'm checking the manuals again. "
    "I'll post an update here shortly."
)

ESCALATION_NOTICE = (
    "This needs a person right away, so I've alerted the building team — "
    "someone will follow up with you directly. If you think anyone is in "
    "danger, leave the area and call 911 or your building's emergency line."
)

COMPLETION_NOTICE = (
    "Update: the building team now has a full report on this and will take "
    "it from here. You can check back here any time."
)


@dataclass(frozen=True)
class BridgeTurn:
    """One routed tenant message: the Nova row to render, plus — when the
    message was a clarify answer — the answer the caller must resume with
    (through hero.api.resume, never directly)."""

    nova: ConversationMessage
    resume_answer: str | None = None


async def record_opening(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    message: str,
    decision: GuardrailDecision,
) -> ConversationMessage:
    """Persist the conversation's first exchange for a freshly created ticket.

    `decision` is the caller's check_message result for the opening message —
    'allow' gets the fixed intake acknowledgment (deterministic, no model
    call: the pipeline's CLARIFY is the one questioner); 'escalate' gets the
    fixed banner and the ticket is stamped escalated immediately (INV-1
    spirit — never wait for the run to say so). Redirect openers never reach
    here: the router returns fixed copy without creating anything.
    """
    await append_conversation_message(
        session,
        ticket_id=ticket_id,
        sender="tenant",
        body=message,
        guardrail_reason=decision.reason,
    )
    if decision.action == "escalate":
        await update_ticket_status(session, ticket_id, "escalated")
        return await append_conversation_message(
            session,
            ticket_id=ticket_id,
            sender="nova",
            kind="escalation",
            body=ESCALATION_NOTICE,
            guardrail_reason=decision.reason,
        )
    return await append_conversation_message(
        session, ticket_id=ticket_id, sender="nova", body=INTAKE_ACK
    )


async def handle_tenant_message(
    vlm: VLM,
    session: AsyncSession,
    *,
    ticket: Ticket,
    message: str,
    pending_question: str | None,
    settings: Settings | None = None,
) -> BridgeTurn:
    """Route one mid-conversation tenant message (see module docstring).

    Guardrails run FIRST — a hazard sent as a clarify answer escalates, it is
    never fed to the resume path. Does not commit; the caller commits (and
    spawns the resume when resume_answer is set)."""
    settings = settings or get_settings()

    decision = check_message(message)
    if decision.action == "escalate":
        await append_conversation_message(
            session,
            ticket_id=ticket.id,
            sender="tenant",
            body=message,
            guardrail_reason=decision.reason,
        )
        # Sticky by design: persist_completion never downgrades an escalated
        # ticket, so a run still in flight cannot overwrite this (INV-1 spirit).
        await update_ticket_status(session, ticket.id, "escalated")
        nova = await append_conversation_message(
            session,
            ticket_id=ticket.id,
            sender="nova",
            kind="escalation",
            body=ESCALATION_NOTICE,
            guardrail_reason=decision.reason,
        )
        return BridgeTurn(nova=nova)

    if decision.action == "redirect":
        await append_conversation_message(
            session,
            ticket_id=ticket.id,
            sender="tenant",
            body=message,
            guardrail_reason=decision.reason,
        )
        nova = await append_conversation_message(
            session,
            ticket_id=ticket.id,
            sender="nova",
            kind="redirect",
            body=decision.reply or "",
            guardrail_reason=decision.reason,
        )
        return BridgeTurn(nova=nova)

    if pending_question is not None and ticket.pipeline_status == "awaiting_tenant":
        # CLARIFY as Nova chat: this message answers the pipeline's question.
        await append_conversation_message(
            session,
            ticket_id=ticket.id,
            sender="tenant",
            kind="clarify_answer",
            body=message,
        )
        nova = await append_conversation_message(
            session, ticket_id=ticket.id, sender="nova", body=RESUME_ACK
        )
        return BridgeTurn(nova=nova, resume_answer=message)

    # Conversational tier. History is everything the tenant has seen, in
    # order; accumulated cost feeds the (logged, non-blocking) ceiling.
    prior = await list_conversation_messages(session, ticket.id)
    history = [
        {"role": "user" if m.sender == "tenant" else "assistant", "content": m.body} for m in prior
    ]
    turn = await nova_turn(
        vlm,
        history=history,
        message=message,
        conversation_cost_usd=sum(m.cost_usd for m in prior),
        settings=settings,
    )
    # Guardrails already passed above, so the turn is 'reply' or 'capped'.
    await append_conversation_message(session, ticket_id=ticket.id, sender="tenant", body=message)
    nova = await append_conversation_message(
        session,
        ticket_id=ticket.id,
        sender="nova",
        kind="capped" if turn.kind == "capped" else "chat",
        body=turn.text or "",
        cost_usd=turn.cost_usd,
    )
    return BridgeTurn(nova=nova)


async def post_run_update(
    session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    status: str,
    pending_question: str | None,
) -> None:
    """Post a finished (or CLARIFY-parked) run's outcome into the conversation.

    No-op for form/operator tickets (no conversation rows). Fixed copy only —
    the diagnosis itself never crosses the public boundary. Called by
    hero.api.pipeline.persist_completion on every run leg (create, resume,
    recovery), so chat-originated tickets always hear back."""
    messages = await list_conversation_messages(session, ticket_id)
    if not messages:
        return

    if status == "clarifying" and pending_question:
        await append_conversation_message(
            session,
            ticket_id=ticket_id,
            sender="nova",
            kind="clarify_question",
            body=pending_question,
        )
    elif status == "escalated":
        # The guardrail path may already have posted the banner — never twice.
        if not any(m.kind == "escalation" for m in messages):
            await append_conversation_message(
                session,
                ticket_id=ticket_id,
                sender="nova",
                kind="escalation",
                body=ESCALATION_NOTICE,
            )
    elif status == "diagnosed":
        await append_conversation_message(
            session,
            ticket_id=ticket_id,
            sender="nova",
            kind="completion",
            body=COMPLETION_NOTICE,
        )
