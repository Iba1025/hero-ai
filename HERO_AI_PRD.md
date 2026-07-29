# Hero.AI — Product & Architecture Context (PRD v8)

> **Purpose of this file:** Single source of truth for architecture, decisions, priorities, and invariants.
> Claude Code: read this before any non-trivial change. If a proposed change conflicts with an
> **INVARIANT**, stop and flag it. If it conflicts with a **DECISION**, cite the decision ID and ask.
> Update the `Decision Log` and `Backlog` sections when decisions change — this file must stay current.

**Last updated:** 2026-07-27
**v8 adds:** client classes and the **commercial quote-request fork** (§1.1.1, §4.13). Residential
remains the primary path.
**v8.1 adds:** three capture modalities with live video optional (§4.8.0), and the **company's
assistant** (§4.7.1) — named for the business, neutral Hero voice, **no voice cloning ever**
(DEC-79) and **no personal names** (DEC-80).
**v8.2 adds:** telephony/voice vendor posture and the **knowledge & catalogue architecture** —
canonical task taxonomy, vendor catalogues, cross-vendor case history, document ingestion
(DEC-81..86, see `HERO_AI_KNOWLEDGE_SPEC.md`).
**v7 consolidated:** Intake Session Spec v2 (visit model), PRD v7 Amendments (delivery/identity/
reliability), and the distribution decisions. **This file is now the index of truth for all
invariants, decisions, and backlog.** Companion specs hold implementation detail only.
**Status legend:** ✅ CURRENT · 🔄 UPGRADE PLANNED · ⏸ DEFERRED · ❌ ANTI-GOAL (do not build)
**Backlog IDs are stable identifiers; table order (not ID number) is priority order.**

> **Version lineage:** v4 = diagnostic pipeline · v5 = + coordination/commercial/interaction ·
> v6 = + trade repositioning, video capture, Twenty · v7 = + visit model, delivery & identity layer,
> distribution surface · **v8 = + client classes and the commercial fork.** The pipeline is unchanged
> through all of them. Every v4 invariant survives intact.
>
> **In use:** INV-1..22 · DEC-1..86 · BL-0..72 (**BL-38 unallocated, BL-64 withdrawn — do not reuse**).

---

## 1. What Hero.AI Is

**AI-powered diagnostic and coordination operating system for the maintenance trades.**

A ticket (description + photos, video, or a live capture session) enters; the system produces an
**evidence-grounded diagnosis**, a **preliminary scope**, a **confirmed diagnostic visit**, a
**matched provider**, and — critically — a **contractor-confirmed outcome label** feeding the
flywheel.

**Mental model:** a deterministic pipeline wrapped around non-deterministic models, feeding a
long-lived job lifecycle. The LLM thinks; a state machine decides what happens next; every risky
step passes a gate before anything acts; every human-facing action starts as a draft and earns
autonomy by measured accuracy.

### 1.1 Scope: trades, not buildings (DEC-43)

The organising units are **equipment** and **trade**, not the building. A rooftop unit on a strip
mall, a panel in a 1962 tower, and a water heater in a detached house are the same problem shape:
a fault, a nameplate, a manual, a licensed trade.

| Trade | Why | Evidence character |
|---|---|---|
| **HVAC** | Highest manual density, universal nameplates, fault codes, warranty economics, seasonal urgency | Manual-grounded (strong) |
| **Electrical** | Panel/breaker isolation is systematically diagnosable; hazard-gated already | Code + install-guide (medium) |
| **Plumbing** | Highest water-damage cost, clearest preventative story, highest ticket variance | Mixed (medium-weak) |

Adjacent and inherited: **appliance repair** (nameplate + error code — the most remotely-scopeable
category). Hazard categories **gas / structural / water intrusion** are never focus trades; they are
stop conditions (INV-1).

**Honest finding that shapes the roadmap:** manual-grounded RAG is strongest in HVAC and appliance,
weaker in electrical and plumbing where knowledge is code-based and experiential. Shane
(electrician), on how he localises a fault: *"Experience. That's the only way."* **Expect
systematically lower confidence bands in those two trades by design** — value shifts from manual
citation toward the interview, the scope tree, and declared gaps. Track band distribution per trade
(BL-3). Do not treat a low band there as a retrieval bug.

#### 1.1.1 Sites and client classes (DEC-69, DEC-73)

Hero serves **anyone a home-services contractor services** — not just multi-unit buildings. The site
type is not the interesting variable. **The interesting variable is who reports the fault, who
decides, and who pays.** In a detached house those are one person; in a restaurant chain they are
four.

