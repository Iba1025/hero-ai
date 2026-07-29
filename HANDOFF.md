# Context Transfer — Hero.AI, as of 2026-07-27 (PRD v8.2)

> **Purpose:** session-handoff document for Claude Code. If a session compacts, dies, or a
> fresh one starts mid-deploy, read this first, then HERO_AI_PRD.md §2. Keep this file
> updated at every STOP gate.

## Summary

**Built and live-verified (unchanged since 2026-07-14):** Phases 1–5 — full diagnostic
pipeline (LangGraph, INTAKE→OUTCOME, async since H1), Nova chat tenant intake (yellow
retheme per the one-screen Figma mock, DEC-26), operator ledger, contractor outcome screen,
guardrails + nova evals, 394+ tests, mypy --strict, all invariants CI-enforced.

**Phase 6 (deploy) was IN PROGRESS at last update — VERIFY BEFORE ACTING.** Compose/Docker
artifacts staged, DO TOR1 droplet at root@134.122.44.90 (Ubuntu 24.04, 4GB, $32 tier, SSH
key from this Mac verified). Local Docker proof abandoned (~11GB free on this Mac) — STEP 1
proof runs on the droplet itself (DEC-27 amendment). *This section is 13 days stale; check
git log and droplet state before assuming.*

**New since 2026-07-14: planning only, nothing built.** PRD is now at **v8.2**, fully
consolidated — invariants INV-1..8 → **INV-1..22**, decisions DEC-1..30 → **DEC-1..86**,
backlog BL-0..12 → **BL-0..72**. **Everything added is `[SPEC]`. No new code exists.**
BL-38 unallocated; BL-64 withdrawn (voice cloning, DEC-79). Do not reuse either.

**A work order exists: `WORK_ORDER_v8.2.md`.** It carries the preservation boundaries, phase
gates, and stop conditions for implementing the above. **Read it before touching code — including
its 2026-07-29 Amendments section** (Class A/B runtime-change rule replacing the blanket Phase-0
gate; INV-12 counts resume functions not endpoints; corrected eval commands).

## STOP-gate update — 2026-07-29

- **Droplet verified (134.122.44.90):** up 15 days, ufw active (OpenSSH/80/443 only —
  firewall-first held), Docker 29.6.1 installed, `bootstrap.done` present — but **no compose
  project has ever been deployed** (`docker compose ls` empty; `/opt/hero` holds only an empty
  `data/` dir). No backups, no crontab, no `RUNBOOK.md`. **Phase 0 (deploy gate) is NOT passed;
  Phase 6 STEP 3 not started.**
- **Backlog reconciled** after the v5–v8 drafts unknowingly reissued repo-allocated IDs
  BL-13..24: committed IDs keep their meanings; colliding v8 items reissued as **BL-73..78**;
  CI-driven deploys reissued as **BL-79**. Full mapping in PRD §6's renumbering note. This file's
  references to BL-19/20/21/22 (Scope Report / job graph / provider registry / autonomy ladder)
  should be read as **BL-74/75/76/77**.
- **Eval baseline (2026-07-29):** 404 passed / 47 skipped, `mypy --strict` clean.
  `run_eval.py` supports `--runs N` (DEC-20 ✓); `run_nova_eval.py` does not (gap, not a blocker).

---

## ⛔ Do not start (guard — read before picking up any backlog item)

**The deploy gate comes first.** Per DEC-50, on the current single 4GB box in lean mode with
Langfuse dropped:

- **Do not start video capture (BL-29/36), Twenty (BL-31), or realtime video (BL-33).**
  They do not fit. They land after the Phase 6 deploy gate, on resized or second infra.
  Twenty's arrival likely forces the DEC-29 reversion conversation.
- **Do not start voice (BL-24/25/36).** DEC-41 sequences it after the pilot; DEC-33 blocks
  it on CA-resident ASR/TTS. *(DEC-79 dropping voice cloning does make neutral TTS
  self-hostable — Piper/Coqui class — so this is more tractable than it was, but still not
  before the deploy gate.)*
- **Do not implement BL-36 before BL-30 and BL-40.** A live session that confirms a real
  appointment does safety-critical classification in real time. Gates first.

- **Do not start knowledge/catalogue work (BL-65..70) before the schema bundle.** The
  taxonomy is the join key for catalogue, cases, pricing, and matching — everything joins
  through it and retrofitting it across populated tables eats a month.

