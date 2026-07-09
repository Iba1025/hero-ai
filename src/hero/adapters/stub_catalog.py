"""Stub CatalogResolver — deterministic fake for skeleton testing."""

from __future__ import annotations


class StubCatalogResolver:
    """Returns a fixed SKU for any part need."""

    async def resolve(self, part_need: str, trade: str) -> str | None:
        return f"STUB-SKU-{trade.upper()}-001"
