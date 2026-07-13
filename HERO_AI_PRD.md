# Hero.AI — Product & Architecture Context (PRD v4)

> **Purpose of this file:** Single source of truth for architecture, decisions, priorities, and invariants.
> Claude Code: read this before any non-trivial change. If a proposed change conflicts with an
> **INVARIANT**, stop and flag it. If it conflicts with a **DECISION**, cite the decision ID and ask.
> Update the `Decision Log` and `Backlog` sections when decisions change — this file must stay current.

**Last updated:** 2026-07-08 (v4: merged external architecture review — see `docs/research/`)
**Status legend:** ✅ CURRENT (keep as-is) · 🔄 UPGRADE PLANNED · ⏸ DEFERRED · ❌ ANTI-GOAL (do not build)
**Backlog IDs are stable identifiers; table order (not ID number) is priority order.**

---

## 1. What Hero.AI Is

AI-powered diagnostic + procurement operating system for building maintenance.
A ticket (tenant description + photos/video) enters; the system produces an **evidence-grounded
diagnosis**, a work order, an orderable part (SKU), and — critically — a **contractor-confirmed
outcome label** that feeds the data flywheel.

**Mental model:** a deterministic pipeline wrapped around non-deterministic models. The LLM thinks;
a state machine decides what happens next; every risky step passes a gate before anything acts.

**North star metric:** rate and cleanliness of `ContractorStatement` labels per week.
The pipeline is replicable by incumbents (Yardi Maintenance IQ, AppFolio Realm-X, Entrata ELI+)
in roughly a quarter. The labeled outcome dataset is not. Every engineering decision should be
evaluated against: *does this increase label velocity or label quality?*

---

## 2. Invariants (never violate without founder sign-off)

- **INV-1 · Safety gate is hard, not advisory.** For gas, high-voltage, structural, and water-intrusion
  categories, escalate to a licensed trade **regardless of confidence score**. No accuracy threshold
  overrides this. `VERIFY` is mandatory before `SAFETY_GATE`.
- **INV-2 · Canadian data residency.** All stores (R2/S3 bucket, Postgres, Qdrant, Langfuse) must sit
  in a Canadian region (`ca-central-1` or equivalent). This is a PIPEDA / Quebec Law 25 procurement
  gate, and a sales differentiator vs US-hosted incumbents. No new service may be added that
  processes ticket content outside Canada. Langfuse stays **self-hosted** for this reason.
  Third-party reranker/eval APIs count as services — prefer self-hosted (see DEC-8).
- **INV-3 · No media blobs in Postgres.** Media bytes go to R2/S3 via presigned direct upload
  (multipart for video). Postgres stores object keys (pointers) only.
- **INV-4 · Confidence is never self-reported.** The system never asks the model "how sure are you?"
  Verification checks hypotheses against retrieved evidence; calibration is post-hoc against
  contractor-confirmed outcomes. Reported confidence must trace to the calibrator, not the LLM.
  (Verbalized LLM confidence is empirically miscalibrated, overconfident, and sycophantic under
  contradiction — this invariant is literature-backed, not a preference.)
- **INV-5 · Clarify, don't guess.** If retrieved evidence + ticket content are insufficient to diagnose,
  `CLARIFY` asks a human and loops back to `RETRIEVE`. Hallucinating on thin information is a bug.
  `[IMPL: src/hero/graph/nodes/retrieve.py]` (P4-5): verify-tier sufficiency check on BOTH retrieval
  paths — a triage "simple" verdict can never let an insufficient ticket reach DIAGNOSE unasked
  (tested: tests/invariants/test_inv5_clarify.py). At most one organic check per ticket (no re-ask
  after a clarify round); questions must be concrete and tenant-answerable (generic questions are
  rejected at parse time and fail open to DIAGNOSE); hard-escalate/hazard tickets never CLARIFY (INV-1).
- **INV-6 · Every state transition is persisted** (LangGraph Postgres checkpointer). Resumability
  and the audit trail depend on this. Never bypass the checkpointer for "quick" paths.
