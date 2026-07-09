"""OUTCOME node — capture contractor confirmation (BL-0).

Terminal node. The actual ContractorStatement is written via the API
(POST /outcomes), not by the graph — this node marks the ticket as
ready for outcome capture.
"""

from __future__ import annotations

from typing import Any


def outcome(state: dict[str, Any]) -> dict[str, Any]:
    """Mark ticket as awaiting contractor statement."""
    return {}
