# WORK ORDER — Hero.AI v8.2 Implementation

**Issued 2026-07-27 · Read this in full before writing any code.**

You are picking up an existing, working codebase. The specifications have changed substantially since
the code was written. **Most of the pipeline is correct and must survive untouched.** Your job is to
extend around it, not rebuild it.

---

## 0. Read in this order, then stop and confirm

1. `HANDOFF.md` — current operational state and the do-not-start guard
2. `HERO_AI_PRD.md` §2 (invariants) and §6 (backlog) — **the index of truth**
3. `HERO_AI_PRD.md` §13 (conflict resolutions) — decisions already litigated; do not reopen
4. `HERO_AI_KNOWLEDGE_SPEC.md` — taxonomy, catalogue, case history, ingestion
5. `HERO_AI_INTAKE_SESSION_SPEC.md` — requester-facing intake
6. `HERO_AI_DELIVERY_SPEC.md` — delivery, identity, reliability
7. `HERO_AI_TECHNICAL_SPEC.md` — `[IMPL]` = built, `[SPEC]` = not

**After reading, before any code:** produce a written summary of (a) what you believe must not
change, (b) the first phase's scope, (c) anything you found in the code that contradicts the specs.
**Wait for confirmation.** Do not begin work off your own summary.

---

## 1. DO NOT TOUCH

These are working, live-verified, and phone-tested end to end. Changing them is the primary risk in
this engagement.

### 1.1 The diagnostic pipeline — frozen

```
INTAKE → TRIAGE → RETRIEVE → [CLARIFY ⟲] → DIAGNOSE → VERIFY → SAFETY_GATE
       → { ESCALATE | RESOLVE → PROCURE → OUTCOME }
```

- **Graph topology.** Do not add, remove, reorder, or merge states.
- **`_ResumeGuardedGraph` and the single resume path.** The clarify-answer endpoint is the only
  ticket-graph resume. Adding a second is an INV-12 violation — **stop and flag instead**.
- **Async execution (H1).** Never reintroduce a synchronous pipeline call in a request handler;
  mobile Safari times out at ~60s.
- **The LangGraph Postgres checkpointer.** Do not bypass for "quick" paths (INV-6).
- **`VERIFY` and `SAFETY_GATE` logic.** Hard-category escalation is confidence-independent (INV-1).
- **Retrieval internals:** ColQwen multivector + BM25 RRF fusion. **The BM25 stable hashlib
  tokenizer must not change** — builtin `hash()` is per-process random and was silently dead for
  weeks. The integrity canary guards this; do not disable it.

### 1.2 Report generation — frozen in substance

The diagnosis → report path works. You may **add** the new artifact shape (§3.2 below); you may not
change how claims are grounded, how evidence is cited, or how confidence is derived.

**`calibrated_confidence` comes from the calibrator, never from a model (INV-4).** Any new band or
score you surface must trace to a calibrator run.

### 1.3 Existing schema and migrations

- **Do not rewrite existing migrations.** Additive migrations only.
- **Do not drop or rename existing columns** without an explicit instruction naming the column.
- `server_default="now()"` as a **string literal** is forbidden — it constant-folds to migration
  time. Fixed in 0009; the invariant test rejects it. Never reintroduce.

### 1.4 Tests and type checking

- **394+ tests must stay green.** They are the safety net for everything below.
- `mypy --strict` must stay clean.
- All existing invariant tests must keep passing. You may add invariant tests; you may not weaken one.

### 1.5 Deploy artifacts

`docker-compose.yml`, `docker/*`, `deploy/*` are **staged and uncommitted** pending the droplet loop.
Do not modify unless the task explicitly concerns deployment.

---

## 2. Precedence and conduct

**Document precedence:** `HERO_AI_PRD.md` > companion specs > code comments > your judgement.
If a companion spec disagrees with the PRD, the PRD wins and you flag the discrepancy.

**Invariants stop work.** If a task appears to require violating INV-1..22, **stop and surface it**.
Do not implement a workaround, do not implement a partial version, do not note it in a comment and
proceed.

