"""Phase 5 STEP 3 — Nova chat endpoints (ASGI, repo/bridge/graph faked).

The trust-boundary assertions are load-bearing: transcript entries expose
exactly {sender, kind, body, created_at} — no guardrail internals, no cost,
no pipeline vocabulary. Bridge ROUTING is covered in test_nova_bridge.py;
these tests cover the HTTP surface around it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from hero.api import background, deps
from hero.api.main import create_app
from hero.api.routers import public as public_router
from hero.nova.bridge import INTAKE_ACK, BridgeTurn

BUILDING_ID = uuid.uuid4()
ORG_ID = uuid.uuid4()
SLUG = "bldg-slug-abc123"
STATUS_SLUG = "status-slug-xyz789"
TICKET_ID = uuid.uuid4()
_TS = datetime(2026, 7, 12, 9, 0, tzinfo=UTC)


class _FakeBuilding:
    id = BUILDING_ID
    org_id = ORG_ID
    name = "Maple Court"
    slug = SLUG


class _FakeTicket:
    def __init__(self) -> None:
        self.id = TICKET_ID
        self.org_id = ORG_ID
        self.building_id = BUILDING_ID
        self.description = "Radiator cold in unit 4"
        self.status = "open"
        self.public_slug = STATUS_SLUG
        self.created_at = _TS
        self.pipeline_status = "complete"


class _FakeSession:
    async def commit(self) -> None:
        pass


def _row(sender: str = "nova", kind: str = "chat", body: str = INTAKE_ACK) -> SimpleNamespace:
    return SimpleNamespace(
        sender=sender, kind=kind, body=body, created_at=_TS, guardrail_reason="x", cost_usd=0.5
    )


@pytest.fixture(autouse=True)
def _fake_rate_allow(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    counts: dict[str, int] = {}

    async def fake_allow(
        session: Any, key: str, *, max_events: int, window_seconds: float = 3600.0
    ) -> bool:
        counts[key] = counts.get(key, 0) + 1
        return counts[key] <= max_events

    monkeypatch.setattr(public_router, "rate_allow", fake_allow)
    return counts


@pytest.fixture(autouse=True)
async def _drain_background() -> AsyncGenerator[None, None]:
    yield
    await background.drain()


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[httpx.AsyncClient, None]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost/unused")
    app = create_app()

    async def _fake_session() -> AsyncGenerator[Any, None]:
        yield _FakeSession()

    app.dependency_overrides[deps.get_db_session] = _fake_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def start_fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fakes for POST /conversations: capture creates, openings, and the run."""
    calls: dict[str, Any] = {"tickets": [], "openings": [], "runs": []}

    async def fake_get_building(session: Any, slug: str) -> Any:
        return _FakeBuilding() if slug == SLUG else None

    async def fake_create_ticket(session: Any, **kwargs: Any) -> Any:
        calls["tickets"].append(kwargs)
        return _FakeTicket()

    async def fake_create_media(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_record_opening(
        session: Any, *, ticket_id: Any, message: str, decision: Any
    ) -> Any:
        calls["openings"].append({"ticket_id": ticket_id, "message": message, "decision": decision})
        kind = "escalation" if decision.action == "escalate" else "chat"
        return _row(kind=kind, body="ack")

    async def fake_get_graph() -> Any:
        return object()

    async def fake_run_ticket_pipeline(graph: Any, ticket_id: Any, **kwargs: Any) -> None:
        calls["runs"].append({"ticket_id": ticket_id, **kwargs})

    monkeypatch.setattr(public_router, "get_building_by_slug", fake_get_building)
    monkeypatch.setattr(public_router, "create_ticket", fake_create_ticket)
    monkeypatch.setattr(public_router, "create_media", fake_create_media)
    monkeypatch.setattr(public_router, "record_opening", fake_record_opening)
    monkeypatch.setattr(public_router, "get_graph", fake_get_graph)
    monkeypatch.setattr(public_router, "run_ticket_pipeline", fake_run_ticket_pipeline)
    monkeypatch.setattr(public_router, "get_session_factory", lambda: None)
    return calls


# ---- POST /public/buildings/{slug}/conversations ----


@pytest.mark.asyncio
async def test_chat_start_unknown_building_404(
    client: httpx.AsyncClient, start_fakes: dict[str, Any]
) -> None:
    resp = await client.post(
        "/public/buildings/wrong-slug/conversations",
        json={"message": "radiator is cold", "contact": "555-0123"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_chat_start_redirect_opener_creates_nothing(
    client: httpx.AsyncClient, start_fakes: dict[str, Any]
) -> None:
    """DEC-24: a legal opener gets fixed copy — no ticket, no rows, no run."""
    resp = await client.post(
        f"/public/buildings/{SLUG}/conversations",
        json={"message": "can I withhold rent until this is fixed?", "contact": "555-0123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_slug"] is None
    assert body["status_path"] is None
    assert body["reply"]["kind"] == "redirect"
    assert "legal or tenancy" in body["reply"]["body"]
    assert start_fakes["tickets"] == []
    assert start_fakes["openings"] == []
    await background.drain()
    assert start_fakes["runs"] == []


@pytest.mark.asyncio
async def test_chat_start_allowed_creates_ticket_and_spawns_run(
    client: httpx.AsyncClient, start_fakes: dict[str, Any]
) -> None:
    """DEC-23: the first allowed message IS the intake — same machinery,
    full pipeline immediately, fixed acknowledgment copy."""
    resp = await client.post(
        f"/public/buildings/{SLUG}/conversations",
        json={"message": "The radiator is cold and banging", "contact": "555-0123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_slug"]
    assert body["status_path"] == f"#/status/{body['status_slug']}"
    assert set(body["reply"]) == {"sender", "kind", "body", "created_at"}  # trust boundary

    created = start_fakes["tickets"][0]
    assert created["org_id"] == ORG_ID
    assert created["description"] == "The radiator is cold and banging"
    opening = start_fakes["openings"][0]
    assert opening["decision"].action == "allow"
    await background.drain()
    assert start_fakes["runs"][0]["ticket_id"] == TICKET_ID


@pytest.mark.asyncio
async def test_chat_start_hazard_still_creates_and_runs(
    client: httpx.AsyncClient, start_fakes: dict[str, Any]
) -> None:
    """A hazard opener escalates (record_opening stamps it) but the ticket
    exists and the pipeline still runs — the ledger stays honest."""
    resp = await client.post(
        f"/public/buildings/{SLUG}/conversations",
        json={"message": "There is a gas smell near the stove", "contact": "555-0123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_slug"]  # a ticket DID get created
    assert body["reply"]["kind"] == "escalation"
    assert start_fakes["openings"][0]["decision"].action == "escalate"
    await background.drain()
    assert start_fakes["runs"][0]["ticket_id"] == TICKET_ID


@pytest.mark.asyncio
async def test_chat_start_empty_message_422(
    client: httpx.AsyncClient, start_fakes: dict[str, Any]
) -> None:
    resp = await client.post(
        f"/public/buildings/{SLUG}/conversations",
        json={"message": "   ", "contact": "555-0123"},
    )
    assert resp.status_code == 422
    assert start_fakes["tickets"] == []


@pytest.mark.asyncio
async def test_chat_start_shares_intake_rate_key(
    client: httpx.AsyncClient,
    start_fakes: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chat and form intake share one budget per building link — the chat
    door is not a way around the form's limit."""
    monkeypatch.setenv("PUBLIC_INTAKE_RATE_PER_HOUR", "2")
    body = {"message": "The radiator is cold", "contact": "555-0123"}
    for _ in range(2):
        r = await client.post(f"/public/buildings/{SLUG}/conversations", json=body)
        assert r.status_code == 200
    resp = await client.post(f"/public/buildings/{SLUG}/conversations", json=body)
    assert resp.status_code == 429
    assert len(start_fakes["tickets"]) == 2


# ---- GET /public/status/{slug}/messages ----


@pytest.fixture
def ticket_fakes(monkeypatch: pytest.MonkeyPatch) -> _FakeTicket:
    ticket = _FakeTicket()

    async def fake_get_ticket(session: Any, public_slug: str) -> Any:
        return ticket if public_slug == STATUS_SLUG else None

    monkeypatch.setattr(public_router, "get_ticket_by_public_slug", fake_get_ticket)
    return ticket


@pytest.mark.asyncio
async def test_transcript_exposes_only_chat_envelope(
    client: httpx.AsyncClient, ticket_fakes: _FakeTicket, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Trust boundary: no guardrail_reason, no cost_usd, no ids — exactly
    the four render fields per message."""

    async def fake_list(session: Any, ticket_id: Any) -> list[Any]:
        return [_row(sender="tenant", body="radiator cold"), _row(kind="clarify_question")]

    monkeypatch.setattr(public_router, "list_conversation_messages", fake_list)
    resp = await client.get(f"/public/status/{STATUS_SLUG}/messages")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"state", "working", "messages"}
    assert body["state"] == "received"  # plain language, never pipeline vocabulary
    assert body["working"] is False
    for m in body["messages"]:
        assert set(m) == {"sender", "kind", "body", "created_at"}


@pytest.mark.asyncio
async def test_transcript_unknown_slug_404(
    client: httpx.AsyncClient, ticket_fakes: _FakeTicket
) -> None:
    assert (await client.get("/public/status/wrong-slug/messages")).status_code == 404


# ---- POST /public/status/{slug}/messages ----


@pytest.fixture
def message_fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fake the bridge + resume machinery around the endpoint."""
    calls: dict[str, Any] = {
        "handled": [],
        "resumes": [],
        "status_stamps": [],
        "turn": BridgeTurn(nova=_row(body="Noted!")),
        "has_conversation": True,
    }

    async def fake_has_conversation(session: Any, ticket_id: Any) -> bool:
        return bool(calls["has_conversation"])

    async def fake_handle(
        vlm: Any, session: Any, *, ticket: Any, message: str, pending_question: Any, settings: Any
    ) -> Any:
        calls["handled"].append({"message": message, "pending_question": pending_question})
        return calls["turn"]

    async def fake_update_pipeline_status(session: Any, ticket_id: Any, status: str) -> None:
        calls["status_stamps"].append(status)

    async def fake_get_graph() -> Any:
        return object()

    async def fake_resume(graph: Any, ticket_id: Any, *, answer: str, **kwargs: Any) -> None:
        calls["resumes"].append({"ticket_id": ticket_id, "answer": answer})

    monkeypatch.setattr(public_router, "has_conversation", fake_has_conversation)
    monkeypatch.setattr(public_router, "handle_tenant_message", fake_handle)
    monkeypatch.setattr(public_router, "update_pipeline_status", fake_update_pipeline_status)
    monkeypatch.setattr(public_router, "get_graph", fake_get_graph)
    monkeypatch.setattr(public_router, "resume_ticket_pipeline", fake_resume)
    monkeypatch.setattr(public_router, "get_session_factory", lambda: None)
    monkeypatch.setattr(public_router, "get_chat_vlm", lambda: object())
    return calls


@pytest.mark.asyncio
async def test_chat_message_conversational_reply(
    client: httpx.AsyncClient, ticket_fakes: _FakeTicket, message_fakes: dict[str, Any]
) -> None:
    resp = await client.post(
        f"/public/status/{STATUS_SLUG}/messages", json={"message": "  it got worse  "}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"reply", "working"}
    assert body["reply"]["body"] == "Noted!"
    assert set(body["reply"]) == {"sender", "kind", "body", "created_at"}
    assert body["working"] is False  # pipeline_status == "complete"
    assert message_fakes["handled"] == [{"message": "it got worse", "pending_question": None}]
    await background.drain()
    assert message_fakes["resumes"] == []


@pytest.mark.asyncio
async def test_chat_message_clarify_answer_spawns_resume(
    client: httpx.AsyncClient, ticket_fakes: _FakeTicket, message_fakes: dict[str, Any]
) -> None:
    """When the bridge routes the message as a clarify answer, the endpoint
    stamps running and resumes through the single-path task — like /answer."""
    message_fakes["turn"] = BridgeTurn(nova=_row(body="thanks"), resume_answer="Unit 4B")
    resp = await client.post(f"/public/status/{STATUS_SLUG}/messages", json={"message": "Unit 4B"})
    assert resp.status_code == 200
    assert resp.json()["working"] is True
    assert message_fakes["status_stamps"] == ["running"]
    await background.drain()
    assert message_fakes["resumes"] == [{"ticket_id": TICKET_ID, "answer": "Unit 4B"}]


@pytest.mark.asyncio
async def test_chat_message_400_for_form_tickets(
    client: httpx.AsyncClient, ticket_fakes: _FakeTicket, message_fakes: dict[str, Any]
) -> None:
    """Form-intake tickets have no conversation — they keep POST /answer."""
    message_fakes["has_conversation"] = False
    resp = await client.post(f"/public/status/{STATUS_SLUG}/messages", json={"message": "hello"})
    assert resp.status_code == 400
    assert message_fakes["handled"] == []


@pytest.mark.asyncio
async def test_chat_message_empty_422(
    client: httpx.AsyncClient, ticket_fakes: _FakeTicket, message_fakes: dict[str, Any]
) -> None:
    resp = await client.post(f"/public/status/{STATUS_SLUG}/messages", json={"message": "   "})
    assert resp.status_code == 422
    assert message_fakes["handled"] == []


@pytest.mark.asyncio
async def test_chat_message_rate_limited_per_status_link(
    client: httpx.AsyncClient,
    ticket_fakes: _FakeTicket,
    message_fakes: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_MESSAGE_RATE_PER_HOUR", "2")
    for _ in range(2):
        r = await client.post(f"/public/status/{STATUS_SLUG}/messages", json={"message": "hi"})
        assert r.status_code == 200
    resp = await client.post(f"/public/status/{STATUS_SLUG}/messages", json={"message": "hi"})
    assert resp.status_code == 429
    assert len(message_fakes["handled"]) == 2


# ---- BL-22: mid-chat photos ----


@pytest.fixture
def photo_fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture media rows + transcript rows appended by the photo path."""
    calls: dict[str, Any] = {"media": [], "appended": []}

    async def fake_create_media(session: Any, **kwargs: Any) -> Any:
        calls["media"].append(kwargs)

    async def fake_append(session: Any, **kwargs: Any) -> Any:
        calls["appended"].append(kwargs)
        return _row(sender=kwargs.get("sender", "tenant"), kind=kwargs.get("kind", "chat"))

    def fake_presign(settings: Any, *, object_key: str, content_type: str, **kw: Any) -> str:
        return f"https://r2.example/{object_key}"

    monkeypatch.setattr(public_router, "create_media", fake_create_media)
    monkeypatch.setattr(public_router, "append_conversation_message", fake_append)
    monkeypatch.setattr(public_router, "presigned_upload_url", fake_presign)
    return calls


@pytest.mark.asyncio
async def test_status_presign_unknown_slug_404(
    client: httpx.AsyncClient, ticket_fakes: _FakeTicket, photo_fakes: dict[str, Any]
) -> None:
    resp = await client.post(
        "/public/status/wrong-slug/presign",
        json={"filename": "leak.jpg", "content_type": "image/jpeg", "size_bytes": 1024},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_status_presign_rejects_non_image(
    client: httpx.AsyncClient, ticket_fakes: _FakeTicket, photo_fakes: dict[str, Any]
) -> None:
    resp = await client.post(
        f"/public/status/{STATUS_SLUG}/presign",
        json={"filename": "notes.pdf", "content_type": "application/pdf", "size_bytes": 100},
    )
    assert resp.status_code == 415


@pytest.mark.asyncio
async def test_status_presign_keys_under_tickets_building(
    client: httpx.AsyncClient, ticket_fakes: _FakeTicket, photo_fakes: dict[str, Any]
) -> None:
    """Keys share the intake prefix + the ticket's building, so the message
    endpoint's public-intake/ validation accepts them unchanged (INV-3)."""
    resp = await client.post(
        f"/public/status/{STATUS_SLUG}/presign",
        json={"filename": "leak.jpg", "content_type": "image/jpeg", "size_bytes": 1024},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object_key"].startswith(f"public-intake/{BUILDING_ID}/")
    assert body["upload_url"].startswith("https://r2.example/")


@pytest.mark.asyncio
async def test_chat_message_with_photos_persists_media_and_photo_row(
    client: httpx.AsyncClient,
    ticket_fakes: _FakeTicket,
    message_fakes: dict[str, Any],
    photo_fakes: dict[str, Any],
) -> None:
    """BL-22: photos become media rows + one tenant kind=photo transcript row
    BEFORE the text turn; the message still routes through the bridge."""
    photos = [
        {"object_key": f"public-intake/{BUILDING_ID}/x/a.jpg", "content_type": "image/jpeg"},
        {"object_key": f"public-intake/{BUILDING_ID}/y/b.jpg", "content_type": "image/png"},
    ]
    resp = await client.post(
        f"/public/status/{STATUS_SLUG}/messages",
        json={"message": "here's what it looks like", "photos": photos},
    )
    assert resp.status_code == 200
    assert [m["object_key"] for m in photo_fakes["media"]] == [p["object_key"] for p in photos]
    assert len(photo_fakes["appended"]) == 1
    row = photo_fakes["appended"][0]
    assert row["sender"] == "tenant"
    assert row["kind"] == "photo"
    assert row["body"] == "2 photos attached"
    assert message_fakes["handled"][0]["message"] == "here's what it looks like"


@pytest.mark.asyncio
async def test_chat_message_redirected_keeps_no_photos(
    client: httpx.AsyncClient,
    ticket_fakes: _FakeTicket,
    message_fakes: dict[str, Any],
    photo_fakes: dict[str, Any],
) -> None:
    """A redirected message (DEC-24) keeps nothing — no media, no photo row."""
    photos = [{"object_key": f"public-intake/{BUILDING_ID}/x/a.jpg", "content_type": "image/jpeg"}]
    resp = await client.post(
        f"/public/status/{STATUS_SLUG}/messages",
        json={"message": "can I withhold rent until this is fixed?", "photos": photos},
    )
    assert resp.status_code == 200
    assert photo_fakes["media"] == []
    assert photo_fakes["appended"] == []


@pytest.mark.asyncio
async def test_chat_message_rejects_foreign_photo_key(
    client: httpx.AsyncClient,
    ticket_fakes: _FakeTicket,
    message_fakes: dict[str, Any],
    photo_fakes: dict[str, Any],
) -> None:
    resp = await client.post(
        f"/public/status/{STATUS_SLUG}/messages",
        json={
            "message": "photo attached",
            "photos": [{"object_key": "somewhere/else.jpg", "content_type": "image/jpeg"}],
        },
    )
    assert resp.status_code == 422
    assert photo_fakes["media"] == []


@pytest.mark.asyncio
async def test_chat_message_pending_question_passed_when_clarifying(
    client: httpx.AsyncClient,
    ticket_fakes: _FakeTicket,
    message_fakes: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_pending_question reads the ledger journal only while status=clarifying."""
    ticket_fakes.status = "clarifying"
    ticket_fakes.pipeline_status = "awaiting_tenant"

    async def fake_events(session: Any, ticket_id: Any) -> list[Any]:
        return [SimpleNamespace(state="clarify_pending", payload={"question": "Which unit?"})]

    monkeypatch.setattr(public_router, "list_ticket_events", fake_events)
    resp = await client.post(f"/public/status/{STATUS_SLUG}/messages", json={"message": "4B"})
    assert resp.status_code == 200
    assert message_fakes["handled"] == [{"message": "4B", "pending_question": "Which unit?"}]
