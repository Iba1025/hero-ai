# Hero.AI — Knowledge & Catalogue Architecture

**2026-07-27 · Companion to PRD v8.1**

> **Status:** implementation detail. **The PRD is the index of truth** — if this disagrees, the PRD wins.
> **Governed by:** INV-2, INV-4, INV-9, INV-17, INV-18 · DEC-2/3/10/12/32/34 · new DEC-81..86.

Covers two things: where Twilio and ElevenLabs sit (and their residency problem), and how the
knowledge stores actually work — service catalogues, cross-vendor case history, document ingestion,
and the task→price→contractor resolution.

---

# PART 1 — Telephony and voice vendors

## 1.1 The residency position, stated honestly

| Vendor | Regions offered | Canada? | Verdict |
|---|---|---|---|
| **Twilio** | US1 (default), IE1, AU1 | ❌ **No** | Transit-only, exception recorded |
| **ElevenLabs** | US (default), EU, India — Enterprise only | ❌ **No** | TTS defensible with ZRM; **ASR is not** |

Twilio also warns that during the current Regions rollout it does not guarantee all data remains in
the selected region. ElevenLabs states that even with residency selected, **processing may occur
outside the selected location** via affiliates and subprocessors.

**Neither is INV-2-compliant as written.** The resolution is architectural, not contractual.

## 1.2 Transit, not storage (DEC-81)

The move is to make both vendors carry bytes and store nothing.

**Twilio configuration — mandatory:**
- Message body redaction enabled (Twilio Editions feature)
- Call recording **disabled at the account level**; if recording is ever needed, record to our own
  R2 bucket via media streams, never to Twilio storage
- Media (MMS) fetched immediately and written to R2 (INV-3), Twilio copy deleted
- Edge location pinned closest to Toronto for latency; region remains US1 with the exception recorded
- Webhook receivers verify → enqueue → ack (DEC-57); **the payload is staged before any fallible
  work** (DEC-59)

**ElevenLabs configuration — mandatory if used:**
- Enterprise tier with **Zero Retention Mode**: PII redaction before storage, storage prevention on
  raw audio, restricted logging
- EU residency workspace (closest available; not Canada)
- No voice cloning under any circumstance (DEC-79) — which also removes the biometric-data question
  entirely, since voice samples are Article 9 / biometric material under most readings

## 1.3 The asymmetry that decides the architecture

**TTS and ASR are not the same residency problem, and treating them as one is the mistake.**

| Direction | What crosses the border | Exposure |
|---|---|---|
| **TTS** (agent speaks) | The agent's *outbound* text — templated questions, the business name, a window | **Low.** Constrainable to templates with no ticket specifics interpolated |
| **ASR** (agent listens) | The requester's *actual words* — the fault description, the address, the unit number | **High. This is unambiguously ticket content** |

**Recommendation:**

- **ASR → self-hosted.** Whisper-class, on our own box. Already in the stack. This is the harder
  residency exposure and it is also the one we can eliminate outright.
- **TTS → ElevenLabs ZRM/EU is defensible**, with a hard constraint: **outbound synthesis input is
  templated and carries no requester PII**. Enforce it in code, not in policy — a template renderer
  that rejects unbound interpolation, and a test suite that asserts it.
- **Fallback if that constraint proves unmaintainable:** self-hosted neutral TTS (Piper/Coqui/Kokoro
  class). DEC-79 dropping voice cloning is what makes this viable — we need one good voice, not a
  cloning service.

## 1.4 Where they sit in the flow

```
requester's phone
   │
   ├─ inbound call ──► TWILIO (transit) ──► webhook ──► verify/enqueue/ack (DEC-57)
   │                                                       │
   │                                            media ──► R2 (ours, INV-3)
   │                                            audio ──► SELF-HOSTED ASR ──► transcript
   │                                                                            │
   ├─ SMS ──────────► TWILIO (redacted, transit) ◄──────────────────────────────┤
   │                                                                            │
   │                                              ┌── agent turn (LangGraph) ───┘
   │                                              │
   └─ agent speech ◄─ TWILIO ◄─ ELEVENLABS TTS ◄──┘  (templated input only)
                                   [ZRM, EU workspace]

   Session link, video, photo upload ─────► HERO WEB APP (CA-hosted) ─────► R2 (CA)
```

