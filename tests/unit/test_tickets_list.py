"""P4-2 — GET /tickets org-scoped list endpoint (ASGI, DB monkeypatched)."""

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


class _FakeTicket:
    def __init__(self, description: str, status: str = "diagnosed") -> None:
        self.id = uuid.uuid4()
        self.description = description
        self.status = status
        self.trade = "hvac"
        self.urgency = "urgent"
        self.complexity = "standard"
        self.created_at = datetime.now(UTC)


def _token(role: str = "contractor") -> str:
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


@pytest.mark.asyncio
async def test_list_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/tickets")).status_code == 401


@pytest.mark.asyncio
async def test_list_is_org_scoped(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint passes the session org to the scoped repo query."""
    seen: list[uuid.UUID] = []
    rows = [_FakeTicket("Rooftop AC rattling"), _FakeTicket("Leaking pipe 4B")]

    async def fake_list(session: Any, org_id: uuid.UUID, *, limit: int = 100) -> list[Any]:
        seen.append(org_id)
        return rows

    monkeypatch.setattr(tickets_router, "list_tickets_for_org", fake_list)
    client.cookies.set(deps.SESSION_COOKIE, _token(role="contractor"))
    resp = await client.get("/tickets")
    assert resp.status_code == 200
    assert seen == [ORG_A]
    body = resp.json()
    assert [t["description"] for t in body] == ["Rooftop AC rattling", "Leaking pipe 4B"]
    assert body[0]["trade"] == "hvac"
    assert body[0]["urgency"] == "urgent"
    assert body[0]["status"] == "diagnosed"


@pytest.mark.asyncio
async def test_list_empty_org(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_list(session: Any, org_id: uuid.UUID, *, limit: int = 100) -> list[Any]:
        return []

    monkeypatch.setattr(tickets_router, "list_tickets_for_org", fake_list)
    client.cookies.set(deps.SESSION_COOKIE, _token(role="operator"))
    resp = await client.get("/tickets")
    assert resp.status_code == 200
    assert resp.json() == []