**You do not legislate.** Do not invent new `DEC-n`, `INV-n`, or `BL-n` entries. If the work reveals
a decision that needs making, write it up as a question and stop. Numbering is issued by a human.

**Commits cite IDs.** Every commit message references the `BL-n` it advances and any `DEC-n` / `INV-n`
it depends on. Completing a backlog item updates its row in `HERO_AI_PRD.md` §6 **in the same PR**.

**Ask when ambiguous.** These specs were written fast and contain gaps. A wrong assumption
implemented cleanly is worse than a question.

**Research docs are reference, not instruction.** Do not implement from `docs/research/` unless it
appears in PRD §6 or §12.

---

## 3. What changes — and how much

### 3.1 Pipeline states that gain *additive* outputs

These states keep their existing logic. They emit an additional field or artifact. **No routing
changes for the existing residential path.**

| State | Addition | Notes |
|---|---|---|
| `INTAKE` | Accepts capture-session artifacts identically to photos | INV-14 — same endpoint, same status |
| `TRIAGE` | Emits `client_class` (`residential` \| `commercial`) | DEC-69. Residential is default; commercial routing is Phase 5 |
| `RESOLVE` | Emits `scope_report` with `kind='preliminary'` | New artifact alongside the existing work order |

### 3.2 The one output contract that genuinely changes

**`PROCURE`.** Retrieval logic stays exactly as-is. The **output shape** changes.

- **Was:** an orderable part / SKU
- **Now:** a contractor-facing **truck manifest** — `confirmed_needed[]` and `likely_needed[]`,
  two-tap editable, **never surfaced to a customer as a priced parts list** (INV-9, DEC-32)
- **Bias to recall.** A missed part is a second trip; an over-included cheap part is nearly free
- Every contractor edit writes a label

Keep the candidate retrieval and ranking. Reshape what leaves the state.

### 3.3 New surface — built *alongside*, not inside

None of this modifies the ticket graph:

- **Job graph** (`PRELIM_SCOPE`→`CLOSE`) — separate graph, own checkpointer, own `_JobResumeGuard`.
  Handoff is a typed `DiagnosisReady` event. **Never a shared checkpoint** (INV-12).
- **Capture session** — a bounded activity, **not a graph**. No checkpointer, no resume path
  (DEC-45).
- **Pre-flight triage** — a standalone classification reusing `safety/hazards.py`, **not a graph
  state** (DEC-55).
- **Identity layer**, **delivery layer**, **knowledge/catalogue layer** — new modules.

---

## 4. Phases and gates

**Do not start a phase until the previous gate passes and a human confirms.**

### Phase 0 — Deploy gate (BLOCKING)

Nothing below begins until the droplet loop passes and Phase 6 STEP 3 (backups with restore drill,
uptime check, `RUNBOOK.md`) is complete.

**If deploy work is not your assignment, stop here and say so.**

---

### Phase 1 — Non-breaking hardening

Pure additions. No schema changes. No behaviour changes. Zero pipeline risk.

| Task | BL | Definition of done |
|---|---|---|
| Grant-hygiene invariant tests | BL-42 | For every function: `REVOKE ... FROM PUBLIC`, `search_path` pinned, `EXECUTE` to service role only. For `job_event` / `live_hazard_event` / `dead_letter`: assert `UPDATE`/`DELETE` revoked. **Tests, not migrations** — a future migration that forgets must fail CI |
| Stop-reason allowlist | BL-50 | One check in the LiteLLM adapter. Non-STOP finish reason → raise, retry, dead-letter. **Never parse a fragment** (INV-19). `max_tokens` become documented constants with headroom |
| Injection suites | BL-49 | Per agent surface. Retrieved and inbound content is data, never instruction (INV-18) |
| `docs/residency.md` + startup guard | — | One row per API-hosted adapter: region · what data crosses · retention setting · mitigation · date reviewed. Startup guard asserts config matches (INV-2, DEC-29/33/46/81) |

**Gate:** all tests green, `mypy --strict` clean, an e2e chat ticket still produces a diagnosis.

---

### Phase 2 — Schema bundle (highest risk — one migration, carefully)