- **INV-7 · BMS-independence.** The full pipeline (INTAKE → OUTCOME) must produce a complete,
  evidence-grounded diagnosis from **tenant-submitted evidence + the manual corpus alone**.
  BMS/BACnet/IoT sensor data is optional enrichment only: if present it may be injected as
  additional evidence at INTAKE/DIAGNOSE, but no state may **require** it, block on its
  availability, or degrade below full functionality without it. Any schema field carrying sensor
  data must be nullable; every sensor-aware code path must have a tested no-sensor branch.
  Rationale: the target market includes older buildings with no modern BMS — a telemetry
  dependency kills the wedge.
- **INV-8 · Schema-valid ≠ correct.** Structured output / constrained decoding guarantees format
  only. No schema-valid output may bypass grounded verification (`VERIFY`) or the safety gate.

---

## 3. Runtime State Machine (control plane)

```
INTAKE → TRIAGE → RETRIEVE → [grade evidence ⟲ corrective re-retrieve, capped]
       → [CLARIFY ⟲ back to RETRIEVE] → DIAGNOSE
       → VERIFY → SAFETY_GATE → { ESCALATE (licensed trade) | RESOLVE → PROCURE → OUTCOME }
```

| State | Responsibility | Notes |
|---|---|---|
| `INTAKE` | Ticket + media ingestion | Presigned upload client-side; state receives pointers. Sensor/BMS data, if available, attaches here as **optional** evidence (INV-7) |
| `TRIAGE` | Urgency + trade + complexity classification | ✅ Complexity routing landed (BL-4 / DEC-21): VLM triage with keyword fail-safes; simple → fast path |
| `RETRIEVE` | Hybrid retrieval over manual corpus | ✅ Reranker landed (BL-1); 🔄 corrective loop (BL-9) |
| `CLARIFY` | HITL follow-up question, loop to RETRIEVE | Graph pauses here; checkpointer makes it resumable |
| `DIAGNOSE` | VLM forms fault hypotheses | Tiered via LiteLLM (DEC-18): claude-fable-5 primary, claude-sonnet-4-6 verify tier, gpt-4o fallback |
| `VERIFY` | Ground each claim against evidence | ✅ Claim-level checks landed (BL-6 / DEC-6, DEC-19): real evidence text, per-type thresholds |
| `SAFETY_GATE` | Hard escalation check | INV-1. Category-based, confidence-independent. 🔄 Conformal prediction sets (BL-10) |
| `RESOLVE` | Fix recommendation + work order | |
| `PROCURE` | NL part need → catalog SKU | 🔄 Deterministic compatibility hard-filters (BL-11) |
| `OUTCOME` | Capture contractor confirmation | **First-class, not an afterthought** (BL-0) |

- **Framework:** LangGraph with Postgres checkpointer. ✅ Confirmed by two independent reviews as
  current best practice for stateful + HITL agent workflows.
- **DEC-1:** Keep LangGraph. Pin versions hard. Minimize LangChain surface — LangGraph standalone.

---

## 4. The Four Planes

### 4.1 Knowledge plane (multimodal RAG over manufacturer manuals)

- **Ingestion:** page-as-image embedding via ColPali-family late-interaction model → multi-vector
  patch embeddings. No OCR flattening; wiring diagrams and exploded parts views are preserved.
- **Index:** Qdrant (HNSW), populated at **ingestion time only**. Live diagnosis is read-only
  against Qdrant. 🔄 **DEC-9: int8 scalar quantization + on-disk indexing** — near-lossless
  (<1% nDCG@5) at ~4× storage/bandwidth reduction; multivector indexes are storage-heavy
  (~100–500KB/page at float32).
- **Retrieval:** dense multi-vector MaxSim + BM25, fused via reciprocal-rank fusion (RRF).
  BM25 exists to catch literal part numbers / model codes that dense search smears.
  **DEC-10: BM25 stays — do NOT replace with ColBERT.** ColBERT does soft semantic token matching
  and does not guarantee exact-token match; for SKU/part-number retrieval, exact match IS the
  signal. Late interaction already exists in the stack via the ColPali-family embedder.
- 🔄 **DEC-2 (open bake-off):** embedding model. `ColQwen2.5-7B` is adequate (external review:
  "the right starting point") but a generation old. Candidates: **ColQwen3-4B** (ViDoRe SOTA) vs
  **ColModernVBERT** (250M params, within ~0.6 NDCG@5, ~28× smaller → cheaper ingestion,
  CPU-viable). Benchmark on our actual manual pages (BL-5). Embedder is a swappable interface.
