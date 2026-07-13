"""BL-15 — Postgres-backed rate limiting (Phase 5 STEP 3), real Postgres.

The reason this exists: the per-process in-memory window reset on every API
restart (FRICTION.md), so a restart handed abusers a fresh budget. The window
now lives in `rate_limit_event` rows — restart-proof by construction.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hero.api.ratelimit import allow
from hero.storage.models import RateLimitEvent
from tests.invariants.conftest import requires_docker

pytestmark = [requires_docker, pytest.mark.asyncio]


async def test_allows_up_to_cap_then_rejects(db_session: AsyncSession) -> None:
    for _ in range(3):
        assert await allow(db_session, "intake:slug-a", max_events=3) is True
    assert await allow(db_session, "intake:slug-a", max_events=3) is False
    # Still rejected on retry — rejection is durable, not a per-process fluke.
    assert await allow(db_session, "intake:slug-a", max_events=3) is False


async def test_keys_are_independent(db_session: AsyncSession) -> None:
    assert await allow(db_session, "intake:slug-a", max_events=1) is True
    assert await allow(db_session, "intake:slug-a", max_events=1) is False
    assert await allow(db_session, "chat:slug-a", max_events=1) is True  # other key unaffected


async def test_events_survive_a_new_session(db_session: AsyncSession) -> None:
    """The whole point of BL-15: the window is in Postgres, so a 'restarted'
    process (fresh session) still sees the consumed budget."""
    assert await allow(db_session, "intake:slug-b", max_events=1) is True
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(RateLimitEvent.key == "intake:slug-b")
        )
    ).scalar_one()
    assert count == 1
    assert await allow(db_session, "intake:slug-b", max_events=1) is False


async def test_expired_events_fall_out_and_are_pruned(db_session: AsyncSession) -> None:
    key = "intake:slug-c"
    assert await allow(db_session, key, max_events=1) is True
    # Age the event past the window (DB clock — the same clock allow() uses).
    await db_session.execute(
        update(RateLimitEvent)
        .where(RateLimitEvent.key == key)
        .values(created_at=func.now() - timedelta(hours=2))
    )
    await db_session.commit()

    assert await allow(db_session, key, max_events=1) is True  # budget refreshed
    # The expired row was pruned opportunistically — only the fresh one remains.
    count = (
        await db_session.execute(
            select(func.count()).select_from(RateLimitEvent).where(RateLimitEvent.key == key)
        )
    ).scalar_one()
    assert count == 1
