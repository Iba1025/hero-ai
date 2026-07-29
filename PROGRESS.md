# PROGRESS — Hero.AI phase tracker

> **Derived view.** The PRD §6 backlog is the index of truth; this file splits the work-order
> phases (WORK_ORDER_v8.2.md §4, as amended 2026-07-29) into trackable sub-components.
> **Update the relevant row in the same PR that completes a component** — same rule as §6.
> Last full refresh: **2026-07-30**.
>
> Legend: ✅ done · ⚠️ partial · 🔵 in progress · ⏳ not started · ⛔ blocked (blocker named) ·
> ⏸ deferred · 🚫 do-not-start guard active

## Scoreboard

| | count |
|---|---|
| ✅ complete | **13** — BL-1, 2, 4, 6, 17, 18, 19, 20, 21, 22, 42, 49, 81 |
| ⚠️ partial | **4** — BL-0 (ongoing, the moat), BL-3, BL-5, BL-15 |
| ⏸ deferred | **7** — BL-7, 8, 14, 26, 33, 34, 61 |
| ⛔ closed / withdrawn / unallocated | BL-16 (superseded) · BL-64 (DEC-79) · BL-38 (never use) |
| ⏳ open | **55** of 80 allocated IDs |

Phases 0–1 are where the action is; 2–4 are sequenced behind the deploy gate; 5+ is
**by explicit instruction only**.

---

## Phase 0 — Deploy gate 🔵 IN PROGRESS (blocking everything below)