**Twilio's role is three things and no more:** a phone number, SMS transit, and voice-call transit.
It never holds a transcript, a recording, or a diagnosis.

**Video never touches either vendor** — it goes through our own WebRTC edge to processors, per
DEC-46. Photo upload likewise: presigned direct to R2.

## 1.5 What must be recorded

`docs/residency.md` gains a row per service with: region selected · what data crosses · retention
setting · the mitigation · the date reviewed. The startup guard asserts the config matches.

> ⚠️ This is an **exception to INV-2, not compliance with it.** It must be visible in a procurement
> review, not discovered in one. Pair with the DEC-28 R2 migration — a procurement reviewer will ask
> about both in the same breath.

---

# PART 2 — The knowledge architecture

## 2.1 Three stores, and why they must stay separate (DEC-83)

The most common way this goes wrong is treating it as one big "knowledge base." It's three, with
different owners, different query shapes, and different confidentiality rules.

| # | Store | Contents | Tech | Owner | Answers |
|---|---|---|---|---|---|
| **1** | **Manufacturer knowledge** | Service manuals, install guides, fault-code tables, wiring diagrams, codes | **Qdrant** (multimodal, existing) | Universal — same for everyone | *"What does the manual say about a P3 on a Goodman GSX?"* |
| **2** | **Vendor service catalogue** | What this company does and charges | **Postgres** | **The vendor** (confidential) | *"What does New Toronto Electric charge to swap a condensate pump?"* |
| **3** | **Case history** | Every past problem → what it actually was → what fixed it → what it cost | **Postgres + Qdrant** | **Hero, de-identified** (§10.1 clause) | *"What actually turned out to be wrong the last 47 times we saw this?"* |

**RAG vs SQL, stated plainly:**

- **RAG (Qdrant)** answers *"what is similar to this?"* — unstructured, semantic, fuzzy. Manual pages
  and case narratives.
- **SQL (Postgres)** answers *"what exactly, how many, how much, who's eligible?"* — exact lookup,
  hard constraints, aggregation, joins.

You retrieve by similarity and then aggregate by exact join. Neither alone is sufficient. A vector
store cannot tell you a median price or filter on insurance expiry; a relational store cannot tell
you which manual page depicts this wiring configuration.

## 2.2 The crux: a canonical task taxonomy (DEC-82)

**Nothing compounds without this.** It is the single most important schema decision in the document.

The problem: three vendors describe the same job three ways.

```
Vendor A:  "Condensate pump replacement"
Vendor B:  "Cond pump R&R"
Vendor C:  "Replace drain pump — AC"
```

Without normalization those are three unrelated rows. No price band. No cross-vendor learning. No
contractor matching. The case history never compounds because nothing joins.

**The fix is a chart of accounts for trade work.**

```
task_taxonomy
  task_code          TEXT PK   -- HVAC.COND.PUMP.REPLACE
  trade                        -- hvac | electrical | plumbing | appliance
  system                       -- condensate management
  component                    -- pump
  action                       -- replace | repair | clean | inspect | test | diagnose
  description
  typical_minutes_min/max
  hazard_class                 -- feeds INV-1 gating
  requires_licence_class
  parent_task_code             -- hierarchy for rollups
```

Format: `TRADE.SYSTEM.COMPONENT.ACTION`

```
HVAC.COND.PUMP.REPLACE
HVAC.REFRIG.CAPACITOR.REPLACE
HVAC.IGNITION.FLAMESENSOR.CLEAN
PLMB.DRAIN.MAIN.CLEAR
PLMB.FIXTURE.TOILET.FILLVALVE.REPLACE
ELEC.PANEL.BREAKER.REPLACE
ELEC.DEVICE.GFCI.REPLACE
```

**Seeding.** Don't try to build it exhaustively. Roughly **200 task codes cover most residential HVAC
service**. Seed from the manual corpus procedures plus the first two or three vendor catalogues, then
grow from ingestion. Start HVAC-only, per DEC-43's trade priority.

