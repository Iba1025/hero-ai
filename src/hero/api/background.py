"""Background pipeline runs (BL-17/H1).

Intake and clarify-answer handlers return immediately; the graph runs in a
tracked asyncio task owned by the FastAPI lifespan. A tracked set (not an
asyncio.TaskGroup) is deliberate: a TaskGroup cancels every sibling when one
child raises — one failed ticket must never take down in-flight runs. Runner
coroutines catch their own exceptions and stamp pipeline_status='failed'
(hero.api.pipeline), so a task here failing loudly is already a bug.

Shutdown drains: the lifespan awaits in-flight runs before the process exits.
A hard kill mid-run is recovered on next startup from the Postgres checkpointer
(INV-6) — see hero.api.pipeline.recover_orphaned_runs.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """Run a pipeline coroutine in the background, tracked until done."""
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_on_done)
    return task


def _on_done(task: asyncio.Task[Any]) -> None:
    _tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        # Runners handle their own failures; reaching here is a bug — be loud.
        logger.error("Background pipeline task died unhandled", exc_info=task.exception())


async def drain() -> None:
    """Await all in-flight background runs (lifespan shutdown + tests)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


def pending_count() -> int:
    return len(_tasks)