**Safe to start now, in this order** (all cheap, none infra-dependent):
`BL-42` (grant-hygiene invariant tests, ~1 day) → `BL-50`/`BL-49` (stop-reason allowlist,
injection suites) → `docs/residency.md` + startup guard → then the Phase 2 schema bundle
per the work order.

**Work-order phases (WORK_ORDER_v8.2.md §4):** 0 deploy gate → 1 non-breaking hardening →
2 schema bundle → 3 job graph → 4 commercial loop text-first → 5+ by instruction only.

---

## Key Decisions (full log in HERO_AI_PRD.md §12 — these are the live ones)

- **DEC-27:** pilot infra = single Canadian VM, Docker Compose, no k8s/Terraform. Amended:
  proof runs on droplet.
- **DEC-28:** R2 stays for pilot media (NA hint, no CA jurisdiction guarantee); hard
  migration trigger before procurement review / paying customer. **Top open risk** — v6/v8
  add interior video, provider PII, and compliance documents.
- **DEC-29:** LEAN MODE — embedder+reranker are API-hosted adapters behind existing
  Protocols. Residency must be recorded in `docs/residency.md`.
- **DEC-30:** Langfuse deferred from pilot box; tracing no-ops when `LANGFUSE_*` unset.
  **Blocks BL-22 and BL-45** — autonomy edit-rate and failure-rate telemetry have no home.
- **DEC-24/25/26:** Nova is maintenance-intake only, voice deferred, mock defined exactly
  one screen. **DEC-51 amends DEC-24:** the agent may confirm a *diagnostic visit*, never a
  repair.
- **DEC-43:** repositioned from *building* maintenance to the **maintenance trades — HVAC,
  electrical, plumbing** (+ appliance). Equipment and trade replace the building.
- **DEC-45/46:** video is a bounded capture activity, **not a third graph**; processor-first
  + keyframes, **not** realtime streaming.
- **DEC-48/49:** Twenty is the system of **engagement**; Hero Postgres is the system of
  **record**. Self-hosted CA only.
- **DEC-63:** `party_identifier` omni-channel identity layer. **Migration-1 shaped.**
- **DEC-69/70:** `client_class` at TRIAGE. Residential → confirmed visit (primary).
  Commercial → **RFQ**, gated on a named approver (INV-21).
- **DEC-75/76:** three capture modalities; **live video optional**. Photo mode escalates
  hazards on *weaker* evidence, not stronger.
- **DEC-77/80:** the Intake Agent is **the company's assistant** — *"you've reached New
  Toronto Electric, I'm their assistant"* — named for the **registered business, never a
  person**.
- **DEC-79:** **no voice cloning of any real person, ever.** BL-64 withdrawn.
- **DEC-81:** Twilio and ElevenLabs are **transit, never storage** — and this is a recorded
  **INV-2 exception, not compliance.** Neither offers Canadian residency. ASR self-hosted;
  TTS templated with no requester PII.
- **DEC-82:** a canonical **`task_taxonomy`** (`TRADE.SYSTEM.COMPONENT.ACTION`) is the join
  key for catalogue, case history, pricing, and matching. **Schema-bundle item.**
- **DEC-83:** three separate stores — manufacturer knowledge (Qdrant) · vendor catalogue
  (Postgres) · case history (Postgres + Qdrant). RAG answers *"what is similar"*; SQL
  answers *"what exactly, how many, how much, who's eligible."*
- **DEC-85/86:** price bands are **contractor-facing only**, computed with a **k≥5 vendor
  floor**; `network_id` and de-identification are in the schema from the bundle, not later.

---

## Important Context (gotchas discovered, hard-won)

**Existing — all still binding:**

- Postgres string-literal `server_default="now()"` constant-folds to migration time —
  fixed in 0009, invariant test rejects the string form. Never reintroduce.
- BM25 sparse indices must use the stable hashlib tokenizer (builtin `hash()` is
  per-process random — silently dead for weeks). Integrity canary now guards it.
- Docker publishes ports BYPASSING ufw — only caddy may publish publicly.
- `AUTH_COOKIE_SECURE=false` until HTTPS flip, else cockpit login silently fails over http.
- Single resume path rule: clarify-answer endpoint is the ONLY ticket-graph resume; guarded
  by `_ResumeGuardedGraph`. Never add another without event capture.
- Sync-POST tenant flows time out on mobile (~60s Safari cap) — everything is async now
  (H1); never reintroduce a synchronous pipeline call in a request handler.
