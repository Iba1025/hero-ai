"""Postgres-backed sliding-window rate limiter — P4-4d abuse basics, grown up
(Phase 5 STEP 3, BL-15).

Replaces the in-memory per-process SlidingWindowLimiter: counts now survive
restarts and are shared across workers (the FRICTION.md Phase 5 item). One
rate_limit_event row per allowed event; `allow` counts rows inside the window
on the caller's session, using the DB clock (func.now()) on both sides so app
and DB clocks never mix.

`allow` COMMITS immediately: a request that later fails validation (and rolls
back its session) must still have consumed budget — otherwise rejected
requests would be free retries. Rate gates therefore run before any other
write in a handler.

Honest limitation, deliberate at pilot scale: count-then-insert is not
serialized, so N concurrent requests can each see the window as open and all
pass — overshoot is bounded by in-flight concurrency. Fine for an abuse
basic; a per-key advisory lock would close it if ever needed.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hero.storage.models import RateLimitEvent


async def allow(
    session: AsyncSession, key: str, *, max_events: int, window_seconds: float = 3600.0
) -> bool:
    """True (and one event recorded) until `max_events` land within the window."""
    cutoff = func.now() - timedelta(seconds=window_seconds)

    # Opportunistic prune keeps the journal small — expired rows for this key
    # are dead weight for every future count.
    await session.execute(
        delete(RateLimitEvent).where(RateLimitEvent.key == key, RateLimitEvent.created_at < cutoff)
    )
    count = (
        await session.execute(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(RateLimitEvent.key == key, RateLimitEvent.created_at >= cutoff)
        )
    ).scalar_one()

    if int(count) >= max_events:
        await session.commit()  # persist the prune; nothing else is pending
        return False

    session.add(RateLimitEvent(key=key))
    await session.commit()
    return True
