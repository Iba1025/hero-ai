"""P4-1 auth — passwords, tokens, login flow, role + org enforcement.

Endpoint tests run the real FastAPI app over httpx ASGITransport with the
DB layer monkeypatched — no Postgres needed locally. The DB-backed
org-scoping invariant lives in tests/invariants/test_inv_org_scoping.py.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest

from hero.api import deps
from hero.api.main import create_app
from hero.api.routers import auth as auth_router
from hero.api.routers import tickets as tickets_router
from hero.auth.passwords import hash_password, verify_password
from hero.auth.tokens import TokenError, decode_session_token, issue_session_token

SECRET = "unit-test-secret"
ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
USER_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# passwords
# ---------------------------------------------------------------------------


def test_password_roundtrip() -> None:
    h = hash_password("hunter2!")
    assert h != "hunter2!"
    assert h.startswith("$argon2id$")
    assert verify_password(h, "hunter2!")


def test_password_wrong_rejected() -> None:
    h = hash_password("hunter2!")
    assert not verify_password(h, "hunter3!")


def test_password_malformed_hash_rejected() -> None:
    assert not verify_password("not-a-hash", "anything")


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------


def _token(role: str = "contractor", org: uuid.UUID = ORG_A, expires: int = 3600) -> str:
    return issue_session_token(
        user_id=str(USER_ID),
        org_id=str(org),
        role=role,
        secret=SECRET,
        expires_in_seconds=expires,
    )


def test_token_roundtrip() -> None:
    claims = decode_session_token(_token(), secret=SECRET)
    assert claims.user_id == str(USER_ID)
    assert claims.org_id == str(ORG_A)
    assert claims.role == "contractor"


def test_token_expired_rejected() -> None:
    token = _token(expires=-10)
    with pytest.raises(TokenError):
        decode_session_token(token, secret=SECRET)


def test_token_wrong_secret_rejected() -> None:
    with pytest.raises(TokenError):
        decode_session_token(_token(), secret="other-secret")


def test_token_tampered_rejected() -> None:
    header, payload, sig = _token().split(".")
    with pytest.raises(TokenError):
        decode_session_token(f"{header}.{payload}x.{sig}", secret=SECRET)


# ---------------------------------------------------------------------------
# endpoint behavior (ASGI, DB monkeypatched)
# ---------------------------------------------------------------------------


class _FakeUser:
    def __init__(self, password: str, role: str = "contractor") -> None:
        self.id = USER_ID
        self.org_id = ORG_A
        self.email = "c@org-a.example"
        self.password_hash = hash_password(password)
        self.role = role


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # get_settings() constructs fresh each call; env var beats .env file.
    monkeypatch.setenv("JWT_SECRET_KEY", SECRET)


@pytest.fixture
async def client(secret_env: None) -> AsyncGenerator[httpx.AsyncClient, None]:
    app = create_app()

    async def _no_session() -> AsyncGenerator[Any, None]:
        yield None

    app.dependency_overrides[deps.get_db_session] = _no_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_login_sets_httponly_cookie(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _FakeUser("pw-123")

    async def fake_lookup(session: Any, email: str) -> Any:
        return user if email == user.email else None

    monkeypatch.setattr(auth_router, "get_user_by_email", fake_lookup)
    resp = await client.post("/auth/login", json={"email": user.email, "password": "pw-123"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "contractor"
    set_cookie = resp.headers["set-cookie"]
    assert "hero_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie


@pytest.mark.asyncio
@pytest.mark.parametrize("password", ["wrong", ""])
async def test_login_bad_password_401(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, password: str
) -> None:
    user = _FakeUser("pw-123")

    async def fake_lookup(session: Any, email: str) -> Any:
        return user

    monkeypatch.setattr(auth_router, "get_user_by_email", fake_lookup)
    resp = await client.post("/auth/login", json={"email": user.email, "password": password})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email_same_401(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown email and wrong password are indistinguishable (no enumeration)."""

    async def fake_lookup(session: Any, email: str) -> Any:
        return None

    monkeypatch.setattr(auth_router, "get_user_by_email", fake_lookup)
    resp = await client.post("/auth/login", json={"email": "who@nowhere", "password": "x"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_me_requires_cookie(client: httpx.AsyncClient) -> None:
    assert (await client.get("/auth/me")).status_code == 401
    client.cookies.set(deps.SESSION_COOKIE, _token())
    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    assert resp.json()["org_id"] == str(ORG_A)


@pytest.mark.asyncio
async def test_expired_session_401(client: httpx.AsyncClient) -> None:
    client.cookies.set(deps.SESSION_COOKIE, _token(expires=-10))
    assert (await client.get("/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_unconfigured_secret_503(monkeypatch: pytest.MonkeyPatch) -> None:
    # Empty env var beats any value in .env — simulates unconfigured auth.
    monkeypatch.setenv("JWT_SECRET_KEY", "")
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/auth/me")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_contractor_cannot_create_ticket_403(client: httpx.AsyncClient) -> None:
    client.cookies.set(deps.SESSION_COOKIE, _token(role="contractor"))
    resp = await client.post(
        "/tickets", json={"building_id": str(uuid.uuid4()), "description": "x"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_contractor_cannot_read_label_velocity_403(client: httpx.AsyncClient) -> None:
    client.cookies.set(deps.SESSION_COOKIE, _token(role="contractor"))
    assert (await client.get("/outcomes/metrics/label-velocity")).status_code == 403


@pytest.mark.asyncio
async def test_cross_org_ticket_read_404(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unit-level org scoping: repo returns None for a cross-org id → 404.

    The DB-backed version (real WHERE org_id filter) is the invariant test in
    tests/invariants/test_inv_org_scoping.py.
    """

    async def scoped_lookup(session: Any, ticket_id: uuid.UUID, org_id: uuid.UUID) -> Any:
        return None  # ticket exists in ORG_B; caller is ORG_A → scoped query finds nothing

    monkeypatch.setattr(tickets_router, "get_ticket_for_org", scoped_lookup)
    client.cookies.set(deps.SESSION_COOKIE, _token(role="contractor", org=ORG_A))
    resp = await client.get(f"/tickets/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_no_session_on_tickets_401(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"/tickets/{uuid.uuid4()}")).status_code == 401