- Fixture corpus (3 fake ACME manuals, 9 pts) means off-corpus tickets CORRECTLY escalate
  as `diagnosis_unparseable` — known thinness, not a bug. #53 still pending. **BL-27
  expands this to a real per-trade corpus with a `doc_class` payload field.**
- Live model outputs are non-deterministic (DEC-20): evals use `--runs N`; latency FLAG is
  a trend gate (>2.5s avg across runs).

**New — will bite an implementer working from the specs:**

- **INV-12 — two graphs, two resume paths, no more.** The job graph (`PRELIM_SCOPE`→`CLOSE`)
  is separate and gets `_JobResumeGuard`; `APPROVE` / `REQUESTER_APPROVE` are **the same
  single endpoint, two payload shapes**. The video session and pre-flight triage are
  deliberately NOT graphs (DEC-45/55).
- **INV-15 outranks everything, including the debounce.** Hazard evaluation runs **per
  message, before any batching** (DEC-60). *"Wait I smell gas"* as fragment three of five
  must interrupt on arrival.
- **INV-16 — no repair commitment before the gate.** The agent confirms a *visit*
  ("a technician needs to come take a look"), never a repair. Prompt-tested (BL-39).
  Pre-flight may only ever be *more* conservative than `SAFETY_GATE`; where the gate
  disagrees, the visit is **upgraded to an escalation**, never silently kept.
- **INV-19 — never parse a truncated model response.** A truncated hypothesis list silently
  narrows the conformal set and voids BL-10's safety property with no error. One check in
  the LiteLLM adapter (BL-50).
- **INV-20 — monitor safety classifiers on failure *rate*, not events.** A dead API key
  degrading into "no hazard" for everyone shows every signal green. BL-45 ships *with*
  BL-30.
- **INV-21 — never solicit on an organisation's behalf without a named approver.** The
  reporter is frequently not the decider. No default recipient; undirected RFQs stay in
  draft.
- **INV-22 — the assistant is named for the business, never a person. No voice cloning.**
  Hero owns the protocol; the contractor owns identity and policies only.
- **Postgres grants EXECUTE to PUBLIC by default on new functions.** §14 claims
  `job_event`, `live_hazard_event`, and `dead_letter` are append-only "enforced by grants
  not convention" — **that claim is currently unverified.** BL-42 makes it a CI-enforced
  test (~1 day).
- **Migration-1 cluster — expensive to retrofit, do them together:** provider↔network
  many-to-many · `party_identifier` (DEC-63) · `ticket.building_id` → NULLABLE with
  `equipment_id` as primary join (DEC-44, backfill before the ALTER) · `site` + `party_role`
  (DEC-73).
- **Insert flags are not completion signals.** At every idempotent boundary (OUTCOME label,
  dispatch notify, requester confirmation, invoice, Twenty push, RFQ solicitation) ask
  whether the work happened by **querying state** (BL-43).
- **"Migration 1" in the specs does NOT mean migration `0001`.** We are past 0009. It means
  these items are expensive to retrofit and must land **together in one bundle**, because
  they are each other's foreign keys: `task_taxonomy` · `party_identifier` · `site` +
  `party_role` · provider↔network many-to-many · `network_id` · `building_id` → NULLABLE
  with `equipment_id`/`site_id`.
- **`PROCURE` is the only pipeline state whose output contract changes.** Retrieval logic
  stays; the output becomes a contractor-facing truck manifest (`confirmed_needed` /
  `likely_needed`), never a customer-facing priced parts list (DEC-32).
- **Twilio/ElevenLabs are exceptions, not compliance.** They must be visible in a
  procurement review, not discovered in one. Pair with the DEC-28 R2 migration — a reviewer
  will ask about both in the same breath.

---

## Relevant Files

- `HERO_AI_PRD.md` — **v8.1. The index of truth for invariants, decisions, and backlog.**
  Invariants §2 · state machines §3 · planes §4 · backlog §6 · anti-goals §7 · decision log
  §12 · conflict resolutions §13 · schema §14. **Read §2 before any change.**
- `HERO_AI_INTAKE_SESSION_SPEC.md` — **v3.** Requester-facing intake: assistant identity,
  three modalities, interview, pre-flight, visit confirm loop, delivery, on-site fork,
  drop-off analysis, build sequence.
