"""CatalogResolver Protocol — spec §6.

OPEN-1: schema behind interface because catalog source is undecided.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CatalogResolver(Protocol):
    async def resolve(self, part_need: str, trade: str) -> str | None:
        """Resolve a natural-language part need to a catalog SKU."""
        ...
