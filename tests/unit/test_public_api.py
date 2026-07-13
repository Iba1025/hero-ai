"""P4-4 — public tenant intake + status (ASGI, repo/graph faked).

The load-bearing assertions are the trust boundary ones: public responses
expose NOTHING org-scoped beyond the building's name and the ticket's own
plain-language status. Exact-key-set checks, not just presence checks.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from hero.api import deps
from hero.api.main import create_app
from hero.api.ratelimit import limiter
from hero.api.resume import NotAwaitingClarificationError
from hero.api.routers import public as public_router
from hero.graph.state import MediaRef

BUILDING_ID = uuid.uuid4()
ORG_ID = uuid.uuid4()
SLUG = "bldg-slug-abc123"
STATUS_SLUG = "status-slug-xyz789"
TICKET_ID = uuid.uuid4()


class _FakeBuilding:
    id = BUILDING_ID
    org_id = ORG_ID
    name = "Maple Court"
    slug = SLUG


class _FakeTicket:
    def __init__(self, status: str = "clarifying") -> None:
        self.id = TICKET_ID
        self.org_id = ORG_ID
        self.building_id = BUILDING_ID
        self.description = "Radiator cold in unit 4"
        self.status = status
        self.public_slug = STATUS_SLUG
        self.created_at = datetime(2026, 7, 12, 9, 0, tzinfo=UTC)


class _FakeEvent:
    def __init__(self, state: str, payload: dict[str, Any]) -> None:
        self.state = state
        self.payload = payload


@pytest.fixture(autouse=True)
def _fresh_limiter() -> None:
    limiter.reset()


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[httpx.AsyncClient, None]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost/unused")
    app = create_app()

    async def _no_session() -> AsyncGenerator[Any, None]:
        yield None

    app.dependency_overrides[deps.get_db_session] = _no_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def building_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_building(session: Any, slug: str) -> Any:
        return _FakeBuilding() if slug == SLUG else None

    monkeypatch.setattr(public_router, "get_building_by_slug", fake_get_building)


@pytest.fixture
def presign_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_presign(settings: Any, *, object_key: str, content_type: str, **kw: Any) -> str:
        return f"https://r2.example/{object_key}?sig=test"

    monkeypatch.setattr(public_router, "presigned_upload_url", fake_presign)


@pytest.fixture
def intake_fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture create_ticket/create_media/run_and_persist calls."""
    calls: dict[str, Any] = {"tickets": [], "media": [], "runs": []}

    async def fake_create_ticket(session: Any, **kwargs: Any) -> Any:
        calls["tickets"].append(kwargs)
        return _FakeTicket()

    async def fake_create_media(session: Any, **kwargs: Any) -> Any:
        calls["media"].append(kwargs)
        return None

    async def fake_get_graph() -> Any:
        return object()

    async def fake_run_and_persist(graph: Any, session: Any, ticket: Any, **kwargs: Any) -> str:
        calls["runs"].append({"ticket": ticket, **kwargs})
        return "clarifying"

    monkeypatch.setattr(public_router, "create_ticket", fake_create_ticket)
    monkeypatch.setattr(public_router, "create_media", fake_create_media)
    monkeypatch.setattr(public_router, "get_graph", fake_get_graph)
    monkeypatch.setattr(public_router, "run_and_persist", fake_run_and_persist)
    return calls


@pytest.fixture
def status_fakes(monkeypatch: pytest.MonkeyPatch) -> _FakeTicket:
    ticket = _FakeTicket()

    async def fake_get_ticket(session: Any, public_slug: str) -> Any:
        return ticket if public_slug == STATUS_SLUG else None

    async def fake_events(session: Any, ticket_id: uuid.UUID) -> list[Any]:
        return [
            _FakeEvent("triage", {"trade": "hvac"}),
            _FakeEvent("clarify_pending", {"question": "Which unit?", "round": 1}),
        ]

    monkeypatch.setattr(public_router, "get_ticket_by_public_slug", fake_get_ticket)
    monkeypatch.setattr(public_router, "list_ticket_events", fake_events)
    return ticket


_INTAKE_BODY = {"description": "Radiator cold in unit 4", "contact": "555-0123", "photos": []}


# ---- building link ----


