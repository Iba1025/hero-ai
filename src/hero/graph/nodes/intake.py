"""INTAKE node — ticket + media ingestion.

Presigned upload is client-side; state receives pointers only (INV-3).
Sensor/BMS data, if available, attaches here as optional evidence (INV-7).
"""

from __future__ import annotations

from typing import Any


def intake(state: dict[str, Any]) -> dict[str, Any]:
    """Pass-through: ticket already has description + media refs from API."""
    return {}