- ✅ **Cross-encoder reranker landed** (BL-1, 2026-07). Hybrid top-50 → rerank → top-5. Both reviews
  independently ranked this the single highest-ROI retrieval change. **Self-hosted**
  bge-reranker-v2-m3 (`adapters/bge_reranker.py`); Cohere Rerank API excluded for residency (INV-2, DEC-8).
- 🔄 **Corrective retrieval loop (CRAG-style)** (BL-9 / DEC-11): a lightweight evaluator grades
  whether retrieved manual pages actually support diagnosis before DIAGNOSE; re-retrieve /
  rewrite query if insufficient. Capped iterations + latency timeout, fall back to one-shot.
- ⏸ **Region-level retrieval** (patch-to-region) — post-traction upgrade for audit precision (BL-7).
- **DEC-3:** Qdrant stays. pgvector cannot do late-interaction MaxSim.

### 4.2 Procurement plane

- NL part need → SKU via: candidate retrieval (dense + BM25) → synonym/abbreviation expansion
  → rerank → SKU lock. Aligns with entity-matching best practice (multi-signal: embeddings + ANN
  + deterministic exact signals). Exact-match signals for part numbers stay (DEC-10).
- 🔄 **DEC-12: deterministic compatibility hard-filters** (BL-11): relational compatibility table
  in Postgres (voltage/phase/refrigerant/frame/rotation) applied as hard filters at SKU lock.
  Captures ~80% of a parts-compatibility graph's value at ~5% of the cost.
  ⏸ Graduate to a graph DB (Neo4j/FalkorDB) **only** if relationships outgrow SQL (DEC-13).
- ⚠️ **OPEN-1: catalog source is undecided and bounds everything downstream.** The procurement
  plane's real bottleneck. Flag any code that hard-codes catalog schema assumptions.

### 4.3 Case/record plane (storage)

- **R2/S3:** media bytes, presigned direct upload, multipart for video. ✅
- **Postgres:** source of truth. Three logically distinct contents: operational case records
  (with R2 pointers), LangGraph checkpoints, and `ContractorStatement` outcome labels.
- ⏸ **DEC-4:** analytics split — DuckDB over Parquet (or `postgres_scanner` on a read replica)
  for flywheel joins. ~90% of warehouse benefit at ~10% of cost, single-node. Build when flywheel
  scans visibly compete with live traffic. ❌ No BigQuery/Snowflake until single-node DuckDB is
  genuinely exceeded (~100GB+).

### 4.4 Reasoning layer

- Claude Sonnet primary VLM, GPT-4o fallback, via **LiteLLM**. ✅
- **Observability:** self-hosted Langfuse (INV-2), every run traced. ✅ 2026-07: node-span
  tracing wired (`observability/` — span per node, trace per ticket, no-op without LANGFUSE_*
  config). Dashboards (incl. BL-0 label velocity) require a deployed self-hosted instance —
  infra, still open. Use Langfuse's LLM-as-judge evaluators (Ragas-backed) as part of the eval
  harness (BL-3) — validate judge–human agreement before trusting scores.
- 🔄 **Eval pipeline** (BL-3): labeled golden-ticket regression suite, CI-gated. Tracing ≠ evaluation.

---

## 5. Verification, Calibration & Safety

- `VERIFY` grounds claims against retrieved evidence (INV-4, DEC-6: claim-level; per-claim
  grounding rate is the binding metric).
- **DEC-5:** calibrator = **Platt/temperature scaling now**; isotonic regression gated behind
  ≥1,000 confirmed outcomes (Niculescu-Mizil & Caruana 2005: isotonic overfits small calibration
  sets, matches/beats Platt only at 1,000+ points). Start with a **global** calibrator; per-trade
  specialization only when per-trade label volume supports it — don't fragment a small dataset.
  Track ECE always.
- 🔄 **DEC-14: conformal prediction at SAFETY_GATE** (BL-10). Output distribution-free,
  guaranteed-coverage prediction sets (true fault in set with prob ≥ 1−α); **escalate whenever the
  set is non-singleton or contains a hazard category**. Cheap, statistically grounded, and fits
  the existing escalation logic. Caveats: coverage is marginal and assumes exchangeability —
  new building/equipment types degrade the guarantee; monitor and re-calibrate. Requires a modest
  calibration set → sequenced after early `ContractorStatement` accumulation.
