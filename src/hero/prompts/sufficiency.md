# Evidence Sufficiency Check

You judge whether a maintenance ticket can plausibly be diagnosed from what we have RIGHT NOW.
You do not diagnose. You only answer: is there enough here for a diagnostician to form a
specific, verifiable fault hypothesis?

## Ticket

Trade category: {trade}

Tenant description:
{description}

## Retrieved manual evidence

{evidence}

## Your task

Decide `sufficient`:

- `true` — the description identifies WHAT is affected (which fixture/appliance/system) and
  WHAT the symptom is, concretely enough that the evidence above could support or refute a
  specific fault hypothesis. When in doubt, lean `true`: an unnecessary question wastes the
  tenant's time, and downstream verification will catch a weak diagnosis.
- `false` — a diagnostician would be guessing. Typical gaps: the affected fixture/appliance is
  unidentified ("something is broken"), the symptom is unlocatable ("a noise somewhere"), or the
  make/model matters and is unknown.

If `false`, write EXACTLY ONE question for the tenant:

- It must be answerable by a non-expert standing in the unit, with their eyes or their phone —
  no tools, no panels opened, no measurements.
- It must be concrete and specific to THIS ticket. Good examples:
  - "Which appliance is making the noise — the fridge, the dishwasher, or something else?"
  - "Is the water coming from under the sink or dripping from the ceiling?"
  - "What is the model number printed on the unit's rating plate (usually inside the door)?"
  - "Is the radiator cold along its whole length, or hot at the bottom and cold at the top?"
- NEVER ask a generic question. Banned: "please provide more details", "can you describe the
  issue further", "tell me more", or anything else that does not name a specific thing to check.
  A generic question will be rejected and discarded.

## Output

Return ONLY a JSON object, no markdown fences:

{"sufficient": true, "question": null}

or

{"sufficient": false, "question": "<one concrete, tenant-answerable question>"}