**Growth rule:** the taxonomy grows through review, never through inference. A mapper that can invent
codes produces a taxonomy that doesn't join — the same failure mode as a model inventing part
numbers (INV-9). Unmatched lines go to a proposal queue.

## 2.3 The vendor catalogue

```sql
vendor_catalog_item
  id, vendor_id, network_id
  task_code            REFERENCES task_taxonomy   -- THE JOIN KEY
  vendor_sku           TEXT      -- their own code, if they have one
  vendor_label         TEXT      -- their own words, preserved verbatim
  price_type           TEXT      -- flat | hourly | band | quote_only
  price_amount         NUMERIC
  price_min, price_max NUMERIC   -- for band
  labour_minutes       INT
  includes_parts       BOOL
  source               TEXT      -- stated | imported_csv | inferred_from_invoice | inferred_from_quote
  confidence           NUMERIC   -- lower for inferred
  observed_at          TIMESTAMPTZ  -- DECAY
  superseded_by        UUID      -- accumulate, never overwrite
```

Three things worth noting:

**`source` matters.** A price the contractor stated is stronger evidence than one parsed from an
invoice line. Rank accordingly, and show the contractor what we inferred so they can correct it —
every correction is a label.

**Accumulate, never overwrite.** Same pattern as `party_attribute`. Price history is signal: it tells
you volatility per task, which tells you how fast the band decays.

**Decay is mandatory.** Shane: *"It's very up and down... as soon as the prices go up, you also need
to adjust the quoting prices."* A price captured in January misleads by June. Every band carries an
`observed_at` and a confidence that decays; a quarterly one-question SMS refreshes the ones that
matter.

## 2.4 Case history — the compounding store

```sql
case_record
  id, ticket_id, network_id
  -- presentation (what we knew going in)
  presenting_symptoms  JSONB    -- structured from the interview
  symptom_narrative    TEXT     -- free text → VECTORIZED
  equipment_id         UUID     -- make/model/serial
  site_type, client_class, season, region
  -- prediction (what we said)
  diagnosis_id, predicted_task_codes TEXT[], predicted_band
  -- truth (what it was)  ← THE LABEL
  contractor_statement_id
  actual_task_codes    TEXT[]
  actual_parts         TEXT[]   -- free text is fine; normalization is later
  actual_cost, actual_hours
  resolved_on_first_visit BOOL
  -- provenance
  captured_at, source  -- live_ticket | ingested_invoice | ingested_workorder
```

**Vectorized separately in Qdrant:**

```
collection: case_narratives
  vector: embedding(symptom_narrative + equipment_model + site_type)
  payload: {case_id, network_id, trade, actual_task_codes, equipment_model,
            resolved_on_first_visit, de_identified: bool}
```

**The two-step retrieval that makes this work:**

1. **Qdrant** — *"find cases whose presenting narrative resembles this one"* → 50 case IDs
2. **Postgres** — *"for those 50, what were the actual outcomes, costs, hours, first-visit-fix rate?"*
   → a distribution, not an anecdote

Step 2 is where the value is. Similarity finds candidates; aggregation turns them into a prior.

## 2.5 Federation and confidentiality — build it in at migration 1 (DEC-86)