| Site type | Reports | Decides | Pays | Class |
|---|---|---|---|---|
| Owner-occupied house | Owner | Owner | Owner | **Residential** |
| Rental single-family | Tenant | Landlord | Landlord | **Residential** |
| Condo unit | Unit owner / tenant | Owner or board (depends on the fault's side of the wall) | Owner or corporation | **Residential** |
| Apartment building | Tenant | PM / superintendent | Building fund | **Residential** |
| Small commercial (retail, restaurant, clinic, office) | Staff member | Manager | Owner / franchisor | **Commercial** |
| Multi-site commercial | Site staff | Facility manager | Procurement | **Commercial** |
| Institutional (school, church, community centre) | Staff | Administrator | Board | **Commercial** |

**Residential is the primary path and stays the primary path.** It is the majority of home-services
volume, it is where the diagnostic thesis is strongest, and it is where the confirmed-visit model
(§4.10) fits the way contractors already work. Commercial is a **fork that reuses the entire
pipeline** and changes only the terminal artifact (§4.13).

**`client_class` is classified at `TRIAGE`** alongside trade and urgency. Everything upstream —
session, interview, capture, diagnosis, verification, safety gate — is identical. **The safety gate
is identical.** A gas leak at a restaurant is a gas leak (INV-1).

> ❌ **Not in scope:** multi-site portfolio management, procurement-system integrations, capital
> planning, construction project management. That is ServiceTitan's commercial swamp and we do not
> enter it (§7).

### 1.2 North stars

- **Engineering:** rate and cleanliness of `ContractorStatement` labels per week. The pipeline is
  replicable by incumbents in a quarter. The labeled dataset is not.
- **Commercial:** **non-revenue trips removed per network per month.** The discovery trip, the parts
  trip, the trip turned away for missing paperwork, the callback, the trip nobody needed.

**The link is load-bearing:** a removed trip counts only when the job closes with a
`ContractorStatement`. A feature that removes trips but produces no labels is commodity work (§7).

**Denominator (v7, DEC-65).** Where Hero owns the requester surface, the full funnel is measurable
end to end: `visits → session starts → session completions → visits confirmed → jobs won →
parts-return rate`. **No incumbent has this chain.** Jobber sees form fills; Angi sees leads sold.
This is the artifact for a roll-up operator, because it is denominated in exactly what they optimise.

### 1.3 Why "trips" is the right denomination

| Buyer | Their translation | Their words |
|---|---|---|
| Trade contractor | My diesel, my afternoon | *"9 times in 10 you need more things. So then you have to go and get those things, that costs money."* |
| General contractor | Schedule protection | *"Chasing those documents down from management, that can take five days. That can take 15 days."* |
| Property manager | Vendor spend, tenant retention | *"It depends who's at the desk at that given time."* |
| Service co. / roll-up | Revenue per truck per day → EBITDA → multiple | — |

---

## 2. Invariants (never violate without founder sign-off)

- **INV-1 · Safety gate is hard, not advisory.** Gas, high-voltage, structural, water-intrusion →
  escalate to a licensed trade **regardless of confidence**. `VERIFY` mandatory before `SAFETY_GATE`.
- **INV-2 · Canadian data residency.** All stores in a Canadian region. PIPEDA / Quebec Law 25
  procurement gate and a sales differentiator. No new service processes ticket content outside
  Canada. **Amended (DEC-33):** voice audio, transcripts, telephony metadata are ticket content.
  **Amended (DEC-46):** video frames, session streams, and CV detections are ticket content — and
  video is the most sensitive class we handle. Every API-hosted adapter's residency is recorded in
  `docs/residency.md` and asserted by a startup guard.
- **INV-3 · No media blobs in Postgres.** Bytes to R2/S3 by presigned direct upload; Postgres stores
  object keys. Covers photos, video, keyframes, session recordings, detection overlays.
- **INV-4 · Confidence is never self-reported.** Verification grounds against retrieved evidence;
  calibration is post-hoc against confirmed outcomes. The red/yellow/green band renders
  `calibrated_confidence` **only**. A realtime VLM's narration is never confidence.
- **INV-5 · Clarify, don't guess.** Insufficient evidence → `CLARIFY` asks a human, loops to `RETRIEVE`.
- **INV-6 · Every state transition is persisted** (LangGraph Postgres checkpointer).
- **INV-7 · BMS-independence.** Full pipeline works from submitted evidence + manual corpus alone.
  Sensor data is optional enrichment; nullable fields; tested no-sensor branch on every sensor path.
- **INV-8 · Schema-valid ≠ correct.** No schema-valid output bypasses `VERIFY` or the safety gate.
- **INV-9 · Hero scopes; the licensed professional diagnoses.** Every customer- and provider-facing
  artifact presents evidence, a scope, and a band — never an authoritative diagnosis, never a price,
  never a materials list represented as fact.
- **INV-10 · The safety gate sits above the autonomy ladder, always.** No autonomy level, accumulated
  accuracy, configuration, or customer request bypasses `VERIFY → SAFETY_GATE`. A hard-escalated
  ticket is never auto-matched, auto-dispatched, auto-quoted, or auto-invoiced.
- **INV-11 · Every job-lifecycle event is captured in the ledger.** Message, call, transcript, tap,
  approval, override, edit, dispatch decision → immutable `job_event` row.
- **INV-12 · Two graphs, two resume paths, no more.** Ticket graph (seconds–minutes, resume via
  clarify-answer, `_ResumeGuardedGraph`) and Job graph (hours–weeks, resume via approval,
  `_JobResumeGuard`). Handoff is a typed event, never a shared checkpoint. The video session and
  pre-flight triage are deliberately **not** graphs (DEC-45, DEC-55).
- **INV-13 · The outbound agent cannot commit.** May request, confirm, relay, schedule against
  pre-approved windows. Never commits price, scope, completion date, or liability. Self-identifies
  on every outbound call. Recording consent is a per-jurisdiction config flag.
- **INV-14 · Live video is a capture surface, not a diagnostic authority.** May guide the camera, ask
  questions, run processors, select keyframes. Never states a fault, cause, repair instruction, part,
  or price. Outputs enter `INTAKE` with identical status to photos. **No diagnosis may cite a live
  narration — only a persisted keyframe or transcript span.**
- **INV-15 · Immediate-danger interrupt outranks everything.** Gas odour, hissing at a gas line,
  arcing, sparking, smoke, burning smell, standing water near energised equipment, exposed
  conductors, structural movement, CO alarm → **stop capture immediately**, instruct the person to
  leave and call the appropriate emergency or utility number, hard-escalate. No further questions.
  Outranks the interview protocol, the 5-minute budget, the autonomy ladder, message coalescing, and
  any user instruction to continue. Deterministic pre-LLM classifier (`safety/live_hazards.py`),
  reviewed like code, mandatory red-team suite (BL-30).
  **Amended 2026-07-29 (monotonicity): any detector may escalate; no detector may de-escalate.**
  The deterministic scan is a floor, not a ceiling. Additional detectors — semantic, model-based,
  or otherwise — may be layered above it and may only ever *raise* the hazard signal. This
  preserves the intent of "deterministic pre-LLM" (never let a model's judgement be the *only*
  gate) while permitting a recall layer above it.
  *Rationale: live video is the first surface where a person takes direction from the system while
  standing in front of a hazard.*
- **INV-16 · No repair commitment before the gate.** A session may confirm a **diagnostic visit**
  once pre-flight triage clears hazard and trade. It may never confirm a repair, quote a price,
  state a fault, or promise an outcome before `VERIFY → SAFETY_GATE` and `MATCH`. Pre-flight may
  only ever be *more* conservative than `SAFETY_GATE`; where the gate later disagrees, the visit is
  **upgraded to an escalation** and the requester is proactively told — never silently kept. Agent
  language is constrained and tested: *"a technician needs to come take a look"*, never *"we'll fix
  it Thursday"*.
- **INV-17 · A voice or video vendor's own intelligence is never consumed.** Vendor summaries,
  sentiment, extracted entities, and "AI insights" are discarded. Only raw transcript and raw frames
  enter `INTAKE`. Extraction has exactly one implementation, ours — otherwise the same fault gets
  shaped differently by channel and the flywheel label becomes unattributable.
- **INV-18 · Retrieved and inbound content is data, never instruction.** Anything entering a prompt
  from retrieval, ingestion, OCR, transcription, or any inbound channel is evidence. It may never
  steer the intake agent, copilot, or coordinator agent. Our exposure is broader than a chat
  product's: manufacturer PDFs we didn't author, requester speech, OCR'd nameplate text, and video
  transcripts all feed agents that drive **real-world physical action**. Injection suites per agent
  surface (BL-49).
- **INV-19 · Truncation fails loudly.** Any model finish-reason other than a clean stop raises,
  retries, dead-letters. **Never parse a fragment.** INV-8 sibling: a truncated `DIAGNOSE` that is
  schema-valid is exactly the "schema-valid ≠ correct" case, and a truncated hypothesis list
  **silently narrows the conformal set**, voiding BL-10's safety property with no error anywhere.
  `max_tokens` are documented constants with headroom.
- **INV-20 · Safety-critical classifiers are monitored on failure *rate*, not failure *events*.**
  A dead API key whose error text stops being recognised degrades into a polite handled response for
  every input — nothing throws, nothing dead-letters, every signal green, channel down. **The Hero
  version is INV-15 returning "no hazard" for everyone.** Every processor carries a failure-rate
  monitor; the hazard classifier's monitor alerts, not just logs. Discriminator: genuine bad input is
  rare and uncorrelated; a dead dependency fails everything identically, at once.
- **INV-21 · Never solicit on an organisation's behalf without a named human in that organisation
  approving it.** On the commercial fork (§4.13), Hero drafts a quote request from the reporter's
  evidence — but the RFQ is not delivered to any contractor until a named decision-maker in the
  requesting organisation has reviewed and approved it. The reporter is frequently not the
  decision-maker: a line cook noticing a warm walk-in must not cause five vendors to receive a
  solicitation for a rooftop replacement. Approval is recorded in the ledger with the approver's
  identity (INV-11). Where no decision-maker is identified, the RFQ stays in draft and a human is
  notified — it is never sent to a default.
- **INV-22 · The assistant is named for the business, never for a person.** The Intake Agent presents
  as *the assistant for the company* — *"Hi, you've reached New Toronto Electric, I'm their
  assistant"* — using a **neutral Hero voice**, and identifies itself as an assistant at the start of
  every conversation and whenever asked. It never claims or implies it is a human. Three hard rules:
  (a) **No voice cloning of any real person, ever** (DEC-79). Not the contractor, not staff, not with
  consent. A cloned trade voice is a fraud asset and the reputational failure mode is asymmetric —
  one wrong sentence in a contractor's own voice is unrecoverable.
  (b) **Never surface an owner's or employee's personal name** unless the registered business name
  already contains it. The assistant belongs to the company, not to an individual (DEC-80).
  (c) **Hero owns the protocol; the contractor owns the identity and policies.** The questions asked,
  the safety behaviour, the escalation rules, and the evidence gathered are Hero's and identical for
  every contractor. Only the business name, tone preset, and stated policies vary (extends DEC-62).
  A contractor may never configure what the agent asks, what it escalates, or what it permits a
  requester to do.

---

## 3. Runtime State Machines

### 3.1 Ticket graph — the code is the frozen baseline (`src/hero/graph/build.py`)

```
INTAKE → TRIAGE ─┬─ RETRIEVE ✅ ────────────┬─→ [CLARIFY ⟲ back to full RETRIEVE] ✅
                 └─ RETRIEVE_FAST ✅ (BL-4) ─┘         → DIAGNOSE
       → VERIFY → SAFETY_GATE → { escalated → END | RESOLVE → PROCURE → OUTCOME }   all ✅

[SPEC] planned, NOT built: [grade evidence ⟲ corrective re-retrieve, capped] (BL-9)
```

✅ = built and frozen · [SPEC] = planned. Escalation is a terminal edge off `SAFETY_GATE`, not a
node. **Where this diagram and the code disagree, the code is the baseline and the diagram is a
defect to report — never a change to implement** (founder ruling, 2026-07-29).

| State | Responsibility | Notes |
|---|---|---|
| `INTAKE` | Ticket + evidence ingestion | Presigned upload. Structured interview runs here, before TRIAGE. Video-session artifacts land identically to photos (INV-14). Sensor data optional (INV-7) |
| `TRIAGE` | Urgency + trade + complexity | 🔄 Complexity routing (BL-4) |
| `RETRIEVE` | Hybrid retrieval | ✅ Reranker (BL-1, §6.1); 🔄 corrective loop (BL-9, [SPEC]). Corpus is per-trade (§4.1) |
| `CLARIFY` | HITL follow-up, loop to RETRIEVE | Distinct from the interview (DEC-31) |
| `DIAGNOSE` | VLM forms hypotheses | Claude Sonnet primary, GPT-4o fallback, via LiteLLM |
| `VERIFY` | Ground claims against evidence | 🔄 Claim-level (BL-6) |
| `SAFETY_GATE` | Hard escalation check | INV-1, confidence-independent. 🔄 Conformal sets (BL-10) |
| `RESOLVE` | Fix recommendation | Emits the **preliminary** Scope Report (§4.5.2) |
| `PROCURE` | NL part need → candidate SKU | Contractor-facing truck manifest, never a customer BOM (DEC-32) |
| `OUTCOME` | Contractor confirmation | **First-class** (BL-0) |

### 3.2 Job graph `[SPEC]` — forks by client class, then at the visit (DEC-51, DEC-70)

```
PRELIM_SCOPE ──[client_class]
   │
   ├─ RESIDENTIAL (primary) ─────────────────────────────────────────────────────────
   │   MATCH → ASSIGN_VISIT → MOBILISE → VISIT
   │      │                                │
   │      │ (SAFETY_GATE escalates)        ├─ resolved_on_site → COMPLETE → INVOICE → CLOSE
   │      └──► HUMAN_HANDOFF               ├─ needs_return → CONFIRMED_SCOPE → QUOTE
   │           (visit cancelled,           │      → APPROVE → SCHEDULE → EXECUTE
   │            requester told)            │      → [VARIANCE ⟲] → COMPLETE → INVOICE → CLOSE
   │                                       └─ wrong_trade → REROUTE (evidence carried over)
   │
   └─ COMMERCIAL (fork) ─────────────────────────────────────────────────────────────
       RFQ_DRAFT → REQUESTER_APPROVE (INV-21) → SOLICIT → BID_RECEIVED → AWARD
          │                                                                  │
          └──► HUMAN_HANDOFF (no decision-maker identified)                  ▼
                                                        SCHEDULE → EXECUTE → [VARIANCE ⟲]
                                                             → COMPLETE → INVOICE → CLOSE
```

`APPROVE` (residential) and `REQUESTER_APPROVE` (commercial) are **the same single resume path**
(INV-12) — one guarded approval endpoint, two payload shapes. Do not add a second.

Hard-escalated tickets skip both forks → `HUMAN_HANDOFF` (INV-10), **regardless of client class**.
`COMPLETE` cannot exit without a label or `unlabeled_reason` on either branch.
**`resolved_on_site` is the residential happy path, not an exception branch** — Shane fixes a lot on
the first visit.

**Handoff contract:** the ticket graph emits one `DiagnosisReady` event
(`{ticket_id, diagnosis_id, escalated, escalation_reason}`).

### 3.3 Video session `[SPEC]` — deliberately NOT a graph (DEC-45)

```
session.start → [guided capture ⟲ processors + interview turns]
              → pre-flight triage (DEC-55) → visit offer + confirm loop
              → session.end → artifacts{keyframes[], transcript, detections[], equipment_id?}
              → POST /tickets  (ordinary INTAKE)
                    ↘ INV-15 hazard → terminate + hard-escalate, artifacts still persisted
```

No checkpointer, no resume path, cannot call the ticket graph. **This is what keeps INV-12 intact.**

---

## 4. The Planes

### 4.1 Knowledge plane (multimodal RAG)

- **Ingestion:** page-as-image embedding, ColPali-family late-interaction → multi-vector patch
  embeddings. No OCR flattening; wiring diagrams and exploded views preserved.
- **Index:** Qdrant (HNSW), ingestion-time only. 🔄 int8 quantization + on-disk (DEC-9, BL-12).
- **Retrieval:** dense multi-vector MaxSim + BM25 via RRF. **BM25 stays (DEC-10)** — exact-token
  match *is* the signal for SKUs and model codes. Sparse indices must use the stable hashlib
  tokenizer; builtin `hash()` is per-process random and was silently dead for weeks. Canary guards it.
- 🔄 Embedder bake-off (DEC-2, BL-5) · reranker (BL-1) · corrective loop (DEC-11, BL-9).
- **Lean mode (DEC-29):** embedder + reranker API-hosted behind existing Protocols. Residency recorded.
- **Qdrant stays (DEC-3)** — pgvector cannot do late-interaction MaxSim.

**🔄 Trade corpus expansion (BL-27, DEC-43).** Current corpus is 3 fixture ACME manuals (9 points);
off-corpus tickets correctly escalate as `diagnosis_unparseable` — known thinness, not a bug.

| Trade | Document classes | Priority sources |
|---|---|---|
| HVAC | Service manuals, install instructions, fault-code tables, wiring diagrams, parts breakdowns | Goodman/Daikin, Carrier, Trane, Lennox, Rheem, Mitsubishi |
| Appliance | Service manuals, error-code tables, exploded views | Whirlpool, LG, Samsung, Bosch |
| Electrical | Panel/breaker install guides, device specs, **code (CEC + provincial)** | Schneider/Square D, Eaton, Siemens; CSA C22.1 |
| Plumbing | Water heater + boiler manuals, fixture install guides, **plumbing code** | Rheem, AO Smith, Bradford White, Navien; NPC |

`doc_class` is a payload field on every chunk (`service_manual | install_guide | code | fault_table |
parts_diagram`) so retrieval and eval attribute per trade **and** per document class.

### 4.2 Procurement plane

- NL part need → candidate SKU: retrieval → synonym expansion → rerank → candidate lock.
- 🔄 Deterministic compatibility hard-filters in Postgres (DEC-12, BL-11). ⏸ Graph DB only if SQL is
  outgrown (DEC-13).
- 🔄 **Warranty status is first-class on `equipment` (DEC-34).** Without it we systematically
  over-scope newer equipment — the best-margin segment. Elevated now that HVAC is the lead trade.
- **Output is a truck manifest, not a BOM (DEC-32):** `confirmed_needed` / `likely_needed`, two-tap
  editable, contractor-facing only. **Bias to recall** — a missed part is a second trip; an
  over-included cheap part is nearly free. Every edit is a label.
- ⚠️ **OPEN-1: catalog source undecided**, bounds everything downstream.

### 4.3 Case/record plane

- **R2/S3:** media bytes, presigned direct upload, multipart for video, + keyframes, session
  recordings, detection overlays. ⚠️ **DEC-28 is the top open risk** — R2 gives an NA hint with no CA
  jurisdiction guarantee; hard migration trigger before procurement review or first paying customer.
  v6/v7 raised the stakes: interior video, provider PII, compliance documents.
- **Postgres:** source of truth. Case records · checkpoints (×2) · `ContractorStatement` labels ·
  provider registry · `job_event` ledger · equipment registry · **identity + conversations (§4.11)**.
- ⏸ DuckDB/Parquet split (DEC-4). `job_event` and video artifacts trigger this before the flywheel does.

### 4.4 Reasoning layer

- Claude Sonnet primary VLM, GPT-4o fallback, via LiteLLM. **INV-19 stop-reason check lives here.**
- **Langfuse deferred from the pilot box (DEC-30)**; tracing no-ops when `LANGFUSE_*` unset.
  **Re-enable before BL-22, BL-29, BL-45** — autonomy edit-rate and failure-rate telemetry have no
  home without it.
- 🔄 Eval pipeline (BL-3), CI-gated, **split by trade and `doc_class`**.
- Non-deterministic outputs (DEC-20): `--runs N`, never single-run point estimates.

### 4.5 Coordination plane `[SPEC]`

**Dispatch (Vista-backed, 40,000 providers) orchestrates work already scoped by a human. Hero
manufactures the scope.** Stay on our side of that line.

#### 4.5.1 Structured interview (at `INTAKE`)

Runs over text, voice, or a live video session — same questions, different modality.

- **Timeline** — when it started, constant or intermittent, worsening
- **Recent changes** — highest-signal question, and the one nobody asks. Shane: *"it happened after
  such and such came and drilled a pin for a painting. Could have drove into the wire."*
- **Isolation already attempted** — breakers checked, valve shut, unit reset, filter changed
- **Environmental context** — which unit/floor/zone, what's above and beside
- **Equipment identity** — make, model, serial from the nameplate (§4.8.3)
- **Guided capture** — what to photograph or film, and **what not to attempt**

**Under 5 minutes** (Shane: *"we need to be quick"*). No account, no app, no portal (Ryan:
*"nobody wants to sign up for another portal"*). Never instruct a requester onto a roof, into a
panel, or under a unit. **INV-15 outranks all of it.**

#### 4.5.2 The Scope Report

Home-inspection-report structure, named unprompted by Tyler (GC). **Three flavours (DEC-56, DEC-70):**
`preliminary` (remote, from the session) · `confirmed` (on-site, from the tech) · `rfq` (commercial,
from the preliminary + site context — §4.13). **Quotes may only be built from `confirmed`; an `rfq`
is priced by the bidding contractor, never by us.**

1. **Summary** — top issues, plain language, red / yellow / green band
2. **Evidence** — media, keyframes, answers, timeline, recent changes, manual/code citations
3. **Scope tree** — trades involved, sequenced, with dependencies (Tyler's *"critical path"*)
4. **Range** — best case **and** worst case, explicit margin of error. *"There needs to be some sort
   of range of error."* The uncertainty is the deliverable — managing the gap between *"I thought I
   was just changing the pipe"* and *"now I need drywall, mold remediation, and a painter"* is the
   hardest part of the job.
5. **Gaps** — what could not be assessed and why, ranked by what to check first

**Never a diagnosis, never a price, never a customer-facing parts list (INV-9).** Band renders
`calibrated_confidence` only (INV-4); non-singleton conformal set forces red.

**Pricing posture** — report recommends, contractor sets the number. Formalises Shane's existing
decision: *"You price the job. Sometimes, if there's something that needs to be fixed, I will go
hourly because I don't know what's wrong."*

| Band | Posture | Dispatch |
|---|---|---|
| Green | Fixed price | Book directly |
| Yellow | Fixed + named allowances + stated exclusions | Book directly |
| Red / non-singleton | Time & materials, stated up front | Diagnostic visit, tech pre-loaded with ranked hypotheses |

#### 4.5.3 Provider registry and matching (`MATCH`)

Built **conversationally, not by form** — the users do not type. Onboard by phone; enrich per job;
infer from behaviour.

*Stored:* trade + specialisations · licence class · **job-size band** · geography + travel tolerance ·
rate structure (timestamped, decaying) · compliance docs with expiry · building access history ·
liability capacity · crew size · languages
*Queried live:* availability · capacity · appetite. Never stored as truth — Shane has no calendar.

**Job-size band is the highest-value non-obvious dimension.** Tyler: *"If it's a small issue, what I
don't want to do is call up the massive industrial electrician who has 14 huge commercial buildings
and condo towers."*

**Matching:** hard filters (trade, geography, size band, **compliance currency**, availability) →
internal ranking → shortlist of 3–4. Compliance-as-filter is the unlock: match on *"can legally start
Monday."*

**Ranking is invisible to providers (DEC-36).** Tyler named the churn mechanic exactly: *"If I end up
super badly rated on your system and I am paying you to be part of that, but I'm not generating any
jobs — I'm gonna leave. But if I am not aware of that rating system... it's not going to hurt
anybody."* Consumer-facing shortlist is a separate artifact.

**Override always available, one tap, no justification.** Interpersonal fit and concierge
relationships cannot be modelled and must not be faked.

#### 4.5.4 Compliance vault and site logistics (`MOBILISE`)

- **Compliance packet automation.** WSIB clearance, liability certs, licences stored once, expiry
  tracked, condo-board and PM forms auto-populated, routed and chased. Tyler: *"Five minutes [to
  fill]. But chasing those documents down from management, that can take five days. That can take 15
  days."* A database and a mail merge. **Ship it first (BL-17).**
- **Site logistics from the scope tree** — waste volume and bin sizing; floor and common-area
  protection; parking, elevator, dock windows. Bin sizing is **the only feature in the research
  corpus where a contractor volunteered payment**: *"I would pay you guys monthly if I had something
  that was like that."*
- **Supplier coordination — not procurement.** Confirm stock, hold for will-call, consolidate errands
  (Alex arranged a bin drop *and* a gravel pickup with one vendor: *"killed two birds with one
  stone"*), flag stale prices. ❌ Never resell, never claim a better price than the supplier.

### 4.6 Commercial plane `[SPEC]`

**The invoice is a diff, not a document (DEC-37).**

```
scoped tasks + scoped hours → actual work (contractor confirms/edits, voice-first)
  → actual hours → variance → invoice
```

Three things free: **mid-job scope change** (`VARIANCE` → customer re-approval by text with a number
in it); **margin truth** (quoted vs actual per job/tech/type, no typing); **training labels** —
routed with provenance so scope error, match error, and parts error stay separable.

**Passive cost capture only (DEC-38).** Receipt photo or card-feed attribution by timestamp +
geolocation; confirm only when ambiguous. Alex: *"I'm lazy. I don't type it into a computer."* One
tap maximum or the ground truth never arrives.

**Never merchant of record (DEC-39).** Connected-account processor; contractor is the merchant.
Financing presented at **scope time** — earlier than any competitor can, because ticket size is known
before dispatch.

### 4.7 Interaction plane `[SPEC]`

**Voice is the primary interface (DEC-40).** Four of four ride-along subjects use no software and
type minimally; all four talked fluently for 45–90 minutes while working.

| Surface | Talks to | Latency | Governing rule |
|---|---|---|---|
| **Intake Agent** | Requester | <700ms turn | Never diagnoses aloud, never quotes (INV-9/14). Confirms a **visit**, never a repair (INV-16) |
| **Operator Copilot** | Contractor, hands-free | <700ms, offline-tolerant | Every action reversible and in the ledger (INV-11) |
| **Coordinator Agent** | Suppliers, subs, PMs (outbound) | conversational | Cannot commit (INV-13) |

Field constraints: **offline-first** (mechanical rooms and basements have no signal — and the
mechanical room is exactly where Farid offered access) · noise robustness · push-to-talk default ·
multilingual (Spanish, Punjabi for the GTA) · always a manual fallback.

**Autonomy ladder (DEC-42)** — per action type, per account, earned:

| Level | Behaviour | Promotion |
|---|---|---|
| **L0 Observe** | Watches, logs, suggests nothing | Default for new action types |
| **L1 Draft** | Prepares; human reviews and sends | Default at onboarding |
| **L2 Approve** | Prepares; one tap executes | <20% edit rate over 30 actions |
| **L3 Auto** | Executes; human notified after | <5% edit rate over 100 actions, zero reversals in 30d |

Any edit demotes one level for 14 days · **dispatch and money never exceed L2** without written
opt-in · **never overrides the safety gate (INV-10)** · edit rate is the second-best training signal
and needs Langfuse (DEC-30).

#### 4.7.1 The contractor's assistant (DEC-77) — how the Intake Agent presents

**The Intake Agent presents as the company's assistant, not Hero's.** *"Hi, you've reached New
Toronto Electric — I'm their assistant. Can you tell me what's going on?"* Friendly, neutral Hero
voice. The requester knows immediately which business they've reached and that they're talking to an
assistant.

**Named for the business, never for a person (DEC-80).** Not *"Shane's assistant"* — the company is
New Toronto Electric, and Tyler has a business partner. A personal name is casual name-dropping to a
stranger, implies a personal assistant where there's a firm, breaks the moment staff change or the
business sells, and reads wrong for a forty-person shop. Company names are also what customers
actually recognise and what appears on the truck, the invoice, and the Google listing.

This is the logical extreme of white-labelling (DEC-68), and it matters more here than in most
categories: trust in home services is local and personal. A generic assistant signals *a tech company
is between me and my plumber.* A named assistant signals *this is my guy's office.*

**The trust signal is the name, not the timbre.** ❌ **No voice cloning of any real person, ever
(DEC-79, INV-22a)** — see the decision entry for the reasoning, recorded so it isn't re-proposed.

**Hero owns the protocol; the contractor owns the identity and policies (INV-22b).**

| Hero's, identical for every contractor | The contractor's, varies |
|---|---|
| Which questions are asked (§4.5.1) | **Registered business name** — never an individual's |
| Hazard behaviour and escalation (INV-15, INV-1) | **Tone preset** — a short menu (warm / brisk / plainspoken), not a learned speech model |
| What the requester may be asked to do (allow-list) | Greeting and sign-off wording |
| Evidence captured and how it's structured | **Stated policies** — diagnostic fee, flat-vs-hourly stance, service area, hours, exclusions |
| Visit-vs-repair language (INV-16) | Callback promise wording |

This is DEC-62's rule applied: **anything that changes what the agent is trying to learn belongs to
Hero; only identity and delivery vary.** A contractor may never configure what the agent asks, what
it escalates, or what it permits a requester to touch — otherwise safety behaviour becomes
contractor-specific, which is unacceptable.

**Policy capture is part of the onboarding call (BL-63)** and is now cheap — a short structured
intake, not voice-model training. Shane will not fill in a form but talked for ninety minutes on a
job site; that conversation yields the registry entry (§4.5.3) *and* the assistant's policies: the
$199 diagnostic fee, when he prices flat vs hourly, what he won't touch, his service radius. One
call, both artifacts. That is also why registry onboarding is conversational.

**Persona config lives in the repo, versioned, with a CI drift check (DEC-78, extends DEC-62).**
Never in a vendor dashboard. A contractor-facing edit UI writes through review, not around it — the
policies quoted to a requester are commercial commitments and must be auditable.

**Residency note:** dropping cloning materially simplifies INV-2 compliance. A single neutral TTS
voice can be self-hosted (Piper/Coqui class) rather than sourced from a US cloning vendor, which
takes TTS off the critical path for BL-24 and BL-36.

### 4.8 Capture plane `[SPEC]`

**Video is an intake modality with identical evidence logic to photos, not a new pipeline (DEC-45).**

#### 4.8.0 Three modalities, customer's choice (DEC-75)

**Live video is an option, never a requirement.** Forcing it kills completion rate, which is the
metric the entire session is gated on — and plenty of requesters are in a basement, on two bars, or
simply unwilling to film. **The agent behaves identically in all three modes.**

| Mode | Voice | Video | Photos | Notes |
|---|---|---|---|---|
| **Voice + live video** | ✅ | ✅ live | ✅ | Richest. Guided capture, temporal signal, live isolation testing |
| **Voice + photos** | ✅ | ❌ | ✅ upload | **The full assistant conversation, video off.** Same conversation, same questions, same visit confirmation |
| **Text + photos** | ❌ | ❌ | ✅ upload | Current Nova. Lowest friction, works on any connection. Persona carries in written register |

**Identical across all modes:** the interview protocol (§4.5.1) · the pre-flight gate (§4.10 ②) ·
the visit offer and read-back (INV-16) · the Scope Report · the safety gate · INV-15.

**What differs in photo mode**, and it is only mechanism, never behaviour:

| Live video does it by… | Photo mode does it by… |
|---|---|
| Frame-quality gate says *"hold steady, move closer"* | Quality check on upload → *"that one's a bit blurry, can you retake it?"* |
| Nameplate detector spots it in frame | OCR runs on each uploaded photo; agent asks for the sticker explicitly |
| Agent guides a pan for spatial context | Agent requests specific shots — *"one of the unit, one of the wall behind it"* |
| Agent observes an isolation test | Requester reports the result verbally — *"okay, flip it and tell me what happens"* |
| Hazard detector watches continuously | Hazard classification runs on **speech + each uploaded photo** |

> ⚠️ **Photo mode is deliberately more conservative on hazards (DEC-76).** The classifier has less
> signal — no continuous view, no motion, no audio of a hissing line. It therefore escalates on
> weaker evidence, not stronger. **Fewer hazard signals must never read as fewer hazards.** The BL-30
> red-team suite covers both modes separately.

**Mode is chosen at session start and can be changed mid-session in either direction**, without
losing turns or artifacts already captured. Bandwidth collapse degrades video → photos automatically
(§4.8.4); the requester may also just turn video off.

#### 4.8.1 Why video for these trades

1. **Guided capture** — the agent directs the camera and confirms the shot landed.
2. **Temporal and acoustic signal** — short-cycling compressor, failing bearing, breaker tripping
   under load, water actively dripping, furnace igniting and dropping out. **Highest-value HVAC
   signals; a photo carries none of them.**
3. **Spatial context** — panning shows unit-to-unit relationships, serving the multi-trade cascade.
4. **Live isolation testing** — *"flip that breaker and tell me what happens."* Precisely Shane's
   method: *"find out which circuits are tripping and then open them all up and work back."*
   **This is the capability leap.**

Item 4 is why INV-15 exists: it is the only feature that asks a non-professional to *do something*
to equipment. Test instructions come from a **deterministic allow-list**
(`safety/permitted_actions.py`) — reset a breaker, change a setpoint, replace a filter, run a
fixture. Never: open a panel, bypass a safety, relight a pilot, touch a gas line, access a roof,
enter a crawlspace, or operate anything smoking, sparking, or wet.

#### 4.8.2 Architecture — processor-first, not realtime (DEC-46)

```
device camera → WebRTC edge → processors (local/edge, <200ms)
                                 ├─ hazard detector      → INV-15 interrupt (pre-empts everything)
                                 ├─ nameplate detector   → crop → OCR → equipment lookup
                                 ├─ frame-quality gate   → "hold steady, little closer"
                                 └─ component detector   → panel / breaker / condenser / valve / pan
                              → keyframe selection (N frames, not a stream)
                              → VLM (fps=1, buffer 10s) for interview turns, ASYNC
                              → artifacts → POST /tickets
```

**Voice loop never blocks on a VLM (DEC-52).** The agent reasons over a `CaptureState` object fed by
detections, not over frames. That is what makes it feel synchronised while honouring both the <700ms
budget and INV-2.

Rationale compounds: **residency** (continuous interior footage is the most sensitive class we
handle) · **cost** (video at 3fps is another order above the full text path; keyframes are ~2 orders
cheaper) · **quality** (a frame-quality gate beats a bigger model on a blurry nameplate).

⏸ **Realtime mode (BL-33) deferred** until CA-resident realtime inference exists and unit economics
clear. Revisit for the technician-side copilot, where the user is a professional.

#### 4.8.3 Equipment identity — the highest-ROI processor (DEC-47, BL-28)

Nameplate → make/model/serial → `equipment` → **warranty (DEC-34)** → corpus filter → better retrieval.

Closes four loops at once: collapses the retrieval search space, populates the equipment registry the
preventative layer needs, triggers the warranty flag, and hands the contractor the model number they'd
otherwise be texting a photo of. **Ships before any conversational video capability.**

#### 4.8.4 Session governance

Jurisdiction-aware consent before the camera opens (distinct from call-recording consent — this is
video inside a home) · **5-minute hard cap** · R2 by pointer (INV-3), full-session recording opt-in,
keyframes + transcript + detections default · every session writes `job_event` rows ·
**bandwidth floor: degrade to photo capture rather than failing.**

### 4.9 System of engagement — Twenty `[SPEC]`

**Twenty is the system of engagement; Hero Postgres is the system of record (DEC-48).**
**Self-hosted in a Canadian region; Twenty Cloud is not an option (DEC-49).**

| Concern | Owner | Never |
|---|---|---|
| Contacts, companies, pipeline, activities, tasks, notes | **Twenty** | — |
| `ticket`, `diagnosis`, `diagnosis_claim`, `contractor_statement` | **Hero** | Never authoritative in Twenty |
| `job`, `job_event`, `approval`, `autonomy_state` | **Hero** | Never writable from Twenty |
| LangGraph checkpoints (×2) | **Hero** | Never leaves Hero Postgres |
| Provider registry + `provider_metric` | **Hero** | Ranking never shown to providers (DEC-36) |
| Scope Report, truck manifest, invoice | **Hero**, *rendered in* Twenty | Rendering ≠ ownership |

Hero → Twenty authoritative for job/diagnostic state; Twenty → Hero for contact/pipeline.
Integration is **API-level** (GraphQL + webhooks + one Twenty app package). **Hero does not become a
TypeScript shop.**

❌ **No diagnostic or dispatch logic in Twenty's Skills & Agents framework.** Twenty renders; Hero
decides.

**Cost (DEC-50):** server + worker + Postgres + Redis on Node 24.5/Yarn 4. On the current pilot box
(single 4GB VM, lean mode, Langfuse dropped to save 5 containers) **this does not fit.** Lands after
the Phase 6 deploy gate; likely triggers the DEC-29 reversion conversation.

### 4.10 Interactive intake → confirmed visit `[SPEC]`

> Full flow, drop-off analysis, and build sequence: `HERO_AI_INTAKE_SESSION_SPEC.md` (v2).

**The visit is a product contractors already sell.** Shane: *"$199. First hour of work... I'm
thinking I might up the price to 249."* Tyler: *"Oftentimes I will charge for those and then say,
should we secure the contract, that will be credited back."* We are not asking anyone to trust an AI
diagnosis — we are making their existing paid first step shorter and better-equipped.

**Six stages, and no stage ever ends without a next step. Silence is the only real failure.**

```
① SESSION      voice + video, ≤5 min, interview + capture
② PRE-FLIGHT   hazard + trade + urgency → hazard: ESCALATE, no visit | clear: continue
③ VISIT OFFER  2–3 windows → pick → read-back → CONFIRMED VISIT
④ PIPELINE     full ticket graph → PRELIMINARY scope; SAFETY_GATE may UPGRADE the visit
⑤ DELIVERY     report to assigned tech: SMS + email + CRM, before arrival
⑥ ON-SITE      confirm or correct → CONFIRMED scope + ContractorStatement
               ├─ fixed on the spot → COMPLETE + invoice   (the happy path)
               ├─ needs return      → QUOTE → repair job
               └─ wrong trade       → REROUTE
```

**Pre-flight triage is a standalone classification, not a graph state (DEC-55)** — reuses
`safety/hazards.py` and the TRIAGE classifier, so it and `SAFETY_GATE` cannot disagree in the unsafe
direction. Target <2s, fits a conversational pause, creates no second resume path.

**Confirm loop language matters and is prompt-tested (BL-39):** *"a technician needs to come take a
look"* · read-back with address · fee disclosed **before** confirmation (a surprise fee at the door
destroys trust fastest) · escalation pre-disclosed in one sentence.

**Every diagnostic visit produces a `ContractorStatement`** whether or not a repair follows — labels
now accrue at *visit* rate, not *completed repair* rate. Highest-value engineering consequence of the
visit model.

### 4.11 Delivery, identity & reliability `[SPEC]`

> Full detail: `HERO_AI_PRD_V7_AMENDMENTS.md`. The layer between "an agent decided something" and
> "a human actually received it" — where communications products actually fail.

**Webhook receivers verify → enqueue → ack, nothing else (DEC-57).** Vendors retry on slow acks, so
work in the request path causes a self-inflicted retry storm under peak load. Signature scheme
verified against vendor docs, never assumed. **Per-route body caps enforced before the body is
buffered**, plus a catch-all on `/webhooks/*`.

**Queue separation by "is a human waiting?" (DEC-58):** `live` (interview turns, hazard
classification — a human is mid-sentence) · `dispatch` · `ingest` (protects the Postgres pool) ·
`pipeline` · `batch`. The <700ms budget makes this mandatory. Corpus ingestion must never delay a
live interview turn.

**Failed-and-notified bar (DEC-59).** Every inbound interaction ends processed-and-answered or
failed-and-notified, never silently dropped. **Terminal vs transient split in the type system** —
blur is terminal per frame (*"hold steady, move closer"*), a VLM 503 is transient. One shared
human-facing terminal path. **Stage-first ledgers:** persist the staging row from the raw payload
*before* any fallible work, enrichment columns nullable. Otherwise a fault in that window leaves no
row at all — the vendor has its 200, won't redeliver, and no diagnostic can observe the loss.

**Message coalescing for text interview turns (DEC-60)** — quiet window ~5s, hard ceiling ~30s,
max-resets cap, interruptible composes, reset/commit isolated in one pure testable function.
**⚠️ Sits strictly BELOW hazard classification. INV-15 runs per message, before batching.** A tenant
typing *"wait I smell gas"* as fragment three of five must interrupt on arrival.

**Per-turn transcript validation (DEC-61).** A call is unrepeatable evidence. One malformed turn
drops that turn, loudly. **An unknown speaker role is dropped, never defaulted** — a wrong default
silently files the agent's own words as things the requester said, and *"the tenant said the breaker
was reset"* vs *"the agent asked whether it was"* is a truck roll.

**Vendor-hosted config drift (DEC-62).** Where a prompt lives in a vendor dashboard it forks from the
repo the moment anyone edits it. Objective lives in the repo; reconciliation script; CI drift check.
**Anything that changes what the agent is trying to learn belongs in the shared objective, never in
per-channel framing** — that is the enforcement mechanism for "same questions, different modality."

#### Identity and conversations (DEC-63) — the largest structural gap

Hero has **no identity resolution layer**, and needs one more than a CRM does: providers onboard by
phone, requesters have no account, the coordinator agent calls outbound. Every interaction arrives as
a bare phone number or email. **Without it the provider registry fragments into duplicates and
`provider_metric` — the ranking driving matching — accumulates against ghosts.**

```sql
party_identifier (party_type, party_id, type, value, verified, UNIQUE(type, value))
conversation     (party_id, channel, vendor_external_ref, state, UNIQUE(channel, vendor_external_ref))
conversation_message (conversation_id, speaker, text, timestamp, external_ref)
party_attribute  (party_id, key, value, source_conversation_id, observed_at)  -- accumulate, never overwrite
```

**Normalize before every write** (E.164 with channel-prefix stripping, lowercased email) — "exact
match" is meaningless without canonicalization. **Race-safe creation by constraint, not lock** — two
concurrent events race the unique insert, the loser adopts the winner's party. **Anonymous path** — a
caller with withheld ID gets a review-flagged party; a tenant calling from a blocked number does not
lose their ticket.

**Confidentiality guard (DEC-64):** if the resolved party and the conversation's stored party
disagree, **refuse the write and dead-letter.** Hero's cases are routine — a sub replying on a GC's
thread, a second tech texting from a job site. In a network where provider terms are confidential to
the coordinator (§10.1), cross-filing is a **breach, not a bug**.

#### Database practices

- **Grant hygiene as invariant tests (BL-42).** Postgres grants `EXECUTE` to `PUBLIC` by default;
  granting to a role is additive, not exclusive. §14 claims `job_event` and `live_hazard_event` are
  append-only "enforced by grants not convention" — **this is the class of mistake that silently
  voids that claim.** Ship as tests, not migrations, so a future migration that forgets fails CI.
- **Insert flags are not completion signals (BL-43).** At every idempotent boundary — OUTCOME label,
  dispatch notify, requester confirmation, invoice, Twenty push — ask whether the work happened by
  **querying state**, never by trusting this attempt's insert result.
- **Atomic join-or-open with `pg_advisory_xact_lock`.** Read-then-insert races on natural keys get
  replaced by one locked SQL function returning the row either way.
- **Dead letters, fail-closed config, three-valued liveness (BL-46).** Task runners swallow unhandled
  exceptions — a run that exhausts retries otherwise vanishes. `Number("")` → `0` silently zeroing a
  window is the config version of the `server_default="now()"` bug. **The job graph parks for
  hours-to-weeks on approvals**, so a `_JobResumeGuard` companion sweep distinguishing "legitimately
  waiting" from "wedged" belongs in BL-20's DoD.

### 4.12 Distribution & requester surface `[SPEC]` — new in v7

**Hero is a web app with pluggable entry points, not a widget (DEC-66).** One session implementation,
CA-hosted (INV-2 stays clean — the session never executes inside a contractor's host), reached many
ways. The Fresha analogy holds for shape: the booking surface lives on the platform, and the business
points at it from wherever they already are.

**Entry points, in order of expected volume:**

| Entry point | For | Notes |
|---|---|---|
| **SMS link** | Version B primary | Works for Farid day one — his tenants already call, his staff have their numbers |
| **Missed-call-text-back** | Every trade contractor | Auto-response <15s with the session link. Highest-frequency pitch in the market; every contractor knows their missed-call number |
| **Google Business Profile action** | Shane's profile | **Highest-leverage single integration on the acquisition side.** *"Most of my work is from Google"* — 80+ reviews, no website. Costs him nothing to enable |
| **QR on equipment / in lobby** | Farid's buildings | Opens a session with **equipment already identified** — pairs with BL-28, skips nameplate hunting |
| **Inside the PM's existing portal** | AppFolio/Yardi tenants | Already logged in, already submitting work orders with photos. Zero adoption cost |
| **Embed on contractor site** | Contractors with traffic | Version A channel. Real, useful, last |

**Embed mount order, most robust first (DEC-66):**
1. **Plain link** — `<a href>` to the hosted session. No JS, unbreakable. **This is the default
   recommendation, not the fallback.** Contractor sites are Wix, Squarespace, GoDaddy, or WordPress
   built by someone's cousin; a JS embed breaks on those and it's our fault at 7am.
2. **Launcher script** — ~5KB, styled button, session in a modal iframe, sandboxed with strict CSP.
3. **Native mount** — full-page on Hero-built sites, shared design system, no iframe.

**Hosted contractor profile pages (DEC-67).** `hero.ai/[contractor]` — reviews, service area, years
in business, and **licence and insurance shown as verified**, which nobody else can display because
nobody else holds a compliance vault. The session is the primary CTA. Solves Tyler entirely: he
doesn't need a website, he needs a page, and he can have one this week.

> ⚠️ **Direct-link only. Not indexed as a browsable directory. No cross-contractor search.**
> The moment there is a "find a plumber near me" page, we have started building Angi by accident
> (DEC-35). This bound is easy to drift across and hard to walk back.

**The CTA is the actual design decision.** Every trade site has a contact form, and forms convert
badly for a structural reason: they demand commitment — name, email, phone — before returning any
value. The session inverts the trade. **"Show us the problem"**, and you get a confirmed visit before
you hang up. Value first, commitment second. The form stays as a demoted fallback.

**White-label by default (DEC-68).** Trust in home services is local and personal — a tenant wants to
talk to their building, a homeowner to their plumber. Brand to the contractor or property, with small
"powered by Hero" attribution doing contractor-side inbound quietly. We have no consumer marketplace,
so we need no consumer brand.

**Websites as a productized acquisition channel (DEC-65).** Templated with real craft, fixed-price,
three-day turnaround, Hero-hosted. Bundled into the setup fee — Tyler endorsed exactly this:
*"an upfront fee for setting up the thing, because that's already a big deal."*
❌ **Never bespoke or hourly design work.** The moment it becomes "move that section down, change the
blue" billed by the hour, we have started an agency with a software side project — and services
revenue gets discounted hard on multiple, which is the first thing an M&A-literate advisor will look
for in the revenue mix.

### 4.13 Commercial fork — the quote request `[SPEC]` — new in v8

> **Secondary path. Residential stays primary (§1.1.1).** Everything before `PRELIM_SCOPE` is
> identical — same session, same interview, same capture, same diagnosis, same safety gate. Only the
> terminal artifact and the downstream flow differ.

#### Why the artifact differs

A homeowner wants someone to come look. **A commercial client is starting a procurement process.**
They need a document complete enough to be bid against — often by more than one contractor — and
they have an approval chain, a purchase order, and vendor requirements. A "confirmed visit" is the
wrong output; a **structured quote request** is the right one.

#### What the RFQ contains (DEC-70, DEC-72)

Everything in the preliminary Scope Report (§4.5.2), plus commercial context:

| Block | Contents | Source |
|---|---|---|
| **Requesting party** | Organisation, site, billing entity (frequently different), reporter, decision-maker | Party model (§4.11) |
| **Site & access** | Address, unit/zone, after-hours constraints, escort or security requirement, loading dock, elevator booking, parking | `site` record |
| **Assets** | One row per affected asset — *"RTU-3 and RTU-5"*, not *"the AC"* | `equipment` (BL-59) |
| **Scope of work** | **Itemised by task**, suitable for bidding | Scope tree |
| **Evidence** | Photos, keyframes, transcript, timeline, manual/code citations | Capture artifacts |
| **Gaps** | What could not be assessed; explicitly flagged as bidder-to-verify | Scope report |
| **Vendor requirements** | COI limits, WSIB, licence class, trade certifications | **Compliance vault (§4.5.4)** |
| **Commercial terms** | Response deadline, format, PO reference, sole-source vs competitive | Requester config |

**Itemised by *task*, never by *part* (DEC-72).** *"Replace condensate pump on RTU-3, including
removal and disposal of the existing unit"* — not a SKU list with prices. The bidder supplies parts
and prices; that is the entire point of an RFQ. **This keeps INV-9 intact in the commercial context
and is in fact more clearly correct here** than it is residentially — nobody expects the requester to
specify parts in a bid document.

The vendor-requirements block is a quiet advantage: because Hero holds verified compliance documents,
**solicitation can be pre-filtered to contractors who already meet the requirements**. No other
system in this category can do that, and it removes the most common cause of a bid being thrown out.

#### Flow

```
PRELIM_SCOPE → RFQ_DRAFT → REQUESTER_APPROVE → SOLICIT → BID_RECEIVED → AWARD → SCHEDULE → ...
```

**`REQUESTER_APPROVE` is mandatory and is the INV-21 gate.** The reporter is frequently not the
decision-maker. The draft goes to the named decision-maker, who edits, approves, or rejects. Only
then does anything leave the building. Where no decision-maker is identified, the RFQ stays in draft
and a human is notified — **never sent to a default recipient.**

**Solicitation is single or competitive**, at the requester's choice. Competitive means the same RFQ
to N contractors, all pre-filtered on compliance and job-size band.

**No bid portal in v1 (DEC-74).** Contractors respond however they already respond — email, phone,
their own quote template. Hero tracks that a response was received and attaches it to the job. A
structured bid-comparison flow is BL-61 and is deliberately deferred; building it now would be a
month of work for a workflow we have not yet watched anyone perform.

#### Delivery

Same three channels as the residential Scope Report (DEC-54) — SMS with a link, email, CRM record —
**with one difference: the PDF matters more.** A commercial contractor's estimator attaches the RFQ
to their bid file. Generate a proper document, not just a web page.

#### What stays identical

- **The safety gate.** A gas leak at a restaurant is a gas leak. Hard-escalated tickets skip the fork
  entirely (INV-1, INV-10).
- **INV-9.** The RFQ describes scope and evidence. It does not diagnose authoritatively and it does
  not price.
- **The flywheel.** An awarded and completed commercial job produces a `ContractorStatement` exactly
  as a residential visit does. Commercial jobs are lower-volume and higher-value, so they contribute
  fewer but richer labels.
- **The single resume path.** `REQUESTER_APPROVE` shares the guarded approval endpoint with
  residential `APPROVE` (INV-12).

---

## 5. Verification, Calibration & Safety

- `VERIFY` grounds claims against retrieved evidence (INV-4, claim-level per DEC-6).
- **Platt/temperature scaling now; isotonic gated at ≥1,000 outcomes; global before per-trade
  (DEC-5).** Per-trade is more attractive sooner given HVAC vs electrical evidence quality (§1.1),
  but the ≥1K gate still binds, per trade.
- 🔄 **Conformal prediction at `SAFETY_GATE` (DEC-14, BL-10):** escalate when the set is non-singleton
  or contains a hazard category. Non-singleton also forces red band + T&M posture.
- Precedence: **INV-15 (live danger) > INV-1 (hard category) > INV-10 (above the ladder) >
  calibrated confidence.**

---

## 6. Backlog (table order = priority; IDs stable; **BL-38 unallocated and BL-64 withdrawn (DEC-79) — do not reuse either**)

> **Renumbering note (2026-07-29).** PRD v5–v8 were drafted against v4's visible BL-0..12 and
> unknowingly reissued IDs BL-13..24, which the repo had already allocated (commits and code cite
> them). Resolution, per founder ruling: **committed IDs keep their original meanings** — completed
> ones are in §6.1; still-open ones (BL-13, BL-15, BL-23) are restored to the table below. The v8
> items that collided were reissued at the end of the range:
> Compliance vault BL-17 → **BL-73** · Scope Report BL-19 → **BL-74** · Job graph BL-20 → **BL-75** ·
> Provider registry BL-21 → **BL-76** · Autonomy ladder BL-22 → **BL-77** · Invoice-as-diff
> BL-23 → **BL-78** · Structured interview at INTAKE (v8 draft's BL-18) → **BL-80** · CI-driven
> deploys (ex-BL-24, never committed) → **BL-79**. Operator Copilot keeps **BL-24** (the old
> BL-24 allocation was never committed).
> Commits dated before 2026-07-27 citing BL-13..24 always mean the old (v4/Phase-5) items.
> ⚠️ The companion specs, HANDOFF.md, and WORK_ORDER_v8.2.md still cite the pre-reconciliation
> numbers (BL-19/20/21/22/23) for the moved items — read them through this mapping until updated.

| ID | Item | Effort | Why |
|---|---|---|---|
| **BL-0** | `OUTCOME` label capture: near-zero-friction confirm/correct; velocity tracked | ongoing | The moat |
| **BL-81** | ✅ 2026-07-29: **Hazard phrase coverage + recall instrumentation** — `safety/hazards.py` rewritten as per-category patterns (`scan_hazards`): inversions, colloquialisms, sensory-not-substance ("rotten eggs"/"sulfur" for mercaptan), misspellings, panicked fragments; strict superset of the legacy keyword list, wired into both consumers (Nova guardrail + safety gate). Adversarial corpus `evals/hazard_redteam_cases.py` (96 must-catch, 8 categories) — **the pattern list is an output of the suite, not an input**. Recall asserted at 100%/category (`tests/invariants/test_inv15_hazard_recall.py`); report via `evals/run_hazard_recall.py`. INV-15 amended with the monotonicity rule | ~2 days | INV-15's canonical example ("wait I smell gas") missed the old keyword scan — a hand-curated list never converges by inspection. Class A-safe: more escalations only, no new failure path |
| **BL-42** | ✅ 2026-07-29: **Grant-hygiene invariant tests** — `tests/invariants/test_grant_hygiene.py` runs the real alembic chain into a scratch DB, then asserts: no function grants EXECUTE to PUBLIC, every function pins `search_path`, and `job_event`/`live_hazard_event`/`dead_letter` (enforced-if-present) revoke UPDATE/DELETE/TRUNCATE with nothing granted to PUBLIC. Plus `test_inv12_single_resume.py`: AST allowlist asserting exactly one `Command(resume=…)` call site per graph (founder Q4 ruling) | ~1 day | Closes the class of bug that silently voids §14's append-only enforcement; a future migration that forgets fails CI |
| **BL-73** | Compliance vault + packet automation | ~1 wk | 5 min vs 15 days; converts a design partner into a live network |
| **BL-47** | **`party_identifier` + normalization + race-safe creation** | ~1 wk | **Migration 1.** Without it the registry fragments and `provider_metric` accumulates against ghosts |
| **BL-35** | **Capacity model + `visit` + confirm loop + reminders** (on existing *text* intake) | ~2 wk | Validates the whole commercial premise in 2 weeks, no video/voice/residency dependency |
| **BL-65** | **`task_taxonomy` + seed (HVAC, ~200 codes) + `task_alias`** | ~2 wk | **Nothing compounds without it.** Migration-1 shaped — the join key for catalogue, cases, pricing, matching |
| **BL-27** | Trade corpus expansion + `doc_class` payload | ~2 wk | v6 repositioning is inert without it; fixture corpus is 9 points |
| **BL-66** | `vendor_catalog_item` + import + price decay | ~1 wk | Solves the pricebook cold start; required for pricing posture |
| **BL-67** | **Document ingestion pipeline** (invoices/quotes → line items → task codes, ColQwen reuse, review queue) | ~3 wk | The onboarding demo *and* day-one case backfill. Lowest-risk ask of a design partner |
| **BL-68** | `case_record` + `case_narratives` vector collection + de-identification | ~2 wk | The compounding store. Blocked on BL-65 |
| **BL-74** | Scope Report artifact (preliminary + confirmed) | ~2 wk | INV-9 made concrete |
| **BL-37** | Preliminary report delivery: SMS + email + signed mobile page + CRM | ~2 wk | The tech reads it before the truck moves |
| **BL-50** | INV-19 stop-reason allowlist in the LiteLLM adapter | ~1 day | One place; prevents silently narrowed conformal sets |
| **BL-49** | ✅ 2026-07-29 (current surfaces): **INV-18 injection suites** — `tests/unit/test_injection_nova.py` (instruction-override → fixed-copy redirect, never allow; hazard keyword outranks injection framing; replies never echo attacker text) + `tests/unit/test_injection_prompt_rendering.py` (retrieved/inbound text renders verbatim and inert — token lookalikes never re-expanded, template scaffolding intact; keyword floor + DEC-21 override beat injected downgrades even when the VLM parrots them). Grows one suite per new agent surface (copilot, coordinator, capture session) in that surface's PR | ~3 days | Cheap; hardens surfaces about to be built |
| **BL-75** | Job graph + `_JobResumeGuard` + `job_event` ledger | ~2 wk | Structural prerequisite for the coordination plane |
| **BL-41** | On-site confirm/correct + three-way visit fork + `CONFIRMED_SCOPE` | ~2 wk | **Label velocity starts here** |
| **BL-3** | ⚠️ partial — Eval pipeline: golden-ticket eval with `--runs N` ✅ (`evals/run_eval.py`). **Remaining: not CI-gated, not split by trade/`doc_class`** (the split feeds §1.1's band-distribution finding); `run_nova_eval.py` lacks `--runs` (DEC-20 gap) | ~1 wk | Prereq for BL-5/9/74/27 |
| **BL-43** | Insert-flags + atomic join-or-open audit | ~3 days | Do before dispatch notify and invoice exist |
| **BL-71** | Twilio transit config: redaction, recording off, media → R2, residency record | ~1 wk | Prerequisite for any SMS or voice channel |
| **BL-69** | `price_band` with k≥5 floor + decay | ~1 wk | Contractor-facing benchmark. Blocked on BL-66 |
| **BL-70** | Task → eligible-contractor resolution (registry + compliance + capacity join) | ~1 wk | Closes diagnosis → dispatch. Blocked on BL-76, BL-65 |
| **BL-72** | Self-hosted ASR + templated-TTS constraint with enforcing tests | ~2 wk | Removes the larger half of the voice residency exposure |
| **BL-53** | **Google Business Profile booking action** | ~1 wk | Cheapest distribution available; works for contractors who will never have a website |
| **BL-40** | Pre-flight triage (standalone, deterministic-first) | ~1 wk | Gates the visit offer |
| **BL-30** | **Live-hazard classifier + red-team suite (INV-15)** | ~1–2 wk | **Blocks all conversational video.** Life safety |
| **BL-45** | **INV-20 failure-rate monitors**, hazard classifier alerting | ~1 wk | Ship *with* BL-30 — an unmonitored safety classifier is a safety gap |
| **BL-52** | Contractor profile page + native session mount | ~2 wk | Solves Tyler without a website |
| **BL-56** | **`client_class` + `site` model + party roles (reporter/decider/payer)** | ~1 wk | Schema-shaped; the reporter≠decider split is what makes commercial work and it's cheap now |
| **BL-58** | **RFQ artifact + `REQUESTER_APPROVE` gate (INV-21) + delivery incl. PDF** | ~2 wk | The commercial terminal artifact; reuses the whole pipeline |
| **BL-59** | Multi-asset tickets (*"RTU-3 and RTU-5"*, not *"the AC"*) | ~1 wk | Commercial faults are routinely multi-asset; residential rarely is |
| **BL-60** | Site access constraints (after-hours, escort, dock, elevator) on the site record | ~3 days | Feeds both the RFQ and residential `MOBILISE` |
| **BL-62** | **Modality selection + photo-mode parity** (DEC-75/76) | ~1 wk | Photo mode works on today's stack with no residency blocker — it is the *default*, not the fallback |
| **BL-63** | **Assistant identity + policy capture at onboarding** (name, tone preset, fee, exclusions, service area) | ~1 wk | Cheap now that cloning is out (DEC-79). One onboarding call yields the registry entry *and* the assistant config |
| **BL-76** | Provider registry + matching, conversational onboarding | ~3 wk | Version B core |
| **BL-51** | `conversation` + `conversation_message` + `getPartyTimeline` | ~1 wk | Interaction plane needs it; feeds BL-32 |
| **BL-46** | Dead-letter hook + fail-closed config + three-valued liveness | ~1 wk | Wedged approvals are invisible today |
| **BL-28** | **Nameplate → equipment identity + warranty** | ~2 wk | Closes four loops; highest-ROI in the video work |
| **BL-54** | Embed launcher script (sandboxed iframe, strict CSP) | ~1 wk | Version A channel |
| **BL-44** | Message coalescing for text interview turns | ~3 days | **Ships after BL-30** |
| **BL-9** | Corrective retrieval loop, capped + timeout | ~1 wk | Needs BL-3 |
| **BL-36** | **Synchronised voice + video session** | ~4 wk | Blocked on BL-28, BL-30, BL-40, residency |
| **BL-31** | Twenty self-host + sync layer | ~3 wk | Blocked on deploy gate + capacity (DEC-50) |
| **BL-48** | CRM reconcile sweep + idempotency-by-constraint | ~3 days | Part of BL-31's DoD |
| **BL-77** | Autonomy ladder policy layer + edit-rate telemetry | ~2 wk | Blocked on Langfuse (DEC-30) |
| **BL-32** | Scope Report as a Twenty front component | ~1 wk | Coordinator's daily surface |
| **BL-55** | Site template (productized, Hero-hosted) | ~2 wk | Setup-fee offering; design work doesn't compete with engineering |
| **BL-39** | Prompt-level language tests for INV-16 | days | Visit vs repair |
| **BL-5** | ⚠️ partial — Embedder bake-off: adapters ✅ (`colmodernvbert`; Bedrock lean mode per DEC-29). **Remaining: the bake-off itself never ran — DEC-2 is an open question, not a settled decision** | ~1 wk | Quality and/or ~28× cost |
| **BL-78** | Invoice-as-diff + passive cost capture | ~2 wk | Variance is a label |
| **BL-12** | Int8 quantization + on-disk Qdrant index | days | ~4× storage cut |
| **BL-24** | Operator Copilot (voice, offline-first), CA-resident only | ~4 wk | Blocked on residency |
| **BL-10** | Conformal prediction sets at SAFETY_GATE | 1–2 q | Feeds BL-74 band |
| **BL-11** | Deterministic procurement compatibility filters | | Partly blocked on OPEN-1 |
| **BL-25** | Coordinator Agent (outbound) with INV-13 guardrails | ~4 wk | Highest legal exposure; last |
| **BL-13** | *(legacy v4 ID, restored)* Per-contractor ticket assignment (DEC-22): `contractor_id` on ticket, assignment action in operator UI, contractor list filtered to assigned tickets | days | Pilot is org-scoped visibility; needed once orgs run multiple crews |
| **BL-15** | ⚠️ partial *(legacy v4 ID, restored)* — Postgres rate limiting ✅ 2026-07-13. **Remaining:** R2 presigned PUTs get a server-enforced body-size condition — declared `content_length` is advisory today | days | Single-worker pilot is safe; bites when a hostile client PUTs oversized bodies |
| **BL-23** | *(legacy v4 ID, restored)* Mid-run evidence injection: photos/messages arriving while a run is in flight feed DIAGNOSE as new evidence. Touches the single-resume-path rule — needs its own design pass before any code | 1–2 w | Do NOT bolt onto the resume path ad hoc. Until then mid-chat photos land in media + transcript only (BL-22, §6.1) |
| **BL-80** | Structured interview at INTAKE + interview/CLARIFY separation (DEC-31; Intake Spec §4 protocol on the existing text intake). Reissued from the v8 draft's colliding BL-18 — old BL-18 is ✅ §6.1 | ~2 wk | The interview is the evidence-quality lever; cited by Delivery Spec §9.3/9.4 |
| **BL-79** | CI-driven deploys (DEC-27): replace the pilot's script + `compose up -d` with a CI pipeline (build → invariant tests against the containerized stack → push image → deploy). Pilot deploys stay manual and inspectable by decision | days | Post-pilot; reissued from uncommitted ex-BL-24 |
| **BL-33** | ⏸ Realtime video mode | deferred | CA-resident realtime + unit economics |
| **BL-34** | ⏸ Technician-side capture (phone → wearable, Mann) | deferred | After the professional-user path is proven |
| **BL-61** | ⏸ Structured bid collection + comparison portal | deferred | A month of work for a workflow we haven't watched anyone perform. Track responses as received first (DEC-74) |
| **BL-26** | ⏸ Cross-network federation + portable performance | deferred | 3 networks + the §10.1 data clause |
| **BL-7** | ⏸ Region-level evidence grounding | deferred | Post-traction audit upgrade |
| **BL-8** | ⏸ DuckDB/Parquet analytics split | deferred | `job_event` + video trigger this first |
| **BL-14** | ⏸ *(legacy v4 ID)* Per-node timestamps in the ledger (node-level instrumentation feeding `ticket_event`) | deferred | Audit-artifact nicety; ledger events share the run-completion timestamp, ordered by `seq` |
| **BL-16** | ⛔ closed 2026-07-29 *(legacy v4 ID)* — Nova voice mode: **superseded by BL-24 (Operator Copilot) and BL-36 (voice+video session)** | closed | Closed with reason, kept as history; never reuse |

### 6.1 Completed (IDs preserved — load-bearing history; never reuse)

| ID | Delivered |
|---|---|
| **BL-1** | ✅ 2026-07 — BGE cross-encoder reranker (`adapters/bge_reranker.py`) wired into fusion; self-hosted default until DEC-29 lean mode selected Bedrock Cohere Rerank by config |
| **BL-2** | ✅ 2026-07 — `PlattCalibrator` default + gated `IsotonicCalibrator` (`adapters/platt.py`); the `calibrated_confidence` source (INV-4) |
| **BL-4** | ✅ 2026-07 — Complexity routing in TRIAGE: VLM triage (verify tier) with deterministic INV-1 fail-safes, fast/full path split (`graph/nodes/triage.py`, DEC-21) |
| **BL-6** | ✅ 2026-07 — Claim-level VERIFY: real `EvidenceChunk.text` into entailment, per-type thresholds, claim persistence (DEC-6/19) |
| **BL-17** | ✅ 2026-07-13 — H1 async pipeline: intake + clarify-answer POSTs return instantly; background runner drives the graph (never reintroduce sync calls — mobile Safari ~60s cap) |
| **BL-18** | ✅ 2026-07-13 — H2 work-order persistence: `persist_completion` shared by runner + recovery |
| **BL-19** | ✅ 2026-07-13 — H3 serving hardening bundle: graph init in lifespan, checkpointer pool, startup recovery |
| **BL-20** | ✅ 2026-07-13 — H4 timestamp source consistency: DB clock everywhere; guarded by `tests/invariants/test_timestamp_defaults.py` |
| **BL-21** | ✅ 2026-07-13 — H5 tenant-facing error UX (`web/src/errors.ts`): 4xx/5xx/network copy that never lies about whether a submission landed |
| **BL-22** | ✅ 2026-07-13 — Mid-chat photo attach (DEC-26): status-link presign + `…/messages` accepts photos; media pointers (INV-3) + transcript rows |

*(BL-13, BL-15 remainder, and BL-23 are open and restored in the table above. BL-14 and BL-16 are ⏸ deferred, above.)*

---

## 7. Anti-Goals (❌ do not build — rationale recorded so they aren't relitigated)

**Retrieval & models:** ColBERT-for-BM25 swap (DEC-10) · domain fine-tuning now (DEC-15 — the
circulated "LightLLM4FDD 99.8%" figure is **unsubstantiated**; real source is a GPT-3.5 fine-tune on
clean single-AHU benchmarks; **do not cite it**) · raw BMS time-series as text (DEC-16) · full PILLM
verification · model self-reported confidence (INV-4) · constrained decoding as verification (INV-8) ·
**parsing a truncated model response (INV-19)** · **consuming a vendor's own extracted fields,
summaries, or sentiment (INV-17)** · **live web grounding inside any agent reply** (an agent citing a
search result sounds exactly like an authoritative diagnosis — INV-9/INV-4, and INV-2).

**Architecture:** blobs in Postgres (INV-3) · graph DB for parts now (DEC-13) · full BMS/BACnet
integration (INV-7) · broad LangChain surface (DEC-1) · cloud warehouse before DuckDB is exceeded
(DEC-4) · **a third graph or a second resume path in either graph (INV-12)** · **read-then-insert on
any natural key with concurrent writers** · **defaulting an unknown speaker role (DEC-61)** ·
**monitoring a safety-critical classifier on events rather than failure rate (INV-20)** · non-Canadian
services processing ticket content (INV-2) · **realtime video streaming to a non-CA-resident model
(DEC-46)** · Twenty Cloud or any hosted CRM outside Canada (DEC-49) · **diagnostic or dispatch logic
inside Twenty's Skills & Agents framework** · treating Twenty as source of truth for any flywheel
object.

**Product & safety:** customer-facing materials lists (INV-9/DEC-32) · system-set prices ·
**confirming a repair, quoting, or naming a fault before `SAFETY_GATE` (INV-16)** · **silently
keeping a visit when `SAFETY_GATE` escalates** · **a video agent that states a fault, cause, part,
price, or repair instruction (INV-14)** · **instructing a requester outside the permitted-actions
allow-list** · **continuing a live session after a hazard signal (INV-15) — no user override** ·
contractor-visible ratings (DEC-36) · merchant of record (DEC-39) · reselling parts or claiming
supplier savings · **autonomous outbound send without ladder promotion** · payroll, fleet telematics,
warehouse inventory, construction PM (ServiceTitan's swamp) · a fourth focus trade before three
corpora exist · **soliciting any contractor on an organisation's behalf without a named approver
(INV-21)** · **pricing an RFQ — the bidder prices it (DEC-72)** · **parts/SKU lists inside an RFQ;
scope is itemised by task** · **multi-site portfolio management, procurement-system integrations, or
capital planning** — commercial is a fork, not a second product (§1.1.1) · **voice cloning of any real
person — contractor, staff, or anyone, with or without consent (INV-22a / DEC-79)** · **an agent that
claims or implies it is a human** · **surfacing an owner's or employee's personal name as the
assistant's identity (DEC-80)** · **letting a contractor configure what the agent asks,
escalates, or permits a requester to touch** — protocol is Hero's, identity is theirs (INV-22b) · **requiring live video to file a ticket** — it is an option, never a
gate (DEC-75) · **treating fewer hazard signals in photo mode as fewer hazards (DEC-76)** ·
**exporting a cloned voice model** (INV-22c) · **storing transcripts, recordings, or message
bodies with Twilio or ElevenLabs** — transit only (DEC-81) · **sending requester speech to a
non-CA-resident ASR** (DEC-81) · **an ingestion mapper that invents task codes** (DEC-84) ·
**showing a requester a network price band** (DEC-85) · **computing a band from fewer than 5
vendors** (DEC-86).

**Go-to-market:** **open consumer marketplace or paid demand acquisition (DEC-35)** — Angi's grave:
the same lead sold to multiple pros destroys pro trust, pros churn, fulfilment collapses; 2025 revenue
≈ half historical peak · **a browsable contractor directory or cross-contractor search (DEC-67)** ·
**bespoke or hourly design work — sites are productized setup, never a services line (DEC-65)** ·
calendar integration as the source of truth for capacity (DEC-53) · requiring an account or login to
view a Scope Report · any feature that removes trips but produces no label.

> **v7 reversal, recorded:** v5/v6 anti-goaled "SEO services, ad management, website builds,
> before-after animation" as agency commodity. **Struck.** The reasoning held for a generic startup
> and not for this team — the founder's background (agency copywriting on major consumer accounts,
> seven years of cinematography, existing animated-website and scroll-animation tooling) means what
> ships is not what a freelancer ships, and Tyler requested it unprompted. Replaced with the narrower
> bound above: productized, never hourly.

---

## 8. Competitive Context

**Incumbent FSM/PM software.** Yardi Maintenance IQ, AppFolio Realm-X, Entrata ELI+ (100+ embedded
agents, Mar 2026), Haven, Property Meld, Latchel. Jobber ships AI Receptionist, Voice, Rewrite,
auto-drafted quotes. ServiceTitan ships Atlas, Field Pro, Titan Intelligence.

**Every diagnostic-adjacent surface in both stacks sits *after* dispatch.** Atlas and Field Pro assist
a tech already standing in front of the equipment. Neither diagnoses before the truck rolls. Neither
derives a scope from a customer complaint. **Neither takes live video from the requester.**

**Managed-network prior art:**

| Attached to the supply chain | Independent marketplace |
|---|---|
| **Motili** — Daikin-owned; 2,000+ contractors, 1,000+ distribution centres | **Angi** — 2025 revenue ≈ half peak; pro churn on lead quality |
| **Alert Labs** — Kitchener ON; acquired by Watsco, 2018, on ~$30K raised | **Thumbtack** — survived via repeated pivots; roadmap includes IoT-alert-to-service-request |
| **Dispatch** — Vista-backed; 40,000 providers; licence + insurance verification | |

**Infrastructure attached to distribution compounds; independent marketplaces bleed.** HVAC-first
(DEC-43) makes Hero legible to exactly the channel that acquired Alert Labs and built Motili.

**What none of them have:** (a) manual-grounded evidence chains with a full audit trail,
(b) contractor-confirmed outcome labels, (c) a Canadian-resident stack, (d) a scope manufactured
before dispatch, (e) live guided video capture from the requester, (f) **full-funnel attribution from
first visit to labeled outcome (§1.2)**. Defend all six in every PR.

**Standing risks:** incumbent bundling · unclear ROI ownership · moat pointed at engineering rather
than data (BL-0 is the answer) · **Dispatch already owns registry + matching** — they route tickets,
we manufacture them. Do not drift onto their side of that line.

---

## 9. Data Flywheel

`ContractorStatement ⋈ Diagnosis` improves, in order: **calibration** → **retrieval** →
**parts-matching** → *(long-term, DEC-15)* **domain fine-tuning**.

**Label sources**, all secondary to `ContractorStatement`, none replacing it: truck manifest edits ·
scope variance at `INVOICE` · agent edit rate · match overrides · nameplate OCR corrections ·
keyframe-selection quality · **party_attribute observations with provenance**.

Every resolved ticket must produce a usable label or an explicit `unlabeled_reason`. Likewise every
`job_event` (INV-11). **Every diagnostic visit produces a label whether or not a repair follows
(DEC-51)** — the single biggest improvement to label velocity in the roadmap.

**Trigger conditions:** >1,000 confirmed outcomes → isotonic (DEC-5) · recall@10 >95% on held-out
manuals → shift focus to verification · large labeled partner dataset → fine-tuning and time-series
move up · three networks live → federation (BL-26) · CA-resident realtime inference → BL-33.

---

## 10. Go-to-market model (constrains architecture)

### 10.1 Closed networks, not an open marketplace (DEC-35)

A **network** = one coordinator + their captive supply base.

| Network type | Example | Supply base |
|---|---|---|
| PM firm | Farid — 23 buildings | 6–7 vendors |
| General contractor | Tyler | a handful of subs |
| **Multi-location service co. / roll-up** | **Christian's network** | **own crews across acquired opcos** |

None has a demand problem. All have a matching-and-latency problem — Farid's response time is 1–3
days and the constraint is *"who's at the desk at that given time,"* not diagnostic difficulty.

Schema consequences: no cold start (first registry is 6–10 providers, onboarded by phone) · no
consumer acquisition spend · **`org_id` is a network, not a company** · **provider ↔ network is
many-to-many from migration 1**.

> **⚠️ Migration-1 cluster — all expensive to retrofit, do them together:** provider↔network
> many-to-many · `party_identifier` (DEC-63) · `ticket.building_id` → NULLABLE with `equipment_id`
> as the primary join (DEC-44; backfill before the ALTER) · `site` + `party_role` (DEC-73) ·
> **`task_taxonomy` + `network_id` on catalogue and case tables (DEC-82/86)** — the taxonomy is the
> join key for everything downstream, and retrofitting it across a populated catalogue and case
> history eats a month.

> **⚠️ Contract requirement, from contract one.** Vendor **performance** data is Hero's to aggregate
> in de-identified form. The vendor **relationship** and commercial terms remain the coordinator's.
> Without this clause there is no federation (BL-26) and no platform — only a dispatch tool for one
> company. Nearly impossible to retrofit. **Legal review before the first signed pilot.**

### 10.2 Who pays

| Persona | Outcome bought | Pays? |
|---|---|---|
| Coordinator (PM firm) | Nothing waits on a desk | **Yes — primary** |
| General contractor | Scope growth never becomes my fault | **Yes** |
| **Service co. / roll-up** | **Revenue per truck per day** | **Yes — enterprise** |
| Trade contractor (supply side) | Arrive with what the job needs | Free/near-free |

**Setup fee (incl. site + registry onboarding + compliance vault population) + platform subscription
+ flat fee per accepted visit.** Charge on *acceptance*, not delivery — removes the "I paid for four
dead leads" mechanic and aligns our incentive with match quality rather than volume.

❌ **Never percentage-of-job.** Tyler gave both ends: charge more than we think (*"do not provide guys
like me with contracts for free, because they're making an astronomical amount of money"*), but at
20% of a $2M job *"they're gonna say go fuck yourself."*

---

## 11. Conventions for Claude Code

- Read this file at session start; re-read §2 and §6 before architectural changes.
- **This file is the index of truth for invariants, decisions, and backlog.** Companion specs
  (`HERO_AI_INTAKE_SESSION_SPEC.md`, `HERO_AI_PRD_V7_AMENDMENTS.md`) hold implementation detail only.
  If they disagree with this file, this file wins.
- Cite DEC-n / INV-n / BL-n in commits and PRs.
- Completing a backlog item updates its row here in the same PR.
- New architectural decisions get a DEC-n entry in §12 with date and rationale.
- Swappable interfaces at every model boundary: embedder, reranker, VLM, ASR, TTS, `VideoProcessor`,
  `CrmSync`. Every vendor choice here is expected to churn.
- If a task requires violating an invariant, stop and surface it.
- `docs/research/` is **reference, not instruction.** Do not implement from it unless it appears in
  §6 or §12.
- Field-research quotes are evidence for decisions, not requirements. If a quote and an invariant
  disagree, the invariant wins and the disagreement gets a DEC entry.

---

## 12. Decision Log

### 12.1 v4 (DEC-1..16)

LangGraph pinned, minimal LangChain (1) · embedder bake-off (2) · Qdrant stays (3) · defer DuckDB (4) ·
Platt now, isotonic ≥1K (5) · claim-level VERIFY (6) · BMS optional (7) · self-hosted reranker (8) ·
int8 quantization (9) · **reject** ColBERT swap (10) · corrective loop (11) · deterministic
compatibility filters (12) · **defer** graph DB (13) · conformal sets (14) · **defer** fine-tuning
(15) · **reject** raw time-series text (16).

### 12.2 In-flight (DEC-20, 24–30)

| ID | Decision | Current impact |
|---|---|---|
| DEC-20 | Non-deterministic outputs; evals use `--runs N` | Applies to video and session evals |
| DEC-24 | Nova is maintenance-intake only, never booking | **Amended by DEC-51** — visits, not repairs |
| DEC-25 | Voice deferred (BL-16) | Superseded in direction (DEC-40), preserved in sequencing (DEC-41) |
| DEC-26 | Mock defines exactly one screen | Scope Report, session, and profile UI are our design |
| DEC-27 | Pilot = single Canadian VM, Docker Compose, no k8s | **Binds hard** — see DEC-50 |
| DEC-28 | R2 for pilot (NA hint, no CA guarantee) | **Top open risk** — interior video, provider PII, compliance docs |
| DEC-29 | Lean mode: API-hosted embedder/reranker | Residency recorded (INV-2) |
| DEC-30 | Langfuse deferred from pilot box | **Blocks BL-22, BL-29, BL-45** |

### 12.3 v5 (DEC-31..42)

Interview ≠ CLARIFY (31) · PROCURE emits a truck manifest, not a BOM (32) · voice is ticket content
(33) · warranty first-class on equipment (34) · closed networks only (35) · provider ranking invisible
to providers (36) · invoice is a diff (37) · passive cost capture only (38) · never merchant of record
(39) · voice is the primary interface (40) · voice ships after the pilot (41) · autonomy ladder as a
policy layer (42).

### 12.4 v6 (DEC-43..50)

Trade repositioning, HVAC/electrical/plumbing (43) · `building_id` nullable, `equipment_id` primary
join (44) · video session is not a graph (45) · processor-first, not realtime; video is ticket content
(46) · nameplate identity is the first processor (47) · Twenty is engagement, Hero is record (48) ·
Twenty self-hosted CA only (49) · Twenty and video land after the deploy gate (50).

### 12.5 v7 (DEC-51..68)

| ID | Decision | Rationale |
|---|---|---|
| DEC-51 | **Confirm a diagnostic visit in-session; the on-site diagnostic produces the job.** Amends DEC-24. | Maps to a primitive contractors already sell and charge for ($199–$249). Smaller commitment converts better and needs a much smaller gate. **Every visit produces a label** |
| DEC-52 | Voice loop never blocks on a VLM; agent reasons over `CaptureState` | Only way to hit <700ms while honouring DEC-46 |
| DEC-53 | **Capacity model, not calendar integration.** Calendars are a projection of `visit` | Most target providers have no calendar. Shane: *"I don't have any specific software or anything"* |
| DEC-54 | Delivery is SMS (link) + email (full) + CRM record; no-login signed page; model number in the SMS body | Shane reads texts on a ladder; the office reads email; the coordinator lives in Twenty |
| DEC-55 | **Pre-flight triage is a standalone classification, not a graph state**, reusing `safety/hazards.py` | Gates a real appointment in <2s without a second resume path (INV-12). Shared modules mean it cannot disagree with `SAFETY_GATE` unsafely |
| DEC-56 | **Two scope artifacts: `preliminary` and `confirmed`.** Quotes only from `confirmed` | Keeps INV-9 clean — the remote artifact never claims authority the professional hasn't granted |
| DEC-57 | Webhooks verify → enqueue → ack; per-route body caps pre-buffer; signature scheme verified against vendor docs | Vendors retry on slow acks; work in the request path causes a self-inflicted retry storm |
| DEC-58 | Queue separation by "is a human waiting?" | The <700ms budget makes this mandatory; expensive to retrofit once tasks exist |
| DEC-59 | Failed-and-notified bar; terminal vs transient in the type system; stage-first ledgers | Terminal failures otherwise burn every retry; stage-first is the only mechanism that makes loss observable |
| DEC-60 | Message coalescing, **strictly below** hazard classification | INV-15 runs per message before batching |
| DEC-61 | Per-turn transcript validation; **unknown speaker dropped, never defaulted** | A call is unrepeatable evidence; misattribution becomes evidence feeding DIAGNOSE |
| DEC-62 | Vendor-hosted agent config reconciled from the repo, CI drift check | The phone personality forks from the text personality the moment anyone edits the dashboard |
| DEC-63 | **`party_identifier` identity layer + conversations as first-class objects** | Without resolution the registry fragments and `provider_metric` accumulates against ghosts |
| DEC-64 | Confidentiality guard: resolved party ≠ stored party → refuse write, dead-letter | In a network where provider terms are confidential (§10.1), cross-filing is a breach, not a bug |
| DEC-65 | **Websites are a productized acquisition channel, never a services line.** Templated, fixed-price, Hero-hosted, bundled into setup | Founder capability makes this a genuine differentiator, not commodity work — but hourly design work becomes an agency and services revenue discounts hard on multiple |
| DEC-66 | **Hero is a web app with pluggable entry points, not a widget.** Mount order: plain link → launcher script → native | Contractor sites are Wix/Squarespace/GoDaddy; a JS embed breaks on those and it's our fault at 7am. One session implementation, CA-hosted, keeps INV-2 clean |
| DEC-67 | **Hosted profile pages, direct-link only, non-indexed, no cross-contractor search** | Solves Tyler without a website and displays verified licence/insurance nobody else holds. The moment there's a "find a plumber near me" page we've started building Angi by accident (DEC-35) |
| DEC-68 | **White-label by default**, minimal "powered by Hero" attribution | Trust in home services is local and personal; we have no consumer marketplace, so we need no consumer brand |

### 12.6 v8 (DEC-69..74) — client class and the commercial fork

| ID | Decision | Rationale |
|---|---|---|
| DEC-69 | **`client_class` (residential \| commercial) classified at `TRIAGE`.** Residential is the default and the primary path. | Hero serves anyone a home-services contractor serves, not just multi-unit buildings. Everything upstream of `PRELIM_SCOPE` is identical, including the safety gate — only the terminal artifact differs |
| DEC-70 | **Commercial terminal artifact is an RFQ, not a confirmed visit.** | A homeowner wants someone to come look; a commercial client is starting a procurement process and needs a document complete enough to bid against |
| DEC-71 | **`REQUESTER_APPROVE` gate before any solicitation leaves the building** (implements INV-21). Shares the residential `APPROVE` resume path. | The reporter is frequently not the decision-maker. Also preserves INV-12 — one guarded approval endpoint, two payload shapes |
| DEC-72 | **RFQ scope is itemised by *task*, never by *part*.** | Keeps INV-9 intact and is more clearly correct commercially — the bidder supplies parts and prices, which is the entire point of an RFQ |
| DEC-73 | **Site + party-role model: reporter / decider / payer are distinct.** | The interesting variable is not the building type. In a house those are one person; in a restaurant chain, four. This is what makes condo, rental, and commercial all work off one model |
| DEC-74 | **No bid portal in v1.** Contractors respond however they already respond; Hero tracks that a response arrived. | A month of work for a workflow we haven't watched anyone perform. BL-61 when there's evidence |

### 12.7 v8.1 (DEC-75..80) — modalities and the company assistant

| ID | Decision | Rationale |
|---|---|---|
| DEC-75 | **Three capture modalities — voice+video, voice+photos, text+photos — customer's choice, switchable mid-session. Agent behaviour identical in all three.** Live video is an option, never a requirement. | Forcing video kills completion rate, and completion rate is the metric the whole session is gated on. Photo mode also runs on today's stack with no residency blocker, so it ships first |
| DEC-76 | **Photo mode escalates hazards on weaker evidence, not stronger.** | The classifier has less signal — no continuous view, no motion, no audio of a hissing line. Fewer signals must never read as fewer hazards. BL-30 red-teams both modes separately |
| DEC-77 | **The Intake Agent presents as the company's assistant** — *"you've reached New Toronto Electric, I'm their assistant"* — in a neutral Hero voice, with the contractor's tone preset and stated policies. **Hero owns the protocol; the contractor owns the identity and policies.** | Trust in home services is local and personal (Tyler: *"who the fuck is coming into my house"*). The logical extreme of DEC-68. The split is DEC-62's rule: what the agent is trying to learn is Hero's; identity and delivery are theirs |
| DEC-78 | **Persona config lives in the repo, versioned, CI drift check.** Contractor-facing edits write through review, never around it. | Extends DEC-62. Config in a vendor dashboard forks silently, and here the fork carries the contractor's brand and the policies quoted to requesters — those are commercial commitments and must be auditable |
| DEC-80 | **The assistant is named for the registered business, never for an individual.** *"the assistant for New Toronto Electric"*, not *"Shane's assistant"*. Personal names surface only where the business name already contains one. | Four reasons: casually name-dropping an owner to a stranger is a privacy call that isn't ours to make; it misrepresents firms with partners or staff (Tyler works with Dimitri); it breaks the moment someone leaves or the business sells; and it reads wrong for anything above a two-person shop. The business name is also what's on the truck, the invoice, and the Google listing — it's the name customers actually recognise |
| DEC-79 | **No voice cloning of any real person, ever.** Not the contractor, not staff, not with consent. Reverses the v8.1 draft direction. | Four reasons, and the first two are sufficient: (1) a cloned trade voice stored in our database is a **fraud asset**; (2) the reputational failure is **asymmetric** — one wrong sentence in a contractor's own voice is unrecoverable, and Tyler named the dynamic exactly: *"one bad experience, gone"*; (3) it removes a biometric-consent, revocation, and PIPEDA surface entirely; (4) it takes TTS off the critical path — a neutral voice can be self-hosted, where cloning vendors are all US-hosted (INV-2/DEC-33). **The trust signal was always the name, not the timbre.** BL-64 withdrawn |


### 12.8 v8.2 (DEC-81..86) — vendors and the knowledge architecture

> Full detail: `HERO_AI_KNOWLEDGE_SPEC.md`

| ID | Decision | Rationale |
|---|---|---|
| DEC-81 | **Twilio and ElevenLabs are transit, never storage — and this is a recorded INV-2 *exception*, not compliance.** Twilio: body redaction on, recording disabled, media straight to R2. ElevenLabs: Enterprise + Zero Retention Mode + EU workspace, **TTS only**. | Neither offers Canadian residency (Twilio: US1/IE1/AU1; ElevenLabs: US/EU/India), and both caveat that processing may leave the selected region. Making them carry bytes and hold nothing is the only defensible posture. **Must be visible in a procurement review, not discovered in one** — pair with the DEC-28 R2 migration |
| DEC-82 | **A canonical `task_taxonomy` (`TRADE.SYSTEM.COMPONENT.ACTION`) is the join key for catalogue, case history, pricing, and matching.** Grows through review, never through inference. | Three vendors describe one job three ways. Without normalisation nothing joins — no price band, no cross-vendor learning, no contractor matching. **Migration-1 shaped.** ~200 codes cover most residential HVAC service; seed narrow and grow from ingestion |
| DEC-83 | **Three separate stores: manufacturer knowledge (Qdrant) · vendor catalogue (Postgres) · case history (Postgres + Qdrant).** RAG answers *"what is similar"*; SQL answers *"what exactly, how many, how much, who's eligible."* | Different owners, different query shapes, different confidentiality rules. Retrieve by similarity, aggregate by exact join — neither store alone is sufficient |
| DEC-84 | **Document ingestion (invoices, quotes, work orders) → line items → `task_code`, with a human review queue.** The mapper selects from retrieved taxonomy candidates and **may not invent codes**. Corrections write back to a learned alias dictionary. | Same discipline as parts (INV-9/DEC-32). Yields the onboarding demo — *"upload a year of invoices, get a working catalogue in an hour"* — and backfills case history, which Ryan identified as the lowest-risk ask of a design partner |
| DEC-85 | **Price bands are contractor- and coordinator-facing only. Never shown to a requester.** | Showing a customer the network median prices the job for the contractor — violates INV-9 and DEC-36's confidentiality logic in one move. Showing the *contractor* the same number is a competitive benchmark they'd otherwise guess at |
| DEC-86 | **Federation boundary in the schema from migration 1:** `network_id` everywhere · de-identification pass before a case enters the cross-network pool · **k-anonymity floor of 5 vendors on any price band.** | This is the §10.1 data clause made structural. A band computed from fewer than 5 vendors publishes one contractor's pricing to their competitor. Cannot be retrofitted |
| DEC-87 | **Cloudflare Workers AI hosts lean-mode embedding + reranking (`@cf/baai/bge-m3` / `@cf/baai/bge-reranker-base`) — a recorded INV-2 *exception*, not compliance.** Pilot-only. Migration target: the already-built Bedrock ca-central-1 adapters, behind the same Protocols. **Hard trigger mirrors DEC-28: BEFORE any procurement/compliance review and BEFORE the first paying customer.** | Workers AI has no Canadian residency commitment for ticket/manual text. Founder decision 2026-07-30: no AWS credentials available at deploy time; the Cloudflare account already existed (R2, DEC-28). Same bge model family as the BL-1 baseline keeps the DEC-29 eval gate meaningful. **Pairs with DEC-28 and DEC-81 in any procurement review** (numbered 2026-07-29 at deploy) |

---

## 13. Conflict resolutions — recorded so they aren't relitigated

| # | Conflict | Resolution |
|---|---|---|
| 1 | Voice stack vs INV-2 residency | DEC-33: voice is ticket content; CA-resident or self-hosted only |
| 2 | "No materials lists" (INV-9) vs PROCURE/SKU-lock | DEC-32: output becomes a contractor-facing truck manifest; *"orderable SKU"* restated as *"candidate part reference"* |
| 3 | Confidence bands vs INV-4 | Bands render `calibrated_confidence` only; non-singleton conformal set forces red |
| 4 | Auto-dispatch vs INV-1 | INV-10: hard-escalated tickets skip MATCH → HUMAN_HANDOFF. Covers the water-intrusion / $40K–$1M claim case |
| 5 | New approval gates vs single-resume-path rule | INV-12: two graphs, one resume path each; typed-event handoff |
| 6 | Two north stars | §1.2: label velocity (engineering) and trips removed (commercial), linked by rule |
| 7 | Voice-primary vs DEC-24/25 | DEC-40 direction, DEC-41 sequencing; Nova stays text through the pilot |
| 8 | Coordination plane vs single-org schema | §10.1: `org_id` is a network; provider↔network many-to-many from migration 1 |
| 9 | Commercial plane vs no financial objects | New tables behind the job graph; no v4 table modified |
| 10 | Autonomy ladder vs hard gates | INV-10: ladder governs convenience only; dispatch and money capped at L2 |
| 11 | Commodity features vs "no gold-plating ahead of label velocity" | BL-17 is the exception, justified on *access to labels*. Missed-call-text-back and review automation are **integrations, not builds** |
| 12 | Trade repositioning vs building-centric schema | DEC-44: `building_id` nullable; `equipment_id` primary join |
| 13 | Trade repositioning vs INV-7 rationale | Rationale *strengthens* — a detached-house furnace has no BMS at all |
| 14 | Video vs INV-12 (looks like a third graph) | DEC-45: bounded capture activity, no checkpointer, no resume path |
| 15 | Video vs INV-2 (all realtime vendors non-CA) | DEC-46: processor-first, keyframes only; realtime deferred (BL-33) |
| 16 | Video vs INV-4/INV-9 (live VLM narration sounds like diagnosis) | INV-14: no diagnosis may cite a live narration — only a persisted keyframe or transcript span |
| 17 | Video vs INV-1 (person following instructions in front of a hazard) | INV-15 + permitted-actions allow-list; BL-30 gates the feature |
| 18 | Video + Twenty vs DEC-27/29/30 (4GB box) | DEC-50: both land after the deploy gate on resized/second infra |
| 19 | Twenty vs "Postgres is source of truth" | DEC-48 boundary table (§4.9) |
| 20 | Twenty's Skills & Agents vs one pipeline | Anti-goal: Twenty renders, Hero decides |
| 21 | Twenty (Node/Yarn/GraphQL) vs a Python shop | API-level only; one app package, no business logic |
| 22 | Video artifacts vs INV-3 / DEC-28 | INV-3 extended; DEC-28 migration trigger to top of the risk register |
| 23 | Booking in-session vs DEC-24 | DEC-51: a visit is not a repair; language prompt-tested (BL-39) |
| 24 | Booking in-session vs INV-1/INV-10 | INV-16 + DEC-55: pre-flight gate, asymmetry rule, gate may upgrade the visit |
| 25 | Conversational voice + live video vs DEC-46 | DEC-52: processors are the eyes; VLM async on keyframes |
| 26 | "Contractor's calendar" vs providers with no calendar | DEC-53: capacity is the primitive; calendar is a projection |
| 27 | Remote scope vs INV-9 | DEC-56: remote artifact is explicitly `preliminary`; only `confirmed` can price work |
| 28 | Message coalescing vs INV-15 immediate interrupt | DEC-60: coalescing applies to interview turn policy only; hazard is per-message, pre-batch |
| 29 | Vendor "AI insights" (free, tempting) vs one extraction implementation | INV-17: vendor intelligence discarded; raw transcript only |
| 30 | Live grounding (IRIS pattern) vs INV-9/INV-4/INV-2 | Not imported. Anti-fabrication contract kept; grounding is corpus + ticket only |
| 31 | Autonomous send (IRIS pattern) vs autonomy ladder | Not imported. Compose machinery adopted; send authority enters at L1 |
| 32 | **Website/marketing anti-goal vs founder capability** | **v7 reversal (§7):** struck as written; replaced with productized-not-hourly (DEC-65). Reasoning held for a generic startup, not this team |
| 33 | **Profile pages vs DEC-35 (no marketplace)** | DEC-67: direct-link only, non-indexed, no cross-contractor search. The directory is the drift to guard against |
| 34 | **Commercial itemised scope vs INV-9 / DEC-32** ("no customer-facing materials lists") | DEC-72: RFQ is itemised by **task**, not part. The bidder supplies parts and prices. INV-9 intact, and more clearly correct here than residentially |
| 35 | **Commercial RFQ branch vs INV-12** (looks like a third graph) | DEC-71: it is a fork inside the job graph. `REQUESTER_APPROVE` shares the residential `APPROVE` resume path — one endpoint, two payload shapes |
| 36 | **Agentic solicitation vs organisational authority** | INV-21: no RFQ leaves the building without a named decision-maker approving. No default recipient — undirected RFQs stay in draft and notify a human |
| 37 | **Commercial scope vs "don't enter ServiceTitan's swamp"** | §1.1.1: commercial is a fork sharing the entire pipeline, not a second product. Multi-site portfolio management, procurement integrations, and capital planning stay anti-goals (§7) |
| 38 | **Named company assistant vs INV-13** ("self-identifies as an automated assistant") | INV-22: not in tension. *"You've reached New Toronto Electric, I'm their assistant"* is both the branding and the disclosure, in one sentence |
| 43 | **Twilio / ElevenLabs vs INV-2 residency** | DEC-81: transit-only, nothing stored with either. **Recorded as an exception, not compliance.** ASR self-hosted (the requester's actual words); TTS templated with no PII interpolated, enforced by tests |
| 44 | **Cross-vendor price bands vs §10.1 confidentiality** | DEC-85 + DEC-86: bands are contractor/coordinator-facing only, computed with a k≥5 vendor floor, never attributed |
| 45 | **Ingestion mapper vs INV-9** ("never invent") | DEC-84: the mapper selects from retrieved taxonomy candidates via constrained decoding. Unmatched lines go to a proposal queue, never a guessed code |
| 42 | **Personal name vs business name in the assistant's identity** | DEC-80: **business name only.** Casual name-dropping of an owner to a stranger; misrepresents firms with partners (Tyler/Dimitri); breaks on staff change or sale; wrong register for a large shop |
| 39 | **Contractor persona vs uniform safety behaviour** | INV-22b + DEC-77: Hero owns the protocol (questions, escalation, allow-list, visit language); the contractor owns name, tone preset, and policies. Contractor-specific safety behaviour is an anti-goal |
| 40 | **Voice cloning (v8.1 draft) vs fraud, reputation, and residency risk** | **DEC-79 reverses it: no cloning of any real person, ever.** BL-64 withdrawn. The name carries the trust signal; the timbre never did. Simplifies INV-2 (self-hosted neutral TTS) and removes the biometric-consent surface entirely |
| 41 | **Photo-only mode vs INV-15 hazard coverage** | DEC-76: photo mode escalates on *weaker* evidence. Fewer signals ≠ fewer hazards. Both modes red-teamed separately |

---

## 14. Schema `[SPEC]`

Additive except where noted. Full DDL in `HERO_AI_TECHNICAL_SPEC.md` §5.

```
-- v5: coordination + commercial
network · provider · provider_network (MANY-TO-MANY — migration 1)
provider_credential · provider_metric (never exposed to the provider — DEC-36)
job · job_event (IMMUTABLE ledger, INV-11 — append-only, enforced by GRANTS, tested by BL-42)
scope_report (kind: preliminary|confirmed; + band_calibrator_run_id — enforces INV-4)
truck_manifest · match_candidate · approval · autonomy_state · invoice · cost_entry

-- v6: trades + capture + CRM
equipment (make, model, serial, install_date, warranty_status, warranty_expiry, trade, location_ref)
ticket.building_id  -- ALTER: NOT NULL → NULLABLE (DEC-44; backfill BEFORE the ALTER)
ticket.equipment_id -- NEW FK, nullable; primary join for retrieval + history
capture_session (+ voice_enabled, turns_completed, protocol_covered[], preflight_result, terminated_reason)
capture_turn · capture_artifact · detection · live_hazard_event (append-only)
crm_sync_state · manual_chunk.doc_class

-- v7: visit + identity + delivery + distribution
provider_capacity · provider_blackout
visit (kind: diagnostic|scheduled_repair; state: confirmed|upgraded_escalation|cancelled|completed|no_show)
party_identifier (UNIQUE(type, value) — this constraint IS the concurrency control)
conversation · conversation_message · party_attribute (accumulate, never overwrite)
dead_letter
report_delivery (channel, recipient, sent_at, opened_at, signed_url_expires_at)
contractor_profile (slug, branding, review_source, verified_credentials[]) -- DEC-67, non-indexed
embed_config (provider_id, mount_type: link|script|native, allowed_origins[])

-- v8: client class + commercial fork
site (id, address, site_type, client_class,          -- DEC-69/73
      access_constraints JSONB,                       -- after-hours, escort, dock, elevator (BL-60)
      billing_entity_party_id)                        -- frequently ≠ requesting party
party_role (party_id, site_id, role)                 -- reporter | decider | payer | occupant
ticket.site_id       -- NEW FK; supersedes building_id as the location join
ticket.client_class  -- set at TRIAGE (DEC-69)
ticket_asset (ticket_id, equipment_id)               -- MULTI-ASSET (BL-59): "RTU-3 and RTU-5"
scope_report.kind    -- EXTEND: preliminary | confirmed | rfq  (DEC-70)
rfq (id, ticket_id, scope_report_id, requester_party_id, approver_party_id,
     approved_at, solicitation_mode,                  -- sole_source | competitive
     response_deadline, po_reference, vendor_requirements JSONB)
rfq_recipient (rfq_id, provider_id, sent_at, responded_at, response_ref)

-- v8.2: knowledge + catalogue (detail in HERO_AI_KNOWLEDGE_SPEC.md)
task_taxonomy       (task_code PK, trade, system, component, action, description,
                     typical_minutes_min/max, hazard_class, requires_licence_class,
                     parent_task_code)                    -- DEC-82, MIGRATION 1
task_alias          (task_code, vendor_id, alias_text, confidence, source)  -- learned dictionary
vendor_catalog_item (vendor_id, network_id, task_code, vendor_sku, vendor_label,
                     price_type, price_amount, price_min/max, labour_minutes,
                     source, confidence, observed_at, superseded_by)        -- accumulate, decay
case_record         (ticket_id, network_id, presenting_symptoms JSONB, symptom_narrative,
                     equipment_id, predicted_task_codes[], actual_task_codes[],
                     actual_cost, actual_hours, resolved_on_first_visit,
                     source, de_identified_at)                              -- the flywheel
source_document     (vendor_id, network_id, kind, object_key, classified_as, status)
document_line       (source_document_id, raw_text, qty, unit_price, total,
                     mapped_task_code, map_confidence, map_method, reviewed_by)
price_band          (task_code, region, p25, p50, p75, sample_size, computed_at)
                     -- CHECK (sample_size >= 5)          -- k-anonymity floor, DEC-86

-- v8.1: modalities + company assistant
capture_session.modality   -- voice_video | voice_photo | text_photo (DEC-75); switchable mid-session
capture_session.mode_changes JSONB                   -- audit of switches, incl. auto-degrade
contractor_assistant (provider_id, business_name,    -- registered business, NEVER a person (DEC-80)
                      tone_preset,                    -- warm | brisk | plainspoken (DEC-77)
                      greeting, signoff,
                      policies JSONB,                 -- diagnostic fee, flat-vs-hourly, exclusions,
                                                      -- service area, hours, callback wording
                      repo_version, drift_checked_at) -- DEC-78
-- NO voice_model_ref, NO biometric consent columns: cloning is an anti-goal (DEC-79)
```

**Migration cautions:**
- Never use string-literal `server_default="now()"` — constant-folds to migration time (fixed in 0009;
  invariant test rejects the string form).
- `job_event`, `live_hazard_event`, `dead_letter` are append-only. **Enforce with grants; BL-42 tests it.**
- The `building_id` nullability change touches existing rows — backfill before the ALTER.
- Migration-1 cluster: `provider_network`, `party_identifier`, `equipment_id` (§10.1).

---

## 15. Provenance & open evidence gaps

- v2–v3: narrative walkthrough → structured rewrite + SOTA review.
- v4: merged external architecture review (`docs/research/compass_architecture_review_2026-07.md`).
- v5: coordination/commercial/interaction layer. Sources: 4 contractor and operator ride-along
  transcripts, 17 market-content transcripts, competitive teardown of Jobber, ServiceTitan, Motili,
  Dispatch, Alert Labs, Angi, Thumbtack.
- v6: trade repositioning, video capture (Vision Agents), Twenty as system of engagement.
- v7: visit model, delivery/identity/reliability layer (architectural review of IRIS, Nvestiv comms
  layer, S. Hassan — patterns only, no code or vendors), distribution surface.
- **v8: client classes (residential primary, commercial fork) and the quote-request artifact.**
- **v8.1: capture modalities (live video optional) and the contractor's named assistant. Voice
  cloning considered and rejected (DEC-79).**
- **v8.2: telephony/voice vendor posture (Twilio, ElevenLabs — transit only, INV-2 exception
  recorded) and the knowledge & catalogue architecture (canonical task taxonomy, vendor catalogues,
  cross-vendor case history, document ingestion).**

**Open evidence gaps — do not treat v7 as settled:**
- **3–5 all-day HVAC and appliance ride-alongs not yet run.** The trades where the scoping thesis is
  strongest and must be tested. **The one question to ask every tech:** *"How many times this month
  did you go back for a part you didn't have?"*
- Baseline first-time-fix and parts-return rates unmeasured.
- Farid's historical work orders not obtained for the routing backtest.
- **Will a requester confirm a diagnostic visit at the end of a session?** Testable in ~2 weeks on the
  existing text intake (BL-35), before any voice or video work.
- **Will a requester complete a 5-minute guided video session?** Wizard-of-oz before BL-36.
  Completion rate is the gate.
- **Does the preliminary report change what a tech loads on the truck?** Measure parts-return delta
  from the first ten visits.
- Electrical and plumbing corpus viability is asserted, not measured (BL-27 + BL-3 report band
  distribution per trade before those trades are sold).
- **v8.1-specific: modality preference is unmeasured.** Offer all three from day one and watch what
  requesters actually pick — the split between video, voice+photo, and text+photo decides how much
  BL-36 is worth. Cheap to instrument on the existing text intake.
- **v8.1-specific: does a company-named assistant read as that company's?** *"You've reached New
  Toronto Electric, I'm their assistant"* in a neutral voice is the whole branding bet. Test it in the
  wizard-of-oz call — ask the requester afterwards which business they thought they were dealing with.
  One extra question, and it validates or kills DEC-77.
- **v8-specific: no commercial requester has been interviewed.** Every commercial assumption here —
  approval chains, bid comparison, response formats, PO handling — is inferred from Tyler's condo
  work and Farid's operations, not observed. **Interview two facility or office managers before
  building BL-58.** The residential path does not depend on this and should not wait for it.
