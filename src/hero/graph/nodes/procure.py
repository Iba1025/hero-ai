"""PROCURE node — NL part need → catalog SKU.

Uses CatalogResolver Protocol only (OPEN-1: catalog source undecided).
"""

from __future__ import annotations

from typing import Any

from hero.interfaces.catalog import CatalogResolver


def make_procure(catalog: CatalogResolver) -> Any:
    """Factory that returns a procure node with injected catalog resolver."""

    async def procure(state: dict[str, Any]) -> dict[str, Any]:
        trade = state.get("trade", "other")
        hypotheses = state.get("hypotheses", [])

        part_need = "replacement part"
        if hypotheses:
            fault = hypotheses[0].get("fault", "")
            part_need = f"part for: {fault}"

        sku = await catalog.resolve(part_need, trade)
        return {"sku": sku}

    return procure
