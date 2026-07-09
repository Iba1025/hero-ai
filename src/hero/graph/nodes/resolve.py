"""RESOLVE node — fix recommendation + work order."""

from __future__ import annotations

import uuid
from typing import Any


def resolve(state: dict[str, Any]) -> dict[str, Any]:
    """Generate a work order ID. Real impl creates detailed work order."""
    work_order_id = str(uuid.uuid4())
    return {"work_order_id": work_order_id}
