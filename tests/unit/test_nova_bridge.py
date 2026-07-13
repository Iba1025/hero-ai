"""Nova ↔ pipeline bridge routing (Phase 5 STEP 3, DEC-23/24) — repo faked.

The load-bearing assertions are the safety-ordering ones: guardrails run
BEFORE clarify-answer routing (a hazard sent as a clarify answer escalates,
never resumes), escalation banners are fixed copy, and post_run_update never
posts the banner twice.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from hero.nova import bridge
from hero.nova.bridge import (
    COMPLETION_NOTICE,
    ESCALATION_NOTICE,
    INTAKE_ACK,
    RESUME_ACK,
    handle_tenant_message,
    post_run_update,
    record_opening,
)
from hero.nova.chat import NovaTurn
from hero.nova.guardrails import GuardrailDecision

TICKET_ID = uuid.uuid4()
SETTINGS = object()  # only forwarded to (faked) nova_turn


class _Store:
    """In-memory stand-in for the conversation_message table + status stamps."""

    def __init__(self) -> None:
        self.messages: list[SimpleNamespace] = []
        self.status_updates: list[tuple[uuid.UUID, str]] = []


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _Store:
    st = _Store()

    async def fake_append(
        session: Any,
        *,
        ticket_id: uuid.UUID,
        sender: str,
        body: str,
        kind: str = "chat",
        guardrail_reason: str | None = None,
        cost_usd: float = 0.0,
    ) -> SimpleNamespace:
        row = SimpleNamespace(
            ticket_id=ticket_id,
            seq=len(st.messages) + 1,
            sender=sender,
            kind=kind,
            body=body,
            guardrail_reason=guardrail_reason,
            cost_usd=cost_usd,
        )
        st.messages.append(row)
        return row

    async def fake_list(session: Any, ticket_id: uuid.UUID) -> list[SimpleNamespace]:
        return list(st.messages)

    async def fake_update_status(session: Any, ticket_id: uuid.UUID, status: str) -> None:
        st.status_updates.append((ticket_id, status))

    monkeypatch.setattr(bridge, "append_conversation_message", fake_append)
    monkeypatch.setattr(bridge, "list_conversation_messages", fake_list)
    monkeypatch.setattr(bridge, "update_ticket_status", fake_update_status)
    return st


class _ExplodingVLM:
    """Any attribute access means the model was called — the test fails."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError("VLM must never be touched on this path")


def _ticket(pipeline_status: str = "complete") -> Any:
    return SimpleNamespace(id=TICKET_ID, pipeline_status=pipeline_status)


# ---- record_opening ----


async def test_opening_allowed_gets_fixed_intake_ack(store: _Store) -> None:
    nova = await record_opening(
        object(),  # session unused by fakes
        ticket_id=TICKET_ID,
        message="The radiator is cold",
        decision=GuardrailDecision(action="allow"),
    )
    assert [m.sender for m in store.messages] == ["tenant", "nova"]
    assert store.messages[0].body == "The radiator is cold"
    assert nova.body == INTAKE_ACK  # deterministic — no model call at intake
    assert nova.kind == "chat"
    assert store.status_updates == []


async def test_opening_hazard_escalates_immediately(store: _Store) -> None:
    nova = await record_opening(
        object(),
        ticket_id=TICKET_ID,
        message="I smell gas in the hallway",
        decision=GuardrailDecision(action="escalate", reason="hazard_keyword:smell gas"),
    )
    assert store.status_updates == [(TICKET_ID, "escalated")]
    assert nova.kind == "escalation"
    assert nova.body == ESCALATION_NOTICE  # fixed banner, never generated
    assert store.messages[0].guardrail_reason == "hazard_keyword:smell gas"


# ---- handle_tenant_message: guardrails first ----


async def test_hazard_mid_chat_escalates_without_model(store: _Store) -> None:
    turn = await handle_tenant_message(
        _ExplodingVLM(),
        object(),
        ticket=_ticket(),
        message="there's a gas smell in here now too",
        pending_question=None,
        settings=SETTINGS,
    )
    assert store.status_updates == [(TICKET_ID, "escalated")]
    assert turn.nova.kind == "escalation"
    assert turn.nova.body == ESCALATION_NOTICE
    assert turn.resume_answer is None


async def test_hazard_beats_clarify_answer(store: _Store) -> None:
    """CRITICAL ordering: a hazard sent while a clarify question is pending
    escalates — it must NEVER be fed to the resume path as an answer."""
    turn = await handle_tenant_message(
        _ExplodingVLM(),
        object(),
        ticket=_ticket(pipeline_status="awaiting_tenant"),
        message="actually there's a gas leak by the unit",
        pending_question="Which unit is affected?",
        settings=SETTINGS,
    )
    assert turn.resume_answer is None  # the run stays parked; a human acts
    assert turn.nova.kind == "escalation"
    assert store.status_updates == [(TICKET_ID, "escalated")]


async def test_redirect_records_fixed_copy_without_model(store: _Store) -> None:
    turn = await handle_tenant_message(
        _ExplodingVLM(),
        object(),
        ticket=_ticket(),
        message="can I withhold rent for this?",
        pending_question=None,
        settings=SETTINGS,
    )
    assert turn.resume_answer is None
    assert turn.nova.kind == "redirect"
    assert "legal or tenancy" in turn.nova.body  # DEC-24 fixed copy
    assert store.messages[0].guardrail_reason is not None
    assert store.status_updates == []