- Hard category escalation (INV-1) is unchanged and sits above all of this.

---

## 6. Backlog (table order = priority; IDs are stable)

| ID | Item | Effort | Why |
|---|---|---|---|
| **BL-0** | Instrument `OUTCOME` label capture: near-zero-friction contractor confirm/correct UX; label velocity as tracked metric. 2026-07 hardening (P3-2): repo layer refuses `resolved` without a `contractor_statement`; closed verdict vocabulary + corrections-require-`actual_fault` (DB CHECKs + API); `GET /outcomes/metrics/label-velocity` (Langfuse dashboard lands with observability work). Contractor UX still open | ongoing | The moat. Everything else is replicable. |
| **BL-1** | ✅ 2026-07: BGE cross-encoder reranker (`adapters/bge_reranker.py`), wired into full path; Cohere adapter stubbed behind config flag (DEC-8). Hit-rate@5 lift demo pending `--live` eval run | days | Highest-ROI retrieval change (both reviews agree) |
| **BL-2** | ✅ 2026-07: `PlattCalibrator` default (`adapters/platt.py`); `IsotonicCalibrator` self-gated ≥1K labels (DEC-5); ECE reported per eval run | hours | Current default statistically invalid at our volume |
| **BL-3** | Eval pipeline: golden tickets + retrieval metrics (recall@k, nDCG@5) + LLM-as-judge grounding, CI-gated | ~1 wk | Can't improve what isn't measured; prereq for BL-5/BL-9 |
| **BL-4** | ✅ 2026-07: Complexity routing in TRIAGE — VLM triage (verify tier, DEC-18 as amended) with deterministic INV-1 fail-safes (DEC-21); `complexity=="simple"` routes to `retrieve_fast` graph node (BM25-only top 5, no rerank); CLARIFY loop always re-enters full path; eval reports fast/full path split (latency + cost) | ~1 wk | 3–10× token, 2–5× latency cost of full path; unit economics |
| **BL-9** | Corrective retrieval loop: grade evidence, re-retrieve before DIAGNOSE, capped + timeout (DEC-11) | ~1 wk | Double-digit gains on hard queries; needs BL-3 to measure |
| **BL-5** | Embedder bake-off: ColQwen3-4B vs ColModernVBERT on our manuals (DEC-2) | ~1 wk | Quality and/or ~28× cost improvement candidate |
| **BL-12** | Int8 quantization + on-disk Qdrant index (DEC-9) | days | ~4× storage cut, <1% quality loss; do when corpus grows |
| **BL-6** | ✅ 2026-07: Claim-level VERIFY (DEC-6) — real `EvidenceChunk.text` into entailment (VERIFY tier); deterministic claim classifier (`verification/claims.py`) with per-type thresholds (part_number 1.0 / descriptive 0.8, config); per-claim results persisted to `diagnosis_claim` incl. `claim_type` (DEC-19); eval reports per-type grounding | | After BL-1; verification is only as good as evidence |
| **BL-10** | Conformal prediction sets at SAFETY_GATE (DEC-14) | 1–2 q | Needs calibration data; strongest new safety primitive |
| **BL-11** | Deterministic procurement compatibility hard-filters (DEC-12) | | With procurement plane build-out; blocked partly on OPEN-1 |
| **BL-13** | Per-contractor ticket assignment (DEC-22): `contractor_id` on ticket, assignment action in the operator UI, contractor list filtered to assigned tickets | days | Phase 5 — pilot is org-scoped visibility; needed once orgs run multiple crews |
| **BL-15** | Phase 5 hardening (P4-4 accepted caveats, must not evaporate): (1) R2 presigned PUTs get a server-enforced body-size condition — declared `content_length` is advisory today, a client can PUT a larger object; (2) public rate limiting survives multi-worker/multi-instance deploys — `SlidingWindowLimiter` is per-process memory, gunicorn `-w 4` quarters the budget (move to Postgres or Redis counters) | days | Phase 5 — single-worker pilot is safe; both bite the moment deployment topology changes |
| **BL-14** | ⏸ Per-node timestamps in the ledger (node-level instrumentation feeding `ticket_event`) | deferred, low priority | Ledger events currently share the run-completion timestamp, ordered by `seq`; Langfuse spans already cover ops timing — this is an audit-artifact nicety, not a gap |
| **BL-17** | ✅ 2026-07-13: **H1 — Async pipeline** — intake + clarify-answer POSTs return in <2s (measured 0.03–0.28s live); graph runs in a tracked background task (`api/background.py`); `pipeline_status` (`queued\|running\|awaiting_tenant\|complete\|failed`, DB CHECK) on ticket + public status (`working` bool, no pipeline vocabulary across the P4-4 boundary); startup `recover_orphaned_runs` re-drives kill-9'd runs from the Postgres checkpoint (INV-6) — demonstrated live. Prerequisite for Nova (DEC-23) | days | Phase 5 STEP 1 |
| **BL-18** | ✅ 2026-07-13: **H2 — Work-order persistence** — `persist_completion` (shared by create + resume paths) writes the `work_order` row pinned to the id RESOLVE minted, so the ledger `procure` event references the row PK directly — verified live | hours | Phase 5 STEP 1 (graph exit path) |
| **BL-19** | ✅ 2026-07-13: **H3 — Serving hardening bundle** — `init_graph` in lifespan (checkpointer warm-up kills the first-ticket `CREATE INDEX CONCURRENTLY` self-deadlock; model weights load at boot, ~27s, never on a user request); graph/model singleton; live adapter selection is documented config (`VLM_IMPL`/`EMBEDDER_IMPL`/`RERANKER_IMPL`, spec §3) — retires the demo-night uncommitted deps.py bypass | days | Phase 5 STEP 1 (serving path) |
| **BL-20** | **H4 — Timestamp source consistency:** `ticket_event` vs `ticket` rows showed 14:58 vs 22:12 for the same run (likely UTC/local mix); ledger credibility requires coherent times | hours | Phase 5 STEP 4 (chat renders times) |
| **BL-21** | **H5 — Tenant-facing error UX:** human message, states clearly whether the report went through, retry guidance — no raw "Internal Server Error" on a successful submission (FRICTION.md) | days | Phase 5 STEP 4 |
| **BL-16** | ⏸ Nova voice mode (DEC-25): STT/TTS with its own PIPEDA/residency review before any audio leaves the device | deferred | Fast-follow after text-first Nova; INV-2 review is the gate |
| **BL-7** | ⏸ Region-level evidence grounding (patch-to-region) | deferred | Post-traction audit-artifact upgrade |
| **BL-8** | ⏸ DuckDB/Parquet analytics split (DEC-4) | deferred | When flywheel scans compete with live traffic |

