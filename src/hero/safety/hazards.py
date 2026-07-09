"""Hazard keywords/patterns — data file, reviewed like code (spec §9).

No LLM imports anywhere in safety/.
"""

from __future__ import annotations

# Hard-escalation trades (INV-1): always escalate regardless of confidence
HARD_ESCALATE_TRADES: frozenset[str] = frozenset(
    {
        "gas",
        "electrical_high_voltage",
        "structural",
        "water_intrusion",
    }
)

# Hazard keywords that trigger escalation even if trade is not in HARD_ESCALATE_TRADES
HAZARD_KEYWORDS: list[str] = [
    "gas leak",
    "gas smell",
    "carbon monoxide",
    "co detector",
    "co alarm",
    "sparking",
    "electrical fire",
    "exposed wire",
    "live wire",
    "high voltage",
    "electrocution",
    "structural crack",
    "foundation damage",
    "load-bearing",
    "collapse",
    "ceiling collapse",
    "flooding",
    "sewage backup",
    "mold",
    "asbestos",
    "explosion",
]