@pytest.mark.asyncio
async def test_unknown_building_link_404(client: httpx.AsyncClient, building_fake: None) -> None:
    assert (await client.get("/public/buildings/wrong-slug")).status_code == 404


@pytest.mark.asyncio
async def test_building_exposes_only_name(client: httpx.AsyncClient, building_fake: None) -> None:
    """Trust boundary: no org_id, no building id — the display name only."""
    resp = await client.get(f"/public/buildings/{SLUG}")
    assert resp.status_code == 200
    assert resp.json() == {"name": "Maple Court"}


# ---- presign (P4-4d upload constraints) ----


@pytest.mark.asyncio
async def test_presign_rejects_non_image(
    client: httpx.AsyncClient, building_fake: None, presign_fake: None
) -> None:
    resp = await client.post(
        f"/public/buildings/{SLUG}/presign",
        json={"filename": "notes.pdf", "content_type": "application/pdf", "size_bytes": 100},
    )
    assert resp.status_code == 415


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, -1, 10 * 1024 * 1024 + 1])
async def test_presign_rejects_bad_size(
    client: httpx.AsyncClient, building_fake: None, presign_fake: None, size: int
) -> None:
    resp = await client.post(
        f"/public/buildings/{SLUG}/presign",
        json={"filename": "leak.jpg", "content_type": "image/jpeg", "size_bytes": size},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_presign_happy_path_sanitizes_filename(
    client: httpx.AsyncClient, building_fake: None, presign_fake: None
) -> None:
    resp = await client.post(
        f"/public/buildings/{SLUG}/presign",
        json={
            "filename": "../weird name!.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 1024,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object_key"].startswith(f"public-intake/{BUILDING_ID}/")
    assert body["object_key"].endswith("weird_name_.jpg")  # traversal + specials scrubbed
    assert body["upload_url"].startswith("https://r2.example/")


# ---- intake validation ----


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {**_INTAKE_BODY, "description": "   "},
        {**_INTAKE_BODY, "description": "x" * 4001},
        {**_INTAKE_BODY, "contact": ""},
        {**_INTAKE_BODY, "contact": "y" * 201},
        {
            **_INTAKE_BODY,
            "photos": [
                {"object_key": f"public-intake/x/{i}.jpg", "content_type": "image/jpeg"}
                for i in range(7)
            ],
        },
        {
            **_INTAKE_BODY,
            "photos": [{"object_key": "uploads/other-org-key.jpg", "content_type": "image/jpeg"}],
        },
    ],
)
async def test_intake_422s(
    client: httpx.AsyncClient,
    building_fake: None,
    intake_fakes: dict[str, Any],
    body: dict[str, Any],
) -> None:
    resp = await client.post(f"/public/buildings/{SLUG}/tickets", json=body)
    assert resp.status_code == 422
    assert intake_fakes["tickets"] == []  # rejected before any write


@pytest.mark.asyncio
async def test_intake_rejects_non_image_photo(
    client: httpx.AsyncClient, building_fake: None, intake_fakes: dict[str, Any]
) -> None:
    body = {
        **_INTAKE_BODY,
        "photos": [{"object_key": "public-intake/x/a.mp4", "content_type": "video/mp4"}],
    }
    resp = await client.post(f"/public/buildings/{SLUG}/tickets", json=body)
    assert resp.status_code == 415
    assert intake_fakes["tickets"] == []


@pytest.mark.asyncio
async def test_intake_happy_path_lands_in_building_org(
    client: httpx.AsyncClient, building_fake: None, intake_fakes: dict[str, Any]
) -> None:
    body = {
        **_INTAKE_BODY,
        "photos": [
            {
                "object_key": "public-intake/x/leak.jpg",
                "content_type": "image/jpeg",
                "sha256": None,  # http LAN phone — hash unavailable, never invented
            }
        ],
    }
    resp = await client.post(f"/public/buildings/{SLUG}/tickets", json=body)
    assert resp.status_code == 200
    out = resp.json()
    assert out["status_path"] == f"#/status/{out['status_slug']}"

    created = intake_fakes["tickets"][0]
    assert created["org_id"] == ORG_ID
    assert created["building_id"] == BUILDING_ID
    assert created["tenant_contact"] == "555-0123"
    assert created["public_slug"] == out["status_slug"]
    assert intake_fakes["media"][0]["sha256"] is None
    # Regression: the route once passed the raw MIME type ("image/jpeg") and
    # dropped sha256 — every photo-carrying ticket 500'd when DIAGNOSE built
    # TicketState. The dicts handed to the graph must validate as MediaRef.
    run_media = intake_fakes["runs"][0]["media"]
    assert run_media == [
        {"object_key": "public-intake/x/leak.jpg", "media_type": "image", "sha256": None}
    ]
    for m in run_media:
        MediaRef(**m)  # must not raise