| # | Sub-component | Status | Notes |
|---|---|---|---|
| 0.1 | Commit staged deploy artifacts (compose, docker/, deploy/, CI workflow, lean-mode adapters) | ✅ 2026-07-29 | PR #5 — was uncommitted for 15 days |
| 0.2 | Push tree to droplet + stage fixture manuals + pre-build images | ✅ 2026-07-29 | `push.sh` fixed for macOS openrsync (PR #6); hero-api 1.03GB + hero-caddy built on box |
| 0.3 | Server env (`make_server_env.sh`) | ⛔ **CLOUDFLARE_API_TOKEN (Workers AI permission) missing from dev-Mac `.env`** | Pivoted to Workers AI (founder decision 2026-07-30 — recorded INV-2 exception, **DEC number pending from founder**; adapters/config/deploy wiring shipped). Resume: `deploy/make_server_env.sh root@134.122.44.90 http://134.122.44.90` |
| 0.4 | `compose up -d --build` + `alembic upgrade head` on box | ⏳ | RUNBOOK §1 steps 3–4 |
| 0.5 | Corpus ingestion with `--embedder cloudflare` | ⏳ | CLI wired; manuals staged at `/opt/hero/data/manuals` |
| 0.6 | **The gate: e2e chat ticket through Caddy over `http://IP`** — diagnosis + safety gate + ledger row | ⏳ | Off-corpus tickets correctly escalate `diagnosis_unparseable` |
| 0.7 | DEC-29 eval gate: `run_eval.py --runs 3 --live` vs committed self-hosted baseline | ⏳ | Baseline in `evals/results/baseline_selfhosted_2026-07-14.log`; material regression stops the deploy |
| 0.8 | Phase 6 STEP 3 ops floor: backups **with restore drill** · uptime check · RUNBOOK verified | ⚠️ | RUNBOOK drafted (⏳ markers inline); backups/uptime not implemented — nothing to back up until 0.4 |
| 0.9 | HTTPS flip: domain + `ACME_EMAIL` + Caddyfile `SITE_ADDRESS` + R2 CORS + `AUTH_COOKIE_SECURE=true` | ⛔ domain (Inam) | After the loop; not a loop blocker |

## Phase 1 — Non-breaking hardening (Class A ✅ · Class B waits for the gate)

| Sub-component | BL | Status | Notes |
|---|---|---|---|
| Grant-hygiene invariant tests | BL-42 | ✅ 2026-07-29 | Real alembic chain into scratch DB; append-only checks enforced-if-present. **Role split → Phase 2 bundle** (amendment 6) |
| INV-12 single-resume-function test | (in BL-42) | ✅ 2026-07-29 | AST allowlist; job graph adds its one site in its own PR |
| Injection suites, current surfaces | BL-49 | ✅ 2026-07-29 | Nova guardrails + prompt rendering/TRIAGE floor. **Grows one suite per new agent surface, in that surface's PR** |
| Hazard phrase coverage + recall instrumentation | BL-81 | ✅ 2026-07-29 | 96-phrase corpus, 8 categories, 100% recall asserted; INV-15 monotonicity amendment |
| `docs/residency.md` (document) | — | ✅ 2026-07-29 | Bedrock/R2 rows + DEC-81 postures |
| Residency **startup guard** extension (config matches table, refuses to boot) | — | ⏳ Class B | After deploy gate |
| Stop-reason allowlist in LiteLLM adapter (INV-19) | BL-50 | ⏳ Class B | After deploy gate; `max_tokens` → documented constants |

## Phase 2 — Schema bundle ⏳ (highest risk; one coherent migration, after the gate)

| Sub-component | BL / DEC | Status |
|---|---|---|
| `task_taxonomy` + `task_alias`, HVAC-only seed (~200 codes from manual corpus) | BL-65 (schema half) / DEC-82 | ⏳ |
| `party_identifier` + E.164/email normalizer (tests FIRST) + race-safe-by-constraint + concurrent-writer test | BL-47 / DEC-63 | ⏳ |
| `site` + `party_role` (reporter/decider/payer) + `client_class` | BL-56 / DEC-69/73 | ⏳ |
| `provider` · `provider_network` many-to-many · `network_id` columns | §10.1 / DEC-86 | ⏳ |
| `ticket.building_id` → NULLABLE (**backfill before ALTER**, documented rollback) + `equipment_id`/`site_id` FKs | DEC-44 | ⏳ |
| `equipment` (+ warranty fields) | DEC-34 | ⏳ |
| **Append-only service-role split** (non-owner runtime role; BL-42 suite then binds) | amendment 6 | ⏳ |
| Gate: applies+rolls back on prod copy · all tests green · e2e still works · concurrency test passes | | ⏳ |

## Phase 3 — Job graph ⏳ (after Phase 2)

| Sub-component | BL | Status |
|---|---|---|
| Job graph (`PRELIM_SCOPE→…→CLOSE`), own checkpointer | BL-75 | ⏳ |
| `_JobResumeGuard` — **the** single resume path (one endpoint, two payload shapes) + INV-12 test allowlist update | BL-75 | ⏳ |
| `job_event` immutable ledger (INV-11, grants-enforced) | BL-75 | ⏳ |
| `DiagnosisReady` typed handoff (never a shared checkpoint) | BL-75 | ⏳ |
| Hard-escalated → skip MATCH → `HUMAN_HANDOFF` (INV-10); `COMPLETE` needs label or `unlabeled_reason` | BL-75 | ⏳ |
| Three-valued liveness + wedged-job sweep (in BL-75's DoD) + dead-letter hook + fail-closed config | BL-46 | ⏳ |
| Gate: ticket flows through both graphs · ticket-graph tests untouched · wedged job detectable | | ⏳ |

## Phase 4 — Commercial loop, text-first ⏳ (~7 wk; no video, no voice, no new infra)

| # | Sub-component | BL | Status | Blocked on |
|---|---|---|---|---|
| 1 | Capacity model + `visit` + confirm loop + reminders | BL-35 | ⏳ | BL-75 |
| 2 | Assistant identity: business name, tone preset, policies (INV-22, DEC-77/80) | BL-63 | ⏳ | — |
| 3 | Scope Report artifact (preliminary + confirmed) | BL-74 | ⏳ | BL-2 ✅, BL-1 ✅ — deps already met |
| 4 | Delivery: SMS + email + signed page + CRM record | BL-37 | ⏳ | BL-74 |
| 5 | On-site confirm/correct + three-way fork + `CONFIRMED_SCOPE` → **label velocity** | BL-41 | ⏳ | BL-74/37 |
| 6 | INV-16 visit-not-repair language, prompt-tested | BL-39 | ⏳ | with BL-35 |
| | Gate: requester scoped+confirmed over text · contractor gets report before window · on-site outcome writes `ContractorStatement` | | ⏳ | |

## Phase 5+ — by explicit instruction only 🚫 (do-not-start guard, HANDOFF)

Hard ordering constraints that survive any reprioritisation: **BL-36 needs BL-30+BL-40 first ·
BL-45 ships WITH BL-30 · BL-65 precedes BL-66/67/68/69 · BL-44 after BL-30.**

| Cluster | Items | Status |
|---|---|---|
| Knowledge & catalogue (order fixed: 65→66→67→68→69) | BL-65 seed/growth, BL-66 catalogue+decay, BL-67 doc ingestion (ColQwen reuse), BL-68 case history+de-id, BL-69 price bands k≥5, BL-70 eligible-contractor join | ⏳ (65's schema half lands in Phase 2) |
| Capture & safety | BL-62 photo-mode parity, BL-40 pre-flight, BL-30 live-hazard classifier + red team, BL-45 failure-rate monitors (WITH 30), BL-28 nameplate identity, BL-44 coalescing (after 30), BL-36 voice+video session | ⏳ — BL-81 ✅ laid the corpus/recall groundwork for BL-30 |
| Voice/telephony | BL-71 Twilio transit config, BL-72 self-hosted ASR + templated TTS, BL-24 Operator Copilot, BL-25 Coordinator Agent (last — highest legal exposure) | ⏳ (DEC-81 postures recorded in residency.md) |
| Commercial fork | BL-58 RFQ + INV-21 gate, BL-59 multi-asset, BL-60 site access constraints | ⏳ |
| Distribution | BL-52 profile page, BL-53 GBP booking, BL-54 embed script, BL-55 site template | ⏳ |
| CRM | BL-31 Twenty self-host + sync, BL-48 reconcile sweep, BL-32 report component, BL-51 conversations + timeline | ⏳ (blocked: deploy gate + DEC-50 capacity) |
| Trust/compliance | BL-73 compliance vault, BL-17-successor packet automation…, BL-21/76 provider registry, BL-43 insert-flag audit | ⏳ |
| Pipeline upgrades | BL-9 corrective loop, BL-10 conformal sets, BL-11 procurement filters, BL-27 trade corpus + `doc_class`, BL-12 quantization | ⏳ (BL-9/27 need BL-3's remainder) |
| Loose ends (open legacy + reissues) | BL-13 per-contractor assignment · BL-15 remainder (R2 body-size) · BL-23 mid-run evidence injection (design-first) · BL-79 CI-driven deploys (post-pilot) · BL-80 structured interview + interview/CLARIFY separation · BL-3 remainder (CI-gate, trade split, nova `--runs`) · BL-5 remainder (bake-off; **DEC-2 still open**) · BL-77 autonomy ladder (blocked on Langfuse, DEC-30) | ⏳ |

## Standing blockers on humans (from HANDOFF)

`AWS_BEARER_TOKEN_BEDROCK` (Phase 0.3, **the** current blocker) · domain name (0.9) ·
Antler credits (DEC-29 reversion trigger — don't optimise box shape until resolved) ·
`ACME_EMAIL` · #53 real-manual PDF (BL-27) · repo org+private migration · §10.1 legal review
before first signed pilot · GitHub ruleset vs missing CI contexts (admin-merge until fixed).