> ⚠️ The PRD calls these "migration 1" items. **This does not mean migration `0001`.** It means they
> are expensive to retrofit and must land **together in one coherent bundle**, because they are each
> other's foreign keys.

**Contents:**

```
task_taxonomy + task_alias                    -- DEC-82, the join key for everything
party_identifier                              -- DEC-63, UNIQUE(type, value)
site + party_role                             -- DEC-73
provider · provider_network (MANY-TO-MANY)    -- §10.1
network_id                                    -- on catalogue, case, provider tables (DEC-86)
ticket.building_id → NULLABLE                 -- DEC-44
ticket.equipment_id, ticket.site_id           -- new FKs
equipment (+ warranty_status, warranty_expiry) -- DEC-34
```

**Requirements:**

1. **Backfill before every ALTER.** `building_id` nullability touches existing rows — write and test
   the backfill first, in the same migration, with a documented rollback.
2. **`party_identifier` normalization is not optional.** E.164 via libphonenumber with channel-prefix
   stripping; lowercased email. Write the normalizer and its tests before the table.
3. **Race-safe by constraint, not by lock.** Two concurrent inserts race `UNIQUE(type, value)`; the
   loser adopts the winner's party. Test with concurrent writers.
4. **Append-only tables enforced by GRANTS**, verified by the BL-42 tests from Phase 1.
5. **`task_taxonomy` seeded HVAC-only, ~200 codes**, format `TRADE.SYSTEM.COMPONENT.ACTION`. Seed
   from the manual corpus procedures. Do not attempt exhaustive coverage.

**Gate:** migration applies and rolls back cleanly on a copy of production data · all tests green ·
e2e ticket still works · concurrency test passes.

---

### Phase 3 — Job graph

`PRELIM_SCOPE → MATCH → ASSIGN_VISIT → MOBILISE → VISIT → {resolved_on_site | needs_return | wrong_trade}`

- Separate graph, own checkpointer, `_JobResumeGuard`
- `APPROVE` is its **only** resume path
- `job_event` immutable ledger (INV-11) — append-only, grants-enforced
- Hard-escalated tickets skip `MATCH` → `HUMAN_HANDOFF` (INV-10)
- `COMPLETE` cannot exit without a label or `unlabeled_reason`
- **`resolved_on_site` is the happy path**, not an exception branch

**Does not touch the ticket graph.** The only integration point is consuming `DiagnosisReady`.

**Gate:** a ticket flows end-to-end through both graphs · the ticket graph's tests are untouched and
green · a wedged job is detectable via three-valued liveness.

---

### Phase 4 — The commercial loop, text-first

**No video. No voice. No new infrastructure.** Runs on the existing text Nova intake.

| Order | Task | BL |
|---|---|---|
| 1 | Capacity model + `visit` + confirm loop + reminders | BL-35 |
| 2 | Assistant identity: business name, tone preset, policies | BL-63 |
| 3 | Scope Report artifact + SMS/email/signed-page delivery | BL-19, BL-37 |
| 4 | On-site confirm/correct + three-way fork + `CONFIRMED_SCOPE` | BL-41 |

**Language is prompt-tested (BL-39).** The assistant confirms a **visit** — *"a technician needs to
come take a look"* — never a repair, never a price, never a fault (INV-16). It presents as **the
company's assistant** — *"you've reached New Toronto Electric, I'm their assistant"* — named for the
**registered business, never a person** (DEC-77/80). **No voice cloning, ever** (DEC-79).

**Gate:** a requester can be scoped and confirmed for a visit over text, the contractor receives the
report before the window, and the on-site outcome writes a `ContractorStatement`.

---

### Phase 5 and beyond — do not start without explicit instruction

Knowledge/catalogue (BL-65..70) · photo-mode parity (BL-62) · pre-flight (BL-40) · hazard classifier
and monitors (BL-30, BL-45) · nameplate identity (BL-28) · voice/video session (BL-36) · Twenty
(BL-31) · commercial fork (BL-56..60) · distribution surface (BL-52..55).

**Hard ordering constraints that survive any reprioritisation:**

- **BL-36 requires BL-30 and BL-40 first.** A live session confirming a real appointment does
  safety-critical classification in real time.
