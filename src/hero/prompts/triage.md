# Triage a building-maintenance ticket

You are triaging a maintenance ticket for a residential/commercial building.
Classify it on three axes. Output JSON only.

## Ticket description

{description}

## Axes

**trade** — exactly one of:
`hvac`, `plumbing`, `electrical`, `appliance`, `structural`, `water_intrusion`, `gas`, `other`

- `gas` covers any mention of gas smell, gas lines, gas appliances' fuel side.
- `water_intrusion` covers water entering the building envelope (roof leaks,
  flooding, foundation seepage) — NOT a leaking fixture, which is `plumbing`.
- When two trades plausibly apply, pick the one a dispatcher would call first.

**urgency** — exactly one of:
- `emergency` — active hazard or major damage in progress (gas smell, sparking,
  flooding, no heat in freezing weather)
- `urgent` — needs attention within a day (active leak, no hot water, no cooling
  in extreme heat)
- `routine` — everything else

**complexity** — exactly one of:
- `simple` — a single, common, well-understood symptom on one fixture or
  component with an obvious fix domain (e.g. a running toilet, a worn washer,
  a clogged filter). No multi-system interaction, no ambiguity about the trade.
- `standard` — a typical diagnostic ticket: clear trade, but the root cause
  needs evidence to pin down.
- `complex` — multiple symptoms, intermittent behavior, plausible multi-trade
  interaction, or a description too vague to scope.

If in doubt between `simple` and `standard`, choose `standard` — `simple`
routes to a reduced retrieval path and must be reserved for obviously
trivial tickets.

## Output format

JSON object, nothing else:

{"trade": "...", "urgency": "...", "complexity": "..."}
