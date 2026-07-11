"""One-shot backfill: stamp triage fields onto ticket rows created before P4-2.

Tickets created before P4-2 have NULL trade/urgency/complexity on the row —
the values live only in graph checkpoint state. This reads each NULL row's
checkpoint (thread `ticket-{id}`) and copies the fields onto the ticket so
list/dashboard views don't look broken.

Run: uv run python -m hero.storage.backfill_triage
Idempotent: only touches rows where trade IS NULL; rows without a checkpoint
are reported and left untouched (honest gap, never invented).
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hero.storage.models import Ticket
from hero.storage.repo import stamp_ticket_triage


async def backfill_triage(session: AsyncSession, graph: Any) -> tuple[int, int]:
    """Stamp triage fields from checkpoint state onto NULL-trade tickets.

    Returns (stamped, skipped) — skipped = no checkpoint state or no triage
    fields in it (e.g. run never reached TRIAGE).
    """
    result = await session.execute(select(Ticket).where(Ticket.trade.is_(None)))
    tickets = list(result.scalars().all())

    stamped = 0
    skipped = 0
    for ticket in tickets:
        config = {"configurable": {"thread_id": f"ticket-{ticket.id}"}}
        state = await graph.aget_state(config)
        values = state.values if state is not None else {}
        if not values or values.get("trade") is None:
            print(f"skip  {ticket.id}  (no checkpoint triage state)")
            skipped += 1
            continue
        await stamp_ticket_triage(
            session,
            ticket.id,
            trade=values.get("trade"),
            urgency=values.get("urgency"),
            complexity=values.get("complexity"),
        )
        print(f"stamp {ticket.id}  trade={values.get('trade')} urgency={values.get('urgency')}")
        stamped += 1
    return stamped, skipped


async def _main() -> None:
    from hero.api.deps import get_graph
    from hero.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    graph = await get_graph()

    async with factory() as session:
        stamped, skipped = await backfill_triage(session, graph)
        await session.commit()
    await engine.dispose()
    print(f"done: {stamped} stamped, {skipped} skipped")


if __name__ == "__main__":
    asyncio.run(_main())