# ---- handle_tenant_message: clarify answer routing ----


async def test_clarify_answer_routes_to_resume(store: _Store) -> None:
    turn = await handle_tenant_message(
        _ExplodingVLM(),  # fixed RESUME_ACK — no model call
        object(),
        ticket=_ticket(pipeline_status="awaiting_tenant"),
        message="It's unit 4B",
        pending_question="Which unit is affected?",
        settings=SETTINGS,
    )
    assert turn.resume_answer == "It's unit 4B"
    assert turn.nova.body == RESUME_ACK
    assert [m.kind for m in store.messages] == ["clarify_answer", "chat"]


async def test_no_resume_unless_run_is_parked(
    store: _Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale pending question without awaiting_tenant goes conversational."""

    async def fake_nova_turn(vlm: Any, **kwargs: Any) -> NovaTurn:
        return NovaTurn(kind="reply", text="Noted!", cost_usd=0.001)

    monkeypatch.setattr(bridge, "nova_turn", fake_nova_turn)
    turn = await handle_tenant_message(
        object(),
        object(),
        ticket=_ticket(pipeline_status="running"),
        message="It's unit 4B",
        pending_question="Which unit is affected?",
        settings=SETTINGS,
    )
    assert turn.resume_answer is None
    assert turn.nova.kind == "chat"


# ---- handle_tenant_message: conversational tier ----


async def test_chat_maps_history_and_accumulates_cost(
    store: _Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    await record_opening(
        object(),
        ticket_id=TICKET_ID,
        message="The radiator is cold",
        decision=GuardrailDecision(action="allow"),
    )
    store.messages[1].cost_usd = 0.01  # pretend the ack had cost (exercise the sum)

    seen: dict[str, Any] = {}

    async def fake_nova_turn(
        vlm: Any,
        *,
        history: list[dict[str, str]],
        message: str,
        conversation_cost_usd: float,
        settings: Any,
    ) -> NovaTurn:
        seen.update(history=history, message=message, cost=conversation_cost_usd, settings=settings)
        return NovaTurn(kind="reply", text="Got it — anything else?", cost_usd=0.002)

    monkeypatch.setattr(bridge, "nova_turn", fake_nova_turn)
    turn = await handle_tenant_message(
        object(),
        object(),
        ticket=_ticket(),
        message="it also makes a banging noise",
        pending_question=None,
        settings=SETTINGS,
    )
    assert seen["history"] == [
        {"role": "user", "content": "The radiator is cold"},
        {"role": "assistant", "content": INTAKE_ACK},
    ]
    assert seen["message"] == "it also makes a banging noise"
    assert seen["cost"] == pytest.approx(0.01)
    assert seen["settings"] is SETTINGS
    assert turn.nova.kind == "chat"
    assert turn.nova.cost_usd == pytest.approx(0.002)
    assert turn.resume_answer is None


async def test_capped_turn_recorded_as_capped(
    store: _Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_nova_turn(vlm: Any, **kwargs: Any) -> NovaTurn:
        return NovaTurn(kind="capped", text="hand-off copy")

    monkeypatch.setattr(bridge, "nova_turn", fake_nova_turn)
    turn = await handle_tenant_message(
        object(),
        object(),
        ticket=_ticket(),
        message="and another thing",
        pending_question=None,
        settings=SETTINGS,
    )
    assert turn.nova.kind == "capped"
    assert turn.nova.body == "hand-off copy"


# ---- post_run_update ----


async def test_post_run_update_noop_without_conversation(store: _Store) -> None:
    """Form/operator tickets have no conversation rows — nothing is posted."""
    await post_run_update(object(), ticket_id=TICKET_ID, status="diagnosed", pending_question=None)
    assert store.messages == []


async def _seed_chat(store: _Store) -> None:
    await record_opening(
        object(),
        ticket_id=TICKET_ID,
        message="The radiator is cold",
        decision=GuardrailDecision(action="allow"),
    )


async def test_post_run_update_posts_clarify_question(store: _Store) -> None:
    await _seed_chat(store)
    await post_run_update(
        object(),
        ticket_id=TICKET_ID,
        status="clarifying",
        pending_question="Which unit is affected?",
    )
    last = store.messages[-1]
    assert last.kind == "clarify_question"
    assert last.body == "Which unit is affected?"  # verbatim — the run's question
    assert last.sender == "nova"


async def test_post_run_update_posts_completion_notice(store: _Store) -> None:
    await _seed_chat(store)
    await post_run_update(object(), ticket_id=TICKET_ID, status="diagnosed", pending_question=None)
    last = store.messages[-1]
    assert last.kind == "completion"
    assert last.body == COMPLETION_NOTICE  # fixed copy — no diagnosis substance


async def test_post_run_update_posts_escalation_once(store: _Store) -> None:
    await _seed_chat(store)
    await post_run_update(object(), ticket_id=TICKET_ID, status="escalated", pending_question=None)
    assert store.messages[-1].kind == "escalation"
    n = len(store.messages)
    # A second escalated leg (e.g. resume after a guardrail escalation) — deduped.
    await post_run_update(object(), ticket_id=TICKET_ID, status="escalated", pending_question=None)
    assert len(store.messages) == n