**Corpus-coverage note (2026-07-13, BL-17 live verification):** with the pilot's 3 synthetic
test manuals, any ticket outside their coverage (radiator, toilet, exhaust fan — fresh AND
recovered runs alike) ends `escalated` with `diagnosis_unparseable`: the live primary model
correctly returns `claims: []` rather than fabricate against irrelevant excerpts, and DIAGNOSE
escalates per P3-1.5. This is the safety design working, but corpus thinness makes escalation
the *common* case. Mitigation is real-manual ingestion + retrieval-quality re-test (the
FRICTION.md retrieval observation), **scheduled before the Phase 5 STEP 4 phone loop**.

---

## 7. Anti-Goals (❌ do not build — rationale recorded so they aren't relitigated)

- ❌ **Replace BM25 with ColBERT** (DEC-10). Soft semantic matching breaks guaranteed exact-token
  match for SKUs/part numbers; ~10× storage; late interaction already present via the embedder.
- ❌ **Domain fine-tuning now** (DEC-15). Deferred until `ContractorStatement` holds thousands of
  labeled real-world outcomes. Cold-start: no public labeled multi-trade real-fault dataset exists.
  Note: the circulated "LightLLM4FDD 99.8%" claim is **unsubstantiated** — the real source is a
  GPT-3.5 fine-tune on clean single-equipment AHU benchmarks (Zhang et al. 2025, *Applied Energy*
  377:124378), not comparable to real-world multi-trade accuracy. Do not cite the 99.8% figure.
- ❌ **Raw BMS time-series serialized as text into the LLM** (DEC-16). Fails on long sequences and
  subtle anomalies; context truncation. If BMS data ever matters, use a specialized time-series
  encoder feeding compact summaries — and it remains optional enrichment (INV-7).
- ❌ **Neo4j/graph DB for parts compatibility now** (DEC-13). Relational compatibility table +
  deterministic filters first (BL-11); graduate only if relationships outgrow SQL.