This is contractual, not just technical (§10.1's data clause), and it cannot be retrofitted.

| Data | Owner | Crosses networks? |
|---|---|---|
| Vendor's specific prices | **Vendor** | ❌ Never |
| Customer identity, address, contact | **Vendor / coordinator** | ❌ Never |
| Symptom → actual fault mapping | **Hero, de-identified** | ✅ Yes |
| Task duration and first-fix rates | **Hero, aggregate** | ✅ Yes |
| Price **bands** (aggregate, ≥5 vendors, no attribution) | **Hero, aggregate** | ✅ Yes |
| Vendor performance metrics | **Hero, de-identified** | ✅ Yes (this is the §10.1 clause) |

Mechanism: `network_id` on every row · a de-identification pass before a case enters the cross-network
vector pool (strip addresses, names, phone numbers, unit identifiers from the narrative) · **a
k-anonymity floor on bands** — never compute a band from fewer than 5 vendors, or you've published one
contractor's pricing to their competitor.

## 2.6 Document ingestion — how vendor history becomes schema (DEC-84)

The pipeline that turns a shoebox of PDFs into structured catalogue and case history.

```
① INGEST      PDF / image / CSV / FSM export → R2, staged row first (DEC-59)
② CLASSIFY    invoice | quote | work order | price book | service agreement
③ EXTRACT     line items — description, qty, unit price, total, labour hours
④ MAP         each line → task_code                    ← the hard step
⑤ REVIEW      low-confidence mappings → human queue    ← every correction is a label
⑥ WRITE       vendor_catalog_item + case_record
```

**Step ③ is a visual problem, not a text one.** Invoice layouts vary wildly — tables, multi-column,
handwriting, logos. **This is the same problem shape as the manual corpus, so ColQwen already helps.**
Don't build a separate OCR pipeline; reuse the page-as-image approach.

**Step ④ is entity resolution**, in strict order:

1. **Exact match** against a learned mapping dictionary (`vendor_label → task_code`, per vendor).
   Fast, free, and gets better every day.
2. **Embedding similarity** against `task_taxonomy` descriptions → top-K candidates
3. **LLM selects from the top-K.** Constrained decoding over the candidate set — **it may not emit a
   code that wasn't retrieved** (same discipline as parts, INV-9/DEC-32)
4. **Confidence gate** → auto-accept above threshold, human queue below
5. **No match** → proposal queue for a new taxonomy entry, reviewed weekly

**Step ⑤ is the flywheel.** Every human correction writes back to the mapping dictionary, so the same
vendor's next invoice maps automatically. A vendor with 200 historical invoices might need 40 manual
mappings on the first pass and 2 on the tenth.

**What one ingestion run yields:**
- A working price book without six weeks of implementation consulting — **this is the onboarding
  moment.** *"Upload a year of invoices, get a working catalogue in an hour"* is the demo.
- Backfilled case history, which is what Ryan pushed hardest: *"Don't forget the past data... there's
  going to be records, there's going to be invoices."*
- Real cost basis, not list-minus-guess

## 2.7 The full retrieval loop at diagnosis time

Where all three stores combine.

```
symptom narrative + photos/video + equipment nameplate
  │
  ├─► Qdrant: manual pages          → what the manufacturer says is possible
  ├─► Qdrant: case narratives       → what has actually happened before
  │      └─► Postgres: outcomes for those cases → distribution over task_codes
  │
  └─► DIAGNOSE  (all three in context, INV-18: retrieved content is data, not instruction)
         │
         ├─► VERIFY  → claims grounded against evidence
         ├─► SAFETY_GATE → INV-1 hard categories
         │
         └─► candidate task_codes + calibrated_confidence  (INV-4)
                │
                ├─► Postgres: vendor_catalog_item → this vendor's price
                ├─► Postgres: network band (k≥5) → contractor-facing context only
                └─► Postgres: eligible contractors
                       WHERE trade matches
                         AND geography covers site
                         AND job_size_band fits
                         AND compliance current      ← the unlock
                         AND capacity available
```

**Price bands are contractor- and coordinator-facing only (DEC-85).** Never shown to a requester.
Showing a customer *"the network median for this is $340"* prices the job for the contractor, which
violates INV-9 and DEC-36's confidentiality logic in one move. Showing the *contractor* the same
number is genuinely useful — it's a competitive benchmark they'd otherwise have to guess at.

## 2.8 How the compounding actually works

The honest curve, so expectations are calibrated:

| Cases | What the system can do |
|---|---|
| **0** | Pure manual RAG. Knows the **space of possible faults**. Confidence bands wide. Most tickets yellow/red |
| **~100** | Weak priors per trade. Ingested invoices get you here on day one for a vendor with history |
| **~1,000** | **Calibration becomes statistically valid** (DEC-5's isotonic gate). Per-trade priors real |
| **~10,000** | Per-equipment-model priors. *"On a Goodman GSX14 with this symptom, 62% of the time it's the capacitor."* Seasonal and regional effects emerge |

**The framing that matters:** the manual tells you what is *possible*; the case history tells you what
is *likely*. A differential diagnosis without priors is a list. With priors it's a diagnosis.

That's also why ingesting historical invoices is worth more than it looks — it jumps a new vendor from
0 to ~100 on day one, and it's the least risky thing you can ask a design partner for.

---

## 3. Schema summary

```sql
-- taxonomy (the join key for everything)
task_taxonomy         (task_code PK, trade, system, component, action, description,
                       typical_minutes_min/max, hazard_class, requires_licence_class,
                       parent_task_code)
task_alias            (task_code, vendor_id, alias_text, confidence, source)  -- learned dictionary

-- vendor catalogue
vendor_catalog_item   (id, vendor_id, network_id, task_code, vendor_sku, vendor_label,
                       price_type, price_amount, price_min, price_max, labour_minutes,
                       includes_parts, source, confidence, observed_at, superseded_by)

-- case history (the flywheel)
case_record           (id, ticket_id, network_id, presenting_symptoms JSONB,
                       symptom_narrative, equipment_id, site_type, client_class, season,
                       region, diagnosis_id, predicted_task_codes[], predicted_band,
                       contractor_statement_id, actual_task_codes[], actual_parts[],
                       actual_cost, actual_hours, resolved_on_first_visit,
                       captured_at, source, de_identified_at)

-- ingestion
source_document       (id, vendor_id, network_id, kind, object_key, ingested_at,
                       classified_as, page_count, status)
document_line         (id, source_document_id, line_no, raw_text, qty, unit_price, total,
                       mapped_task_code, map_confidence, map_method, reviewed_by, reviewed_at)

-- pricing
price_band            (task_code, region, trade, p25, p50, p75, sample_size,
                       computed_at)          -- CHECK (sample_size >= 5)  ← k-anonymity floor
```

**Qdrant collections:**

| Collection | Vector of | Payload | Scope |
|---|---|---|---|
| `manuals` | manual page image (ColQwen multivector) | doc_class, make, model, trade, page | Universal |
| `case_narratives` | symptom narrative + equipment + site type | case_id, network_id, trade, actual_task_codes, model | De-identified, cross-network |
| `task_descriptions` | taxonomy description | task_code, trade | Universal — powers the ingestion mapper |

---

## 4. Backlog

| ID | Item | Effort | Why |
|---|---|---|---|
| **BL-65** | **`task_taxonomy` + seed (HVAC first, ~200 codes) + `task_alias`** | ~2 wk | **Nothing compounds without it.** Migration-1 shaped — it's the join key for catalogue, cases, pricing, and matching |
| **BL-66** | `vendor_catalog_item` + CSV/FSM import + decay | ~1 wk | Solves the pricebook cold start; needed for pricing posture |
| **BL-67** | **Document ingestion pipeline** (①–⑥), ColQwen reuse, human review queue | ~3 wk | *"Upload a year of invoices, get a working catalogue in an hour."* The onboarding demo, and the day-one case backfill |
| **BL-68** | `case_record` + `case_narratives` collection + de-identification pass | ~2 wk | The compounding store. Blocked on BL-65 |
| **BL-69** | `price_band` computation with k≥5 floor + decay | ~1 wk | Contractor-facing benchmark; blocked on BL-66 |
| **BL-70** | Task → eligible-contractor resolution (joins registry + compliance + capacity) | ~1 wk | Closes the loop from diagnosis to dispatch. Blocked on BL-21 |
| **BL-71** | Twilio transit config + redaction + R2 media handoff + residency record | ~1 wk | Prerequisite for any SMS/voice channel |
| **BL-72** | Self-hosted ASR + templated-TTS constraint with enforcing tests | ~2 wk | Removes the larger half of the voice residency exposure |

**Order:** BL-65 → BL-66 → BL-67 → BL-68 → BL-69. The taxonomy first, always. Everything else joins
through it, and retrofitting a join key across a populated catalogue and case history is the kind of
migration that eats a month.
