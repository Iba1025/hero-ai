"""Hazard detection — data + patterns, reviewed like code (spec §9, BL-81).

No LLM imports anywhere in safety/.

INV-15 monotonicity (amended 2026-07-29): any detector may escalate; no
detector may de-escalate. `scan_hazards()` is the deterministic floor — layers
above it (semantic, model-based) may only ever *raise* the hazard signal.

BL-81: the phrase corpus that drives these patterns lives in
`evals/hazard_redteam_cases.py`, generated adversarially per category
(verb/noun inversions, colloquialisms, the sensory description rather than
the substance — mercaptan is odorised to smell of rotten eggs, so a homeowner
who doesn't know the word "gas" says "eggs" — misspellings, and panicked
fragments). `tests/invariants/test_inv15_hazard_recall.py` asserts 100%
must-catch recall per category; `evals/run_hazard_recall.py` reports the
recall numbers. **The pattern list is an output of that suite, not an input
to it**: grow the corpus first, then the patterns until recall is whole.

Direction of change is deliberately one-way (work-order Class A-safe): edits
here may add escalations, never remove them. Precision is the cheap side of
this trade — a false escalation costs a human callback; a miss costs INV-15's
reason to exist.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# Hard-escalation trades (INV-1): always escalate regardless of confidence
HARD_ESCALATE_TRADES: frozenset[str] = frozenset(
    {
        "gas",
        "electrical_high_voltage",
        "structural",
        "water_intrusion",
    }
)

# Legacy literal keywords (pre-BL-81). Kept as the reviewable core vocabulary
# and as a compatibility export — scan_hazards() is a strict superset of this
# list, and the recall suite asserts that property.
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


class HazardHit(NamedTuple):
    """One detected hazard: which category fired, and the text that fired it."""

    category: str
    matched: str


_WORD = r"[\w'\u2019]+"


def _near(a: str, b: str, gap: int = 4) -> str:
    """`a` followed by `b` within `gap` intervening words."""
    return rf"{a}\W+(?:{_WORD}\W+){{0,{gap}}}{b}"


# Token groups. \b-anchored so "gas" never fires inside "gasket".
_SMELL = r"\b(?:sme+l\w*|odou?rs?|stink\w*|reek\w*|scents?|whiffs?)\b"
_GASSY = r"\b(?:gas+y?|propane|methane|sulfur\w*|sulphur\w*|mercaptan|rotten\s+eggs?|eggs?)\b"
_LEAKY = r"\b(?:leak\w*|leek\w*)\b"
_HISS = r"\bhiss\w*\b"
_GAS_CARRIER = r"\b(?:gas|line|pipe|meter|tank|valve)\b"
_ELEC = (
    r"\b(?:outlet|socket|switch|wir(?:e|es|ing)|panel|breaker|fuse\s*box"
    r"|electric\w*|plug|cord|appliance|light\w*)\b"
)
_ELEC_DISTRESS = (
    r"\b(?:shock\w*|zapp?\w*|melt\w*|scorch\w*|charr\w*|burn\w*|buzz\w*"
    r"|sizzl\w*|crackl\w*)\b"
)
_STRUCT_MEMBER = r"\b(?:ceiling|wall|floor|beam|balcony|roof|joist|support\w*|stairs?)\b"
_STRUCT_DISTRESS = (
    r"\b(?:sagg?\w*|bulg\w*|crack\w*|crumbl\w*|buckl\w*|leaning|shift\w*"
    r"|falling|coming\s+down|giving\s+way)\b"
)
_WATERY = r"\b(?:water|wet|leak\w*|drip\w*|flood\w*)\b"

# Per category: literal legacy keywords FIRST (stable reason strings for the
# ledger audit trail), generated patterns after. Order within the dict is the
# scan/report order.
_CATEGORY_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "gas": [
        re.compile(p)
        for p in (
            r"\bgas\s+leak\w*\b",
            r"\bgas\s+smell\w*\b",
            _near(_SMELL, _GASSY),
            _near(_GASSY, _SMELL),
            _near(_GASSY, _LEAKY),
            _near(_LEAKY, _GASSY),
            _near(_HISS, _GAS_CARRIER),
            _near(_GAS_CARRIER, _HISS),
            r"^\W*ga+s+\W*$",  # the panicked fragment: "gas!!"
        )
    ],
    "carbon_monoxide": [
        re.compile(p)
        for p in (
            r"\bcarbon\s+(?:mon|di)oxide\b",
            r"\bco2?\s+(?:alarm|detector)s?\b",
            r"\bmonoxide\b",
        )
    ],
    "electrical": [
        re.compile(p)
        for p in (
            r"\bsparking\b",
            r"\belectrical\s+fire\b",
            r"\bexposed\s+wir\w*\b",
            r"\blive\s+wire\w*\b",
            r"\bhigh\s+voltage\b",
            r"\belectrocut\w*\b",
            r"\bsparks?\b",
            r"\barc(?:ing|ed|s)?\b",
            _near(_ELEC_DISTRESS, _ELEC, 5),
            _near(_ELEC, _ELEC_DISTRESS, 5),
        )
    ],
    "fire_smoke": [
        re.compile(p)
        for p in (
            r"\bsmok(?:e|ing|y|ey)\b",
            r"\bon\s+fire\b",
            r"\bfire\b(?!\s*place)",
            r"\bflames?\b",
            _near(_SMELL, r"\bburn\w*\b"),
            _near(r"\bburn\w*\b", _SMELL),
            r"\b(?:something|smth|sth)\b\W+(?:is\W+)?burn\w*",
        )
    ],
    "structural": [
        re.compile(p)
        for p in (
            r"\bstructural\s+crack\w*\b",
            r"\bfoundation\s+damage\b",
            r"\bload[- ]bearing\b",
            r"\bcollaps\w*\b",
            r"\bcav(?:e|ing|ed)\s+in\b",
            _near(_STRUCT_MEMBER, _STRUCT_DISTRESS),
            _near(_STRUCT_DISTRESS, _STRUCT_MEMBER),
            _near(r"\bfoundation\b", r"\b(?:crack\w*|damag\w*|shift\w*|settl\w*|sink\w*)\b"),
            _near(r"\b(?:crack\w*|damag\w*)\b", r"\bfoundation\b"),
            r"\bstructural\s+(?:damage|issue|problem)\w*\b",
        )
    ],
    "water_sewage": [
        re.compile(p)
        for p in (
            r"\bflooding\b",
            r"\bsewage\s+backup\b",
            r"\bflood\w*\b",
            r"\bsewage\b",
            _near(r"\bsewer\b", r"\bback\w*\b", 2),
            r"\bstanding\s+water\b",
            _near(_WATERY, _ELEC, 6),
            _near(_ELEC, _WATERY, 6),
            _near(r"\bwater\b", r"\b(?:pouring|gushing|cascading|streaming)\b", 3),
            _near(r"\b(?:pouring|gushing|cascading)\b", r"\bwater\b", 3),
        )
    ],
    "hazmat": [
        re.compile(p)
        for p in (
            r"\bmold\b",
            r"\basbestos\b",
            r"\bmou?ld\w*\b",
        )
    ],
    "explosion": [
        re.compile(p)
        for p in (
            r"\bexplosion\b",
            r"\bexplo(?:de|ded|des|ding|sive)\w*\b",
            r"\bblew\s+up\b",
            r"\bboom\b",
        )
    ],
}

HAZARD_CATEGORIES: tuple[str, ...] = tuple(_CATEGORY_PATTERNS)


def scan_hazards(text: str) -> list[HazardHit]:
    """Deterministic hazard scan. Pure function, no LLM, confidence not an input.

    Returns at most one hit per category (the first pattern that fires), in
    category order. Empty list = no hazard detected by this floor — which,
    per INV-15 monotonicity, a layer above may still escalate.
    """
    lowered = text.lower()
    hits: list[HazardHit] = []
    for category, patterns in _CATEGORY_PATTERNS.items():
        for pattern in patterns:
            m = pattern.search(lowered)
            if m:
                hits.append(HazardHit(category=category, matched=m.group(0)))
                break
    return hits


def any_hazard(text: str) -> bool:
    """True if any hazard category fires on `text`."""
    return bool(scan_hazards(text))
