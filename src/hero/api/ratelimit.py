"""In-process sliding-window rate limiter — P4-4d abuse basics.

Honest limitations, deliberate at pilot scale: in-memory and per-process, so
counts reset on restart and are not shared across workers. A single uvicorn
serves the pilot; revisit alongside real deployment infra, not before.
"""

from __future__ import annotations

import time
from collections import deque


class SlidingWindowLimiter:
    """allow(key) is True until `max_events` land within `window_seconds`."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}

    def allow(self, key: str, *, max_events: int, window_seconds: float = 3600.0) -> bool:
        now = time.monotonic()
        window = self._events.setdefault(key, deque())
        while window and now - window[0] > window_seconds:
            window.popleft()
        if len(window) >= max_events:
            return False
        window.append(now)
        return True

    def reset(self) -> None:
        """Test hook — clears all windows."""
        self._events.clear()


# Module singleton shared by the public router (single process at pilot scale).
limiter = SlidingWindowLimiter()