- `HERO_AI_DELIVERY_SPEC.md` — delivery/identity/reliability implementation: webhook
  receivers, queues, failed-and-notified, coalescing, transcript validation, identity
  schema, DB practices, model-boundary practices.
- `HERO_AI_KNOWLEDGE_SPEC.md` — telephony/voice vendor posture (Twilio, ElevenLabs) and the
  knowledge architecture: three stores, canonical task taxonomy, vendor catalogues,
  cross-vendor case history, document ingestion, the retrieval loop, federation boundaries.
- `WORK_ORDER_v8.2.md` — **preservation boundaries, precedence, phase gates, stop
  conditions.** Read before any code.
- `HERO_AI_TECHNICAL_SPEC.md` — implementation spec; `[IMPL]` = built, `[SPEC]` = not.
- `CLAUDE.md` — commands, precedence rules.
- `FRICTION.md` — phone-run findings (verbatim, triaged BLOCKER/ANNOYANCE/NIT).
- `DEMO.md` — rehearsal script. `RUNBOOK.md` — pending (Phase 6 STEP 3).
- `docs/residency.md` — **required by INV-2 / DEC-29/33/46.** Every API-hosted adapter's
  residency recorded; startup guard asserts it. Create if absent.
- `docker-compose.yml`, `docker/*.Dockerfile`, `deploy/*` — staged, UNCOMMITTED until the
  droplet loop passes.
- `src/hero/interfaces/` + `src/hero/adapters/` — all model boundaries are Protocols.
  **v6+ adds `VideoProcessor` and `CrmSync` when those land.**

> **Superseded, kept for history only:** `HERO_AI_PRD_v5/v6_superseded.md`,
> `HERO_AI_INTAKE_SESSION_SPEC_v1/v2_superseded.md`,
> `HERO_AI_PRD_V7_AMENDMENTS_applied.md` (fully folded into the PRD).

---

## Current State

**Working:** everything, locally, live-mode, phone-tested end to end (Nova chat, photos,
CLARIFY, hazard escalation, ledger, contractor outcome).

**In flight (as of 2026-07-14 — verify):** lean-mode work order —
1. API-hosted embedder/reranker adapters (multivector hosting is the open question;
   dense+BM25 compromise needs an eval-gated delta),
2. compose slims to caddy/api/postgres/qdrant, <3GB steady-state target,
3. eval gate `--runs 3` vs self-hosted baseline BEFORE deploy,
4. full droplet sequence against 134.122.44.90, firewall-first, e2e chat ticket through
   Caddy over http://IP.

**Blocked on humans:** domain name (Inam) · Antler cloud-credits email (would trigger
DEC-29 reversion) · #53 real-manual PDF · repo org+private migration · **legal review of the
§10.1 vendor-performance data clause before the first signed pilot** (federation depends on
it and it cannot be retrofitted) · Saad courtesy note re: delivery-layer patterns sourced
from IRIS.

**Spec'd but unbuilt:** everything in PRD §4.5–4.13 — job graph, video session, visit model,
identity layer, delivery plane, commercial fork, distribution surface.

---

## Next

1. **Finish the deploy gate.** Nothing below starts until the droplet loop passes.
2. Domain + HTTPS flip (Caddyfile `SITE_ADDRESS` + R2 CORS swap + `AUTH_COOKIE_SECURE=true`).
3. Phase 6 STEP 3 ops floor: backups with restore drill, uptime check, `RUNBOOK.md`.
4. **Then the commercial loop, text-first** (Intake Spec §12, ~7 weeks, no video, no voice,
   no residency blocker, no new infra):
   `BL-35` capacity + visit → `BL-63` assistant identity → `BL-19`/`BL-37` report + delivery
   → `BL-41` on-site confirm/correct.
   Interleave the cheap hardening: `BL-42`, `BL-47`, `BL-49`, `BL-50`.
5. Then `BL-62` photo-mode parity → `BL-40` pre-flight → `BL-30`+`BL-45` hazard + monitors →
   `BL-28` nameplate identity → `BL-36` the session.

6. Then knowledge/catalogue: `BL-65` taxonomy → `BL-66` catalogue → `BL-67` document
   ingestion → `BL-68` case history → `BL-69` price bands.

**Before BL-36, run a wizard-of-oz video call** — manual script, real requester. Completion
rate under five minutes is the gate. Ask afterwards **which business they thought they were
dealing with** — that one question validates or kills DEC-77.