@pytest.mark.asyncio
async def test_intake_rate_limited_per_building_link(
    client: httpx.AsyncClient,
    building_fake: None,
    intake_fakes: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PUBLIC_INTAKE_RATE_PER_HOUR", "2")
    for _ in range(2):
        assert (
            await client.post(f"/public/buildings/{SLUG}/tickets", json=_INTAKE_BODY)
        ).status_code == 200
    resp = await client.post(f"/public/buildings/{SLUG}/tickets", json=_INTAKE_BODY)
    assert resp.status_code == 429
    assert len(intake_fakes["tickets"]) == 2


# ---- status page ----


@pytest.mark.asyncio
async def test_status_unknown_slug_404(
    client: httpx.AsyncClient, status_fakes: _FakeTicket
) -> None:
    assert (await client.get("/public/status/wrong-slug")).status_code == 404


@pytest.mark.asyncio
async def test_status_exposes_exactly_four_fields(
    client: httpx.AsyncClient, status_fakes: _FakeTicket
) -> None:
    """Trust boundary: plain phrase + question + own description + created_at.
    No trade/urgency/org/diagnosis ever crosses this boundary."""
    resp = await client.get(f"/public/status/{STATUS_SLUG}")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"state", "question", "description", "created_at"}
    assert body["state"] == "question for you"
    assert body["question"] == "Which unit?"  # from the last clarify_pending event
    assert body["description"] == "Radiator cold in unit 4"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "phrase"),
    [
        ("open", "received"),
        ("escalated", "looking into it"),
        ("diagnosed", "being handled"),
        ("resolved", "resolved"),
        ("someday-new-status", "looking into it"),  # unknown → safe fallback
    ],
)
async def test_status_plain_language_mapping(
    client: httpx.AsyncClient, status_fakes: _FakeTicket, status: str, phrase: str
) -> None:
    status_fakes.status = status
    resp = await client.get(f"/public/status/{STATUS_SLUG}")
    body = resp.json()
    assert body["state"] == phrase
    assert body["question"] is None  # question only surfaces while clarifying


# ---- answer → single resume path ----


@pytest.mark.asyncio
async def test_answer_goes_through_single_resume_path(
    client: httpx.AsyncClient, status_fakes: _FakeTicket, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_get_graph() -> Any:
        return object()

    async def fake_resume(
        graph: Any, session: Any, *, ticket_id: uuid.UUID, answer: str
    ) -> dict[str, Any]:
        calls.append({"ticket_id": ticket_id, "answer": answer})
        status_fakes.status = "diagnosed"  # resume completed the run
        return {"pending_question": None}

    monkeypatch.setattr(public_router, "get_graph", fake_get_graph)
    monkeypatch.setattr(public_router, "resume_with_answer", fake_resume)

    resp = await client.post(f"/public/status/{STATUS_SLUG}/answer", json={"answer": "  Unit 4B  "})
    assert resp.status_code == 200
    assert calls == [{"ticket_id": TICKET_ID, "answer": "Unit 4B"}]
    body = resp.json()
    assert body["state"] == "being handled"
    assert body["question"] is None


@pytest.mark.asyncio
async def test_answer_400_when_nothing_pending(
    client: httpx.AsyncClient, status_fakes: _FakeTicket, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_graph() -> Any:
        return object()

    async def fake_resume(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotAwaitingClarificationError()

    monkeypatch.setattr(public_router, "get_graph", fake_get_graph)
    monkeypatch.setattr(public_router, "resume_with_answer", fake_resume)

    resp = await client.post(f"/public/status/{STATUS_SLUG}/answer", json={"answer": "hello"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_answer_empty_422(client: httpx.AsyncClient, status_fakes: _FakeTicket) -> None:
    resp = await client.post(f"/public/status/{STATUS_SLUG}/answer", json={"answer": "   "})
    assert resp.status_code == 422