- ❌ **Full physics-informed LLM (PILLM) verification.** The useful cheap subset is deterministic
  sanity rules (voltage/phase/refrigerant match) — that's a rules engine, covered by BL-11.
- ❌ Full BMS/BACnet integration — tiered IoT sensor model chosen instead; sensor data is
  enrichment, never a dependency (INV-7). Reject any PR where null sensor fields cause failure
  or degraded output.
- ❌ Blob storage in Postgres, ever (INV-3).
- ❌ Model self-reported confidence anywhere in the product surface (INV-4).
- ❌ Trusting constrained decoding as verification (INV-8).
- ❌ Gold-plating pipeline infrastructure ahead of label velocity.
- ❌ New third-party services that process ticket content outside Canada (INV-2).
- ❌ Broad LangChain abstractions beyond LangGraph core (DEC-1).
- ❌ Cloud warehouse (BigQuery/Snowflake) before single-node DuckDB is exceeded (DEC-4).

---

## 8. Competitive Context (why the invariants exist)

Incumbents ship AI maintenance triage natively: Yardi **Maintenance IQ** (image recognition →
suggested fixes), AppFolio **Realm-X** (agentic maintenance workflows), Entrata **ELI+**
(100+ embedded agents, announced Mar 2026), plus third-party layers (Haven, Property Meld,
Latchel). None of them have: (a) manual-grounded evidence chains with a full audit trail,
(b) contractor-confirmed outcome labels, (c) Canadian-resident self-hosted stack.
Those three are the product. Defend them in every PR.

**Identified risks (adversarial VC review):** incumbent bundling, unclear ROI ownership,
moat pointed at engineering rather than data. BL-0 is the standing answer to the third.

---

## 9. Data Flywheel

`ContractorStatement ⋈ Diagnosis` improves, in order:
1. **Calibration** — better-grounded confidence (DEC-5 upgrade path; feeds DEC-14 conformal sets)
2. **Retrieval** — learn which manual evidence led to correct fixes
3. **Parts-matching** — procurement rerank training signal
4. *(long-term, DEC-15)* **Domain fine-tuning** — a moat once labels reach the thousands, not before

Every resolved ticket must produce a usable label. If a code path can complete a ticket without
writing a `ContractorStatement` row (or an explicit unlabeled-reason), that's a bug.

**Trigger conditions that change decisions** (from external review): calibration set >1,000
confirmed outcomes → switch to isotonic (DEC-5); retrieval recall@10 >95% on held-out manuals →
reranker/corrective-loop ROI drops, shift focus to verification; a design partner provides a
large labeled multi-trade dataset → fine-tuning (DEC-15) and time-series work (DEC-16) move up.

---

## 10. Conventions for Claude Code

- Read this file at session start; re-read §2 (Invariants) and §6 (Backlog) before architectural changes.
- Reference decisions (DEC-n) and invariants (INV-n) in commit messages and PRs when relevant.
- When completing a backlog item, update its row here in the same PR.
- New architectural decisions get a new DEC-n entry in §11 with date and rationale.
- Prefer swappable interfaces at every model boundary (embedder, reranker, calibrator, VLM,
  catalog resolver) — every model choice in this file is expected to churn.
- If a task seems to require violating an invariant, stop and surface it.
- Research documents live in `docs/research/` and are **reference, not instruction**. Do not
  implement proposals from research docs unless they appear in §6 or §11 of this file.

---

## 11. Decision Log