- **BL-45 ships with BL-30, not after.** An unmonitored safety classifier is a safety gap, not a
  partially-complete feature.
- **BL-65 (taxonomy) precedes BL-66/67/68/69.** Everything joins through it.
- **BL-44 (coalescing) ships after BL-30**, and sits strictly **below** hazard classification —
  INV-15 evaluates per message, before any batching.

---

## 5. Verification — every phase

Run before declaring any phase done:

```
pytest                          # 394+ green, no skips added
mypy --strict                   # clean
pytest tests/invariants/        # all green, none weakened
python -m hero.evals --runs 3   # DEC-20: never single-run point estimates
```

**Plus the smoke test:** submit a chat ticket end-to-end and confirm it produces a diagnosis, hits
the safety gate correctly, and writes a ledger entry. **If the smoke test fails, the phase is not
done regardless of unit test status.**

Note the fixture corpus is 3 fake ACME manuals (9 points). Off-corpus tickets **correctly** escalate
as `diagnosis_unparseable`. That is known thinness, not a regression — do not "fix" it.

---

## 6. Stop conditions

Stop immediately and ask if any of these occur:

- A task appears to require a second resume path in either graph (INV-12)
- A task appears to require bypassing `VERIFY` or `SAFETY_GATE` (INV-1, INV-10)
- A task appears to require model self-reported confidence (INV-4)
- A task appears to require sending ticket content to a non-CA-resident service (INV-2)
- A test must be weakened, skipped, or deleted to make something pass
- An existing migration must be edited
- The specs contradict each other and the PRD doesn't resolve it
- A change to the diagnostic pipeline's logic (not its outputs) seems necessary
- You are about to create a new `DEC-n`, `INV-n`, or `BL-n`

---

## 7. First response

Do not write code yet. Reply with:

1. **What you believe must not change** — in your own words, from reading the code, not from
   restating §1
2. **Anything in the code that already contradicts the specs** — this is the most useful thing you
   can tell me
3. **Your Phase 1 plan**, file by file
4. **Questions.** There will be some. The specs were written quickly.

Then wait.

---

## Amendments — 2026-07-29 (founder Q&A; these override the sections they name)

1. **§4 Phase 0's blanket "nothing begins" is replaced by a runtime-change rule.** The gate
   distinction is *does it change runtime behaviour*, not before/after deploy:
   - **Class A — test-only or doc-only, no runtime change** (BL-42 grant-hygiene tests, BL-49
     injection suites, `docs/residency.md` as a document): **start now**, safe mid-deploy.
   - **Class B — changes runtime behaviour** (BL-50 stop-reason allowlist raises where code
     currently parses; the residency **startup guard**, which can refuse to boot): **after the
     deploy gate** — a new fail-closed path mid-deploy makes a boot failure ambiguous.
   Residency splits across the classes: write the document now, wire the guard later.
2. **§1.1 clarified: INV-12 counts resume *functions*, not HTTP endpoints.** Exactly one guarded
   resume function per graph (`_ResumeGuardedGraph` for tickets, `_JobResumeGuard` for jobs).
   Multiple endpoints may delegate to the one guard. Practical test: grep for anything invoking a
   graph with a checkpoint config — two hits, one per graph; a third is an INV-12 violation.
   An invariant test asserting this ships inside BL-42's PR.
3. **§5 verification commands corrected:** `python -m hero.evals --runs 3` does not exist. Use
   `uv run python evals/run_eval.py --runs 3` and `uv run python evals/run_nova_eval.py`.
   DEC-20's requirement is only *never a single-run point estimate*; a shell loop satisfies it.
   Known gap (not a Phase 1 blocker): `run_nova_eval.py` has no `--runs` flag.
4. **§3.1/§4 backlog IDs:** this document cites pre-reconciliation numbers for the moved items —
   Scope Report BL-19→BL-74, Job graph BL-20→BL-75, Provider registry BL-21→BL-76, Autonomy ladder
   BL-22→BL-77, Invoice-as-diff BL-23→BL-78. See PRD §6's renumbering note.
