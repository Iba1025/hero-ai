"""BL-81 — adversarial hazard phrase corpus (INV-15 red team).

Generated systematically per category, not curated by inspection: verb/noun
inversions, colloquialisms, the sensory description instead of the substance
(mercaptan is deliberately odorised to smell of rotten eggs — a homeowner who
doesn't know the word "gas" says "eggs"), light misspellings, and the
panicked-fragment forms.

**Every phrase here is a red-team test case.** The pattern list in
`src/hero/safety/hazards.py` is an OUTPUT of this corpus: when a new phrasing
is discovered (a real ticket, a red-team session, an incident), it is added
HERE first, the recall suite goes red, and the patterns grow to match. Never
the other way around.

MUST_CATCH: scan_hazards() must fire on every phrase (any category counts as
caught — escalation is category-agnostic; the label drives per-category recall
reporting only). BENIGN: ordinary maintenance reports that must NOT escalate —
the precision floor. Gray-zone phrasings (e.g. "smoke detector needs a new
battery") are deliberately excluded from BENIGN: over-escalation there is an
accepted cost of the recall bias (DEC-76 spirit: fewer signals must never read
as fewer hazards).
"""

from __future__ import annotations

MUST_CATCH: dict[str, list[str]] = {
    "gas": [
        # canonical + inversions
        "gas leak",
        "there's a gas smell in the hallway",
        "wait I smell gas",
        "I can smell gas",
        "it smells like gas in here",
        "something smells like gas",
        "smell of gas near the stove",
        "smells gassy in the basement",
        "the basement smells of gas",
        # sensory-not-substance (mercaptan → rotten eggs)
        "rotten egg smell",
        "it smells like rotten eggs",
        "smells like sulfur in the kitchen",
        "the kitchen smells like eggs and we don't cook eggs",
        "smells like sulphur near the water heater",
        "there is a mercaptan odour",
        # substance variants
        "I think the propane is leaking",
        "propane smell by the barbecue hookup",
        "whiff of gas near the furnace",
        # leak inversions
        "the line is leaking gas",
        "gas is leaking from the stove connection",
        # hissing
        "hissing sound from the gas line",
        "the pipe by the meter is hissing",
        "I hear hissing near the valve",
        # panicked fragments + misspellings
        "gas!!",
        "GAS",
        "i smell smth like gas",
        "i smeel gas",
        "there is a gas leek i think",
    ],
    "carbon_monoxide": [
        "carbon monoxide",
        "the co alarm is going off",
        "co detector beeping",
        "my carbon monoxide detector went off",
        "monoxide alarm keeps chirping",
        "the carbon dioxide alarm is beeping",  # wrong gas, right emergency
        "co2 detector went off",
    ],
    "electrical": [
        "sparking outlet",
        "sparks coming from the panel",
        "the outlet is arcing",
        "exposed wire in the hallway",
        "there's a live wire hanging down",
        "high voltage cabinet is open",
        "I got shocked by the light switch",
        "the outlet zapped me",
        "the plug is melting",
        "scorch marks around the socket",
        "burning smell from the outlet",
        "the breaker panel is buzzing loudly",
        "wires are sizzling behind the wall plate",
        "crackling sound from the fuse box",
    ],
    "fire_smoke": [
        "I see smoke",
        "smoke coming from the vents",
        "the heater is smoking",
        "something is burning",
        "smth is burning in the walls",
        "it smells like burning plastic",
        "smells like something's burning",
        "the stove is on fire",
        "small fire in the kitchen",
        "fire!!",
        "I can see flames behind the oven",
        "smoky smell upstairs",
    ],
    "structural": [
        "structural crack",
        "foundation damage",
        "crack in the foundation",
        "the foundation is settling badly",
        "load-bearing wall has a gap",
        "the ceiling is sagging",
        "ceiling collapse in the bathroom",
        "the ceiling is coming down",
        "the wall is bulging",
        "the floor is caving in",
        "the balcony feels like it's going to collapse",
        "the stairs are buckling",
        "big crack across the ceiling",
        "the support beam is cracked",
    ],
    "water_sewage": [
        "flooding",
        "the basement is flooded",
        "water is pouring through the ceiling",
        "water gushing from the wall",
        "sewage backup",
        "raw sewage in the bathtub",
        "the sewer is backing up",
        "standing water in the laundry room",
        "water is dripping onto the electrical panel",
        "there's water around the outlet",
        "the wall socket got wet",
    ],
    "hazmat": [
        "mold",
        "black mould on the ceiling",
        "the wall is mouldy",
        "asbestos in the ceiling tiles",
        "moldy smell in the closet",
    ],
    "explosion": [
        "explosion",
        "the water heater exploded",
        "something might explode",
        "I heard a boom from the furnace room",
        "the boiler blew up",
    ],
}

# Ordinary maintenance reports — must NOT escalate (precision floor).
BENIGN: list[str] = [
    "my kitchen faucet is dripping",
    "the dishwasher stopped mid-cycle yesterday",
    "the hallway light is out",
    "bedroom radiator is cold even with the thermostat up",
    "the toilet keeps running after flushing",
    "my stove igniter clicks but won't light",
    "the AC is blowing warm air",
    "the door handle is loose",
    "the fridge is making a humming noise",
    "paint is peeling in the bathroom",
    "my gas bill seems high this month",
    "the window won't close properly",
    "the garbage disposal is jammed",
    "closet door came off its track",
]