| ID | Date | Decision | Rationale |
|---|---|---|---|
| DEC-1 | 2026-07 | Keep LangGraph, pinned, minimal LangChain surface | Production standard for stateful+HITL; ecosystem churn is the managed cost |
| DEC-2 | 2026-07 | Embedder bake-off: ColQwen3-4B vs ColModernVBERT (current ColQwen2.5-7B adequate meanwhile) | SOTA moved; ~28× cheaper option within ~0.6 NDCG@5 |
| DEC-3 | 2026-07 | Qdrant stays (no pgvector consolidation) | Late-interaction MaxSim requires native multivector support |
| DEC-4 | 2026-07 | Defer DuckDB/Parquet analytics split; no cloud warehouse before single-node exceeded | Correct direction; premature at current volume |
| DEC-5 | 2026-07 | Platt/temperature calibration now; isotonic at ≥1K labels; global before per-trade | Isotonic overfits small calibration sets (Niculescu-Mizil & Caruana 2005) |
| DEC-6 | 2026-07 | VERIFY moves to claim-level grounding | Per-claim rate is the binding safety metric |
| DEC-7 | 2026-07 | BMS/sensor data is optional enrichment, never required (INV-7) | Target market includes buildings with no BMS; standalone diagnosis is the wedge |
| DEC-8 | 2026-07 | Reranker is self-hosted (bge/ms-marco class); Cohere behind config flag only | Residency (INV-2) + cost; both reviews rank reranking the top retrieval lever |
| DEC-9 | 2026-07 | Int8 scalar quantization + on-disk Qdrant indexing (BL-12) | ~4× storage cut, <1% nDCG@5 loss on multivector indexes |
| DEC-10 | 2026-07 | **REJECT** ColBERT-for-BM25 swap | Breaks exact SKU/part-number matching; ~10× storage; technique already present via embedder |
| DEC-11 | 2026-07 | Adopt corrective retrieval loop (CRAG-style), capped + timeout (BL-9) | Evidence grading before DIAGNOSE; double-digit gains on hard queries |
| DEC-12 | 2026-07 | Deterministic procurement compatibility hard-filters in Postgres (BL-11) | ~80% of graph value at ~5% cost |
| DEC-13 | 2026-07 | **DEFER** graph DB for parts compatibility | Only if relationships outgrow SQL (revisit post-BL-11) |
| DEC-14 | 2026-07 | Adopt conformal prediction sets at SAFETY_GATE (BL-10) | Distribution-free coverage guarantee; escalate on non-singleton/hazard sets; monitor under distribution shift |
| DEC-15 | 2026-07 | **DEFER** domain fine-tuning until ContractorStatement in the thousands | Cold-start; "LightLLM4FDD 99.8%" claim debunked (real source: GPT-3.5 on clean single-AHU benchmarks) |
| DEC-16 | 2026-07 | **REJECT** raw BMS time-series text serialization | Fails on long sequences; if ever needed, specialized TS encoder → summary; INV-7 holds |
| DEC-17 | 2026-07 | Dual state representation: `TicketState` (Pydantic) + `GraphState` (TypedDict) | LangGraph's `StateGraph` requires a TypedDict (or `dataclass`/`dict`) to define the state schema for channel-based merging — it does not accept Pydantic `BaseModel`. The spec §4 `TicketState` (Pydantic) is retained for validation inside nodes (e.g. `diagnose` constructs it to validate inputs). `GraphState` (TypedDict) mirrors it field-for-field and is used only as the `StateGraph` type parameter. Both live in `src/hero/graph/state.py`. |
| DEC-18 | 2026-07 (amended 2026-07, P3-4) | Tiered VLM routing: `claude-fable-5` primary (DIAGNOSE), `claude-sonnet-4-6` verify (decompose_claims/check_entailment **+ TRIAGE**), `gpt-4o` cross-provider fallback (both tiers). All model IDs are config — never hard-coded in the adapter. `VLM_MODEL_TRIAGE` overrides the triage model; empty = verify tier. **Amendment:** TRIAGE moved primary → verify tier after a live A/B (4 golden tickets × 3 runs each): sonnet triage matched fable on pass rate (12/12 both), was perfectly stable across runs (0 run-to-run routing flips vs 1 for fable), and cut triage node latency 5.50s → 1.80s (−67%) and triage tier cost $0.1872 → $0.0523 (−72%) per 12-call eval. Annotation deviations 6/12 vs 5/12 — systematic (same verdict every run), not noise. | Reasoning-heavy diagnosis needs a frontier model; triage is a short constrained-vocabulary classification the verify tier handles as well, faster and cheaper. Safe to delegate because DEC-21's deterministic INV-1 fail-safes bound worst-case triage behavior regardless of model. Cross-provider fallback ensures availability. |
| DEC-19 | 2026-07 | `diagnosis_claim` gains a `claim_type` column (`part_number`\|`descriptive`, default `descriptive`; Alembic 0002) — a deviation from the original §5 DDL, which had no type column. Claim classification is deterministic regex (data-as-code, `verification/claims.py`), never an LLM call. | DEC-6 audit trail must record *which grounding threshold applied* to each claim; without the type, a persisted `grounded=true` at 0.8 is indistinguishable from one held to 1.0. Deterministic classifier keeps the safety-relevant routing auditable and free. |
| DEC-20 | 2026-07 | Primary-tier VLM outputs are **non-deterministic and cannot be pinned**: newer Anthropic models (`claude-fable-5`) reject the `temperature` parameter, so the adapter sends none (found live 2026-07-10 — the API returns "`temperature` is deprecated for this model"). Consequence: repeated DIAGNOSE calls on the same ticket produce different hypotheses/claims. Eval harness therefore supports `--runs N` and reports mean/min/max on grounding and cost; single-run eval numbers are samples, not point estimates. | Observed in the P3-0 baseline: the same golden ticket produced 9 claims in one run and 11 in the next. Any metric derived from primary-tier output must be read as a distribution; CI comparisons on single live runs would be noise. |
| DEC-22 | 2026-07 | No per-contractor assignment in the pilot; contractor visibility is org-scoped (`GET /tickets` filters on the session `org_id` only). Real assignment (`contractor_id` on ticket + filtered list) is a Phase 5 backlog row (BL-13). | Pilot orgs are single-contractor-crew scale; an assignment model now is schema + UI surface with no user to exercise it. Deferred deliberately at P4-2 review, not forgotten. |
| DEC-23 | 2026-07-13 | **Tenant intake becomes chat-based ("Nova").** A conversational layer answers in 2–3s on a fast model tier; diagnosis remains **async** via the full verified pipeline and arrives as a chat message when ready. Perceived latency is decoupled from pipeline completion — pipeline depth is unchanged and **NOT to be optimized down**. | The rehearsal (FRICTION.md) showed the sync intake POST blowing the phone timeout on a successful submission; conversation gives instant acknowledgment while VERIFY/SAFETY_GATE keep their full depth (INV-1, INV-8). |
| DEC-24 | 2026-07-13 | **Nova's scope is maintenance intake ONLY.** It is never a booking assistant; trade vocabulary stays exactly the PRD's TradeCategory set (no "cleaning"). Nova never answers safety, legal, medical, or tenancy-rights questions — deterministic guardrails route hazards to escalation and blocked topics to fixed redirect copy before any LLM sees them. | Scope creep in a tenant-facing LLM surface is a liability and positioning risk; the safety envelope must be deterministic (same principle as DEC-21's INV-1 fail-safes). |
| DEC-25 | 2026-07-13 | **Voice is phased — NOT in this build.** Text + photo/video chat first; voice is a fast-follow with its own PIPEDA/residency review (BL-16, deferred). No STT/TTS dependencies enter the repo in Phase 5. | Voice adds a biometric-adjacent data class (recordings) with its own consent and residency analysis (INV-2); shipping text-first decouples that review from the intake UX rebuild. |
| DEC-21 | 2026-07 | TRIAGE is VLM-backed (verify tier, per DEC-18 as amended) but wrapped in **deterministic INV-1 fail-safes** (`graph/nodes/triage.py`): (1) keyword hazard override — if the keyword scan detects a hard-escalate trade (gas/electrical/structural/water_intrusion), the VLM cannot classify it away; (2) urgency is never downgraded below the keyword verdict; (3) any VLM failure (call error or unparseable output, `TriageParseError`) falls back to the keyword classifier with `complexity="standard"` — a triage failure never blocks a ticket and never routes it to the reduced fast path. `TriageResult`'s Literal-typed fields are the parse/vocabulary gate. | Complexity classification needs real language understanding (BL-4), but INV-1 forbids letting a probabilistic model stand between a gas leak and escalation. The keyword layer is the floor, the VLM only refines upward. Fail-open-to-full-path keeps a triage outage from degrading retrieval quality or availability. |

---

## 12. Provenance

- v2: original narrative architecture walkthrough (docx, superseded — do not keep in repo).
- v3: structured rewrite + 2026 SOTA review.
- v4: merged external architecture review (`docs/research/compass_architecture_review_2026-07.md`)
  — adopted: reranker emphasis, corrective loop, conformal prediction, quantization, procurement
  hard-filters, calibration refinement; rejected/recorded: ColBERT swap, near-term fine-tune,
  raw time-series ingestion, premature graph DB.
