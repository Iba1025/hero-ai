"""Phase 5 STEP 3 round-trip, real Postgres + real stub graph, through ASGI:

chat opener → ticket + pipeline → CLARIFY parks → the question posts INTO the
chat → the tenant's next chat message IS the answer (single resume path) →
completion notice posts into the chat → ledger interleaves the conversation.

Same clarify-injection trick as test_public_roundtrip.py. The chat VLM is an
exploding stand-in: this entire flow is fixed copy + the pipeline — the
conversational model tier must never be touched.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hero.adapters.stub_calibrator import StubCalibrator
from hero.adapters.stub_catalog import StubCatalogResolver
from hero.adapters.stub_embedder import StubEmbedder
from hero.adapters.stub_reranker import StubReranker
from hero.adapters.stub_vlm import StubVLM
from hero.api import background, deps
from hero.api.main import create_app
from hero.api.routers import public as public_router
from hero.graph.build import build_graph
from hero.nova.bridge import COMPLETION_NOTICE, INTAKE_ACK, RESUME_ACK
from hero.storage.ledger import assemble_ledger
from hero.storage.repo import (
    create_building,
    get_diagnoses_with_claims,
    get_statements_for_ticket,
    get_ticket_by_public_slug,
    list_conversation_messages,
    list_ticket_events,
)
from tests.invariants.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.asyncio]

QUESTION = "Which room is the radiator in?"
ANSWER = "The living room"
BUILDING_SLUG = "chat-roundtrip-building"


class _InjectClarify:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def ainvoke(self, run_input: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(run_input, dict):
            run_input = {**run_input, "pending_question": QUESTION}
        return await self._inner.ainvoke(run_input, *args, **kwargs)


class _ExplodingChatVLM:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError("chat VLM must never be touched in this roundtrip")


@pytest.fixture
async def client(
    db_session: AsyncSession, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[httpx.AsyncClient, None]:
    compiled = build_graph(
        embedder=StubEmbedder(),
        reranker=StubReranker(),
        calibrator=StubCalibrator(),
        vlm=StubVLM(),
        catalog=StubCatalogResolver(),
        checkpointer=MemorySaver(),
    )
    shared = deps._ResumeGuardedGraph(_InjectClarify(compiled))

    async def fake_get_graph() -> Any:
        return shared

    monkeypatch.setattr(public_router, "get_graph", fake_get_graph)
    monkeypatch.setattr(public_router, "get_chat_vlm", lambda: _ExplodingChatVLM())

    engine = create_async_engine(postgres_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(public_router, "get_session_factory", lambda: factory)

    app = create_app()

    async def _session_override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[deps.get_db_session] = _session_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await background.drain()
    await engine.dispose()


async def test_chat_intake_clarify_answer_roundtrip(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await create_building(db_session, org_id=uuid.uuid4(), name="Maple Court", slug=BUILDING_SLUG)
    await db_session.commit()

    # 1. Opening message creates the ticket + spawns the FULL pipeline
    #    (DEC-23: depth unchanged); Nova acknowledges with fixed copy.
    resp = await client.post(
        f"/public/buildings/{BUILDING_SLUG}/conversations",
        json={
            "message": "The radiator is cold and makes a banging noise",
            "contact": "555-0123",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    status_slug = body["status_slug"]
    assert status_slug
    assert body["reply"]["body"] == INTAKE_ACK

    await background.drain()  # run parks at CLARIFY
    db_session.expire_all()

    # 2. The pipeline's question arrived IN the chat (post_run_update).
    resp = await client.get(f"/public/status/{status_slug}/messages")
    assert resp.status_code == 200
    convo = resp.json()
    assert convo["state"] == "question for you"
    assert convo["working"] is False
    kinds = [(m["sender"], m["kind"]) for m in convo["messages"]]
    assert kinds == [("tenant", "chat"), ("nova", "chat"), ("nova", "clarify_question")]
    assert convo["messages"][-1]["body"] == QUESTION

    # 3. The tenant's next message IS the clarify answer — resumed through the
    #    single resume path, exactly like POST /answer.
    resp = await client.post(f"/public/status/{status_slug}/messages", json={"message": ANSWER})
    assert resp.status_code == 200
    assert resp.json()["reply"]["body"] == RESUME_ACK
    assert resp.json()["working"] is True

    await background.drain()  # resume completes
    db_session.expire_all()

    # 4. Completion posted into the chat; ticket landed like a form ticket.
    ticket = await get_ticket_by_public_slug(db_session, status_slug)
    assert ticket is not None
    assert ticket.status == "diagnosed"
    assert ticket.pipeline_status == "complete"

    messages = await list_conversation_messages(db_session, ticket.id)
    assert [(m.sender, m.kind) for m in messages] == [
        ("tenant", "chat"),
        ("nova", "chat"),
        ("nova", "clarify_question"),
        ("tenant", "clarify_answer"),
        ("nova", "chat"),
        ("nova", "completion"),
    ]
    assert messages[-1].body == COMPLETION_NOTICE

    # 5. The operator ledger interleaves chat with pipeline events truthfully.
    entries = assemble_ledger(
        ticket,
        await list_ticket_events(db_session, ticket.id),
        await get_diagnoses_with_claims(db_session, ticket.id),
        await get_statements_for_ticket(db_session, ticket.id),
        conversation=messages,
    )
    states = [e["state"] for e in entries]
    assert "integrity_error" not in states
    assert states[0] == "intake"
    assert states.count("conversation") == len(messages)
    assert {"triage", "retrieve", "clarify_pending", "clarify_answered", "verify"} <= set(states)
    # The clarify question was the run's question, verbatim, in the chat.
    pending = next(e for e in entries if e["state"] == "clarify_pending")
    assert pending["data"]["question"] == QUESTION
    answered = next(e for e in entries if e["state"] == "clarify_answered")
    assert answered["data"]["answer"] == ANSWER
