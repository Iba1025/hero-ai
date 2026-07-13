"""P4-4 round-trip, real Postgres + real stub graph, end to end through ASGI:

public intake → CLARIFY pending → public answer (single resume path) →
resumed to completion → the assembled ledger shows the full round.

The stub pipeline never asks a clarify question organically, so the graph is
wrapped to inject `pending_question` into the create-run input — exactly how
tests/invariants/test_inv6_checkpoints.py triggers the interrupt. The wrapper
sits INSIDE the real `_ResumeGuardedGraph`, so the resume also exercises the
single-resume-path guard with a genuine Command(resume=...).
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
from hero.api.ratelimit import limiter
from hero.api.routers import public as public_router
from hero.graph.build import build_graph
from hero.storage.ledger import assemble_ledger
from hero.storage.repo import (
    create_building,
    get_diagnoses_with_claims,
    get_statements_for_ticket,
    get_ticket_by_public_slug,
    list_ticket_events,
)
from tests.invariants.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.asyncio]

# Deliberately benign: "water"/"leak" wording triages to water_intrusion, a
# hard escalation category (INV-1) — that path ends the run at the safety gate.
QUESTION = "Which room is the radiator in?"
ANSWER = "The living room"
BUILDING_SLUG = "roundtrip-building-slug"


class _InjectClarify:
    """First (dict) invocation gets pending_question injected; Command resumes
    and everything else pass straight through to the compiled graph."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def ainvoke(self, run_input: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(run_input, dict):
            run_input = {**run_input, "pending_question": QUESTION}
        return await self._inner.ainvoke(run_input, *args, **kwargs)


@pytest.fixture
async def client(
    db_session: AsyncSession, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[httpx.AsyncClient, None]:
    limiter.reset()

    # ONE shared graph instance across requests: the resume request must see
    # the checkpoint the create request wrote (MemorySaver is per-instance).
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

    # BL-17 (H1): the background run opens its OWN sessions — bind its factory
    # to the same test Postgres (settings.database_url may point elsewhere).
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
    await background.drain()  # never leave a run writing into a dropped schema
    await engine.dispose()


async def test_public_intake_clarify_answer_roundtrip(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await create_building(db_session, org_id=uuid.uuid4(), name="Maple Court", slug=BUILDING_SLUG)

    # 1. Tenant files the problem → accepted immediately (BL-17/H1); the run
    #    happens in a background task and interrupts at CLARIFY.
    resp = await client.post(
        f"/public/buildings/{BUILDING_SLUG}/tickets",
        json={
            "description": "The radiator is cold and makes a banging noise",
            "contact": "555-0123",
            "photos": [],
        },
    )
    assert resp.status_code == 200
    status_slug = resp.json()["status_slug"]

    await background.drain()  # let the create-run park at CLARIFY
    db_session.expire_all()  # the run committed on its own sessions

    # 2. Status page shows the pending question in plain language.
    resp = await client.get(f"/public/status/{status_slug}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "question for you"
    assert body["question"] == QUESTION
    assert body["working"] is False
    assert set(body) == {"state", "question", "description", "created_at", "working"}

    # 3. Tenant answers → accepted immediately; the resume runs in the
    #    background through the single resume path → completes.
    resp = await client.post(f"/public/status/{status_slug}/answer", json={"answer": ANSWER})
    assert resp.status_code == 200
    assert resp.json()["state"] == "working on it"
    assert resp.json()["working"] is True
    assert resp.json()["question"] is None

    await background.drain()  # let the resume finish
    db_session.expire_all()

    # 4. The ledger shows the full round — no integrity error, no missing question.
    ticket = await get_ticket_by_public_slug(db_session, status_slug)
    assert ticket is not None
    assert ticket.status == "diagnosed"
    assert ticket.pipeline_status == "complete"  # BL-17: the stamp landed
    assert ticket.tenant_contact == "555-0123"

    entries = assemble_ledger(
        ticket,
        await list_ticket_events(db_session, ticket.id),
        await get_diagnoses_with_claims(db_session, ticket.id),
        await get_statements_for_ticket(db_session, ticket.id),
    )
    states = [e["state"] for e in entries]
    assert "integrity_error" not in states
    assert states[:4] == ["intake", "triage", "retrieve", "clarify_pending"]
    assert {"clarify_answered", "diagnose", "verify", "safety_gate"} <= set(states)
    assert states.index("clarify_pending") < states.index("clarify_answered")

    pending = next(e for e in entries if e["state"] == "clarify_pending")
    assert pending["data"]["question"] == QUESTION
    answered = next(e for e in entries if e["state"] == "clarify_answered")
    assert answered["data"] == {"question": QUESTION, "answer": ANSWER, "round": 1}

    # The claim join held (one verify event, one diagnosis row).
    verify = next(e for e in entries if e["state"] == "verify")
    assert "fault" in verify["data"]
