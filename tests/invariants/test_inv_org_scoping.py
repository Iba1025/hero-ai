"""P4-1 invariant: a contractor JWT cannot read another org's tickets.

The org filter must live in the query layer (repo.get_ticket_for_org) —
a WHERE clause, not a caller-side comparison. These tests hit a real
Postgres (DATABASE_URL or testcontainers); they skip locally without one.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hero.auth.passwords import hash_password
from hero.storage.repo import create_ticket, create_user, get_ticket_for_org, get_user_by_email
from tests.invariants.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.asyncio]

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


async def _seed_ticket(session: AsyncSession, org_id: uuid.UUID) -> uuid.UUID:
    ticket = await create_ticket(
        session,
        org_id=org_id,
        building_id=uuid.uuid4(),
        description="Leaking pipe in unit 4B",
    )
    return ticket.id


async def test_cross_org_ticket_lookup_returns_none(db_session: AsyncSession) -> None:
    """The query-layer scope: an org-B ticket id is invisible to org A."""
    ticket_id = await _seed_ticket(db_session, ORG_B)
    assert await get_ticket_for_org(db_session, ticket_id, ORG_A) is None


async def test_same_org_ticket_lookup_succeeds(db_session: AsyncSession) -> None:
    ticket_id = await _seed_ticket(db_session, ORG_A)
    ticket = await get_ticket_for_org(db_session, ticket_id, ORG_A)
    assert ticket is not None
    assert ticket.org_id == ORG_A


async def test_user_seeding_roundtrip(db_session: AsyncSession) -> None:
    """CLI seeding path: create_user + get_user_by_email + role CHECK."""
    email = f"c-{uuid.uuid4()}@org-a.example"
    await create_user(
        db_session,
        org_id=ORG_A,
        email=email,
        password_hash=hash_password("pw"),
        role="contractor",
    )
    user = await get_user_by_email(db_session, email)
    assert user is not None
    assert user.role == "contractor"
    assert user.org_id == ORG_A
    # password hashes are argon2id, never plaintext
    assert user.password_hash.startswith("$argon2id$")
