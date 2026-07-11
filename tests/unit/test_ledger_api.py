"""P4-3 — GET /tickets/{id}/ledger role gate + org scope + assembly (ASGI)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from hero.api import deps
from hero.api.main import create_app
from hero.api.routers import tickets as tickets_router
from hero.auth.tokens import issue_session_token

SECRET = "unit-test-secret"
ORG_A = uuid.uuid4()
USER_ID = uuid.uuid4()
TICKET_ID = uuid.uuid4()


class _FakeTicket:
    id = TICKET_ID
    org_id = ORG_A
    building_id = uuid.uuid4()
    description = "Rooftop AC rattling"
    status = "diagnosed"
    trade = "hvac"
    urgency = "urgent"
    complexity = "complex"
    created_at = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


class _FakeEvent:
    def __init__(self, seq: int, state: str, payload: dict[str, Any]) -> None:
        self.seq = seq
        self.state = state
        self.payload = payload
        self.run_id = f"ticket-{TICKET_ID}"
        self.created_at = datetime(2026, 7, 11, 12, 1, tzinfo=UTC)


def _token(role: str) -> str:
    return issue_session_token(
        user_id=str(USER_ID),
        org_id=str(ORG_A),
        role=role,
        secret=SECRET,
        expires_in_seconds=3600,
    )


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[httpx.AsyncClient, None]:
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)
    app = create_app()

    async def _no_session() -> AsyncGenerator[Any, None]:
        yield None

    app.dependency_overrides[deps.get_db_session] = _no_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def repo_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_ticket(session: Any, ticket_id: uuid.UUID, org_id: uuid.UUID) -> Any:
        return _FakeTicket() if (ticket_id, org_id) == (TICKET_ID, ORG_A) else None

    async def fake_events(session: Any, ticket_id: uuid.UUID) -> list[Any]:
        return [
            _FakeEvent(1, "triage", {"trade": "hvac", "urgency": "urgent", "path": "full"}),
            _FakeEvent(2, "safety_gate", {"escalated": False, "escalation_reason": None}),
        ]

    async def fake_diagnoses(session: Any, ticket_id: uuid.UUID) -> list[Any]:
        return []

    async def fake_statements(session: Any, ticket_id: uuid.UUID) -> list[Any]:
        return []

    monkeypatch.setattr(tickets_router, "get_ticket_for_org", fake_get_ticket)
    monkeypatch.setattr(tickets_router, "list_ticket_events", fake_events)
    monkeypatch.setattr(tickets_router, "get_diagnoses_with_claims", fake_diagnoses)
    monkeypatch.setattr(tickets_router, "get_statements_for_ticket", fake_statements)


@pytest.mark.asyncio
async def test_ledger_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"/tickets/{TICKET_ID}/ledger")).status_code == 401


@pytest.mark.asyncio
async def test_ledger_contractor_403(client: httpx.AsyncClient, repo_fakes: None) -> None:
    """Contractors keep the narrower GET /tickets/{id} view — no ledger."""
    client.cookies.set(deps.SESSION_COOKIE, _token("contractor"))
    assert (await client.get(f"/tickets/{TICKET_ID}/ledger")).status_code == 403


@pytest.mark.asyncio
async def test_ledger_cross_org_404(client: httpx.AsyncClient, repo_fakes: None) -> None:
    client.cookies.set(deps.SESSION_COOKIE, _token("operator"))
    assert (await client.get(f"/tickets/{uuid.uuid4()}/ledger")).status_code == 404


@pytest.mark.asyncio
async def test_ledger_operator_assembly(client: httpx.AsyncClient, repo_fakes: None) -> None:
    client.cookies.set(deps.SESSION_COOKIE, _token("operator"))
    resp = await client.get(f"/tickets/{TICKET_ID}/ledger")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticket_id"] == str(TICKET_ID)
    assert body["complexity"] == "complex"
    # intake synthesized from the ticket row, then persisted events in seq order
    assert [e["state"] for e in body["entries"]] == ["intake", "triage", "safety_gate"]
    assert body["entries"][1]["data"]["path"] == "full"
