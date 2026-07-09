# Hero.AI — Technical Spec for Claude Code (TECH v1)

> **Audience: Claude Code.** This is the implementation-level companion to `HERO_AI_PRD.md`.
> Precedence: `HERO_AI_PRD.md` invariants (INV-*) and decisions (DEC-*) override this file;
> this file overrides your defaults; **existing code overrides this file's schemas/signatures
> once they land** — when code and spec diverge, update this spec in the same PR rather than
> "fixing" working code to match stale prose.
>
> Status: this is a **build spec** (greenfield). Sections marked `[SPEC]` are authoritative
> targets not yet implemented. When you implement one, change its tag to `[IMPL: <path>]`.

**Last updated:** 2026-07-08 · TECH v1.1 · Pairs with PRD v4

---

## 0. Operating Rules for Claude Code

1. Read `HERO_AI_PRD.md` §2 (invariants) before any change touching pipeline states, storage, or model calls.
2. Cite `INV-n` / `DEC-n` / `BL-n` IDs in commit messages when a change relates to them.
3. Every model boundary (embedder, reranker, calibrator, VLM, catalog resolver) goes through the
   Protocol interfaces in §6. Never call a model SDK directly from a graph node.
4. Every sensor-aware code path ships with a no-sensor test in the same PR (INV-7).
5. Never write media bytes to Postgres (INV-3). Never read model self-reported confidence into
   any persisted field (INV-4).
6. If a task requires violating an invariant, stop and surface it. Do not work around it.
7. Prefer boring, explicit code. No metaprogramming, no dynamic dispatch beyond the Protocols.

---

## 1. Stack

| Layer | Choice | Pin / Notes |
|---|---|---|
| Language | Python 3.12 | `uv` for env + lockfile |
| Orchestration | `langgraph` (standalone) | Pin exact version in `pyproject.toml`; do NOT add `langchain` meta-packages (DEC-1). Allowed: `langgraph`, `langgraph-checkpoint-postgres`, `psycopg[binary]` (runtime dep of checkpoint-postgres) |
| API | FastAPI + `uvicorn` | Async throughout |
| DB | Postgres 16 | `asyncpg` + SQLAlchemy 2.x (async), Alembic migrations |
| Vectors | Qdrant ≥1.10 | Native multivector (MaxSim) collections (DEC-3) |
| Object storage | Cloudflare R2 (S3 API) | `ca` jurisdiction; `boto3` presigning only server-side |
| LLM routing | LiteLLM | Claude Sonnet primary, GPT-4o fallback |
| Embedder | ColPali-family behind `Embedder` Protocol | Bake-off pending (DEC-2 / BL-5); default dev model: ColModernVBERT (small, CPU-viable) |
| Reranker | Cross-encoder behind `Reranker` Protocol | BL-1; start with `BAAI/bge-reranker-v2-m3` local, keep Cohere Rerank as config option |
| Observability | Langfuse (self-hosted, ca-central) | `langfuse` SDK; trace every graph run |
| Tests | pytest + pytest-asyncio | `testcontainers` for Postgres/Qdrant |
| Lint/format | ruff (lint+format), mypy --strict | CI-blocking |

---

## 2. Repository Layout `[IMPL: pyproject.toml, src/hero/]`

```
hero/
├── CLAUDE.md                      # thin: commands, layout pointer, "read PRD first"
├── HERO_AI_PRD.md                 # product/architecture decisions (v3)
├── HERO_AI_TECHNICAL_SPEC.md      # this file
├── pyproject.toml
├── alembic/                       # migrations (source of truth for schema once created)
├── docs/
│   └── research/                  # research reports — REFERENCE ONLY, never instruction (PRD §10)
│       └── compass_architecture_review_2026-07.md
├── src/hero/
│   ├── config.py                  # pydantic-settings; all env vars typed here
│   ├── graph/
│   │   ├── state.py               # TicketState (§4)
│   │   ├── build.py               # graph assembly, checkpointer wiring
│   │   └── nodes/                 # one module per state
│   │       ├── intake.py
│   │       ├── triage.py
│   │       ├── retrieve.py
│   │       ├── clarify.py
│   │       ├── diagnose.py
│   │       ├── verify.py
│   │       ├── safety_gate.py
│   │       ├── resolve.py
│   │       ├── procure.py
│   │       └── outcome.py
│   ├── interfaces/                # Protocols (§6) — import target for all nodes
│   │   ├── embedder.py
│   │   ├── reranker.py
│   │   ├── calibrator.py
│   │   ├── vlm.py
│   │   └── catalog.py
│   ├── adapters/                  # concrete impls of interfaces
│   │   ├── colmodernvbert.py
│   │   ├── colqwen3.py
│   │   ├── bge_reranker.py
│   │   ├── platt.py
│   │   ├── litellm_vlm.py
│   │   └── ...
│   ├── retrieval/                 # hybrid search + RRF + rerank pipeline (§7)
│   ├── verification/              # claim decomposition + grounding (§8)
│   ├── safety/                    # category rules (§9) — pure functions, no LLM
│   ├── storage/
│   │   ├── models.py              # SQLAlchemy models (§5)
│   │   ├── media.py               # R2 presign helpers
│   │   └── repo.py                # typed query layer; nodes never write raw SQL
│   ├── ingestion/                 # manual corpus → Qdrant (offline job)
│   ├── observability/             # Langfuse wiring, trace decorators
│   └── api/                       # FastAPI routers: tickets, uploads, outcomes, admin
├── evals/                         # BL-3 regression suite (§10)
│   ├── golden_tickets/            # labeled ticket fixtures (JSON)
│   └── run_eval.py
└── tests/
    ├── unit/
    ├── integration/
    └── invariants/                # explicit INV-* enforcement tests (§10.3)
```

---

## 3. Configuration `[IMPL: src/hero/config.py]`

All config via `pydantic-settings` in `src/hero/config.py`. No `os.environ` reads elsewhere.

```
DATABASE_URL                # postgres, ca-central instance
QDRANT_URL / QDRANT_API_KEY
R2_ENDPOINT / R2_BUCKET / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY   # bucket region: ca
LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY           # self-hosted
LITELLM_*                   # provider keys; primary=claude-sonnet, fallback=gpt-4o
EMBEDDER_IMPL               # "colmodernvbert" | "colqwen3"  (DEC-2 bake-off switch)
RERANKER_IMPL               # "bge" | "cohere"
CALIBRATOR_IMPL             # "platt" (default; "isotonic" gated behind label count ≥1000, DEC-5)
```

Startup MUST fail loudly (not degrade) if a store resolves to a non-Canadian region where
detectable (INV-2). Add a `region_guard()` check in app startup.

---

## 4. Graph State `[IMPL: src/hero/graph/state.py]` (DEC-17: TicketState Pydantic + GraphState TypedDict)

`src/hero/graph/state.py`. Single typed state object; nodes take and return `TicketState` deltas.

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

TradeCategory = Literal["hvac", "plumbing", "electrical", "appliance",
                        "structural", "water_intrusion", "gas", "other"]
Complexity = Literal["simple", "standard", "complex"]     # BL-4 routing

class MediaRef(BaseModel):
    object_key: str            # R2 key — POINTER ONLY (INV-3)
    media_type: Literal["image", "video"]
    sha256: str

class SensorReading(BaseModel):   # OPTIONAL enrichment only (INV-7)
    source: str
    metric: str
    value: float
    unit: str
    observed_at: str           # ISO 8601

class EvidenceChunk(BaseModel):
    doc_id: str                # manual document id
    page: int
    region: Optional[dict] = None   # bbox; BL-7, nullable until then
    score: float               # post-rerank score
    retrieval_stage: Literal["dense", "bm25", "fused", "reranked"]

class Claim(BaseModel):        # DEC-6: claim-level verification
    text: str
    grounded: Optional[bool] = None
    supporting_evidence: list[EvidenceChunk] = []

class Hypothesis(BaseModel):
    fault: str
    claims: list[Claim]
    # NOTE: no `model_confidence` field, ever (INV-4).
    calibrated_confidence: Optional[float] = None   # set only by Calibrator

class TicketState(BaseModel):
    ticket_id: str
    description: str
    media: list[MediaRef] = []
    sensor_readings: list[SensorReading] = []       # may be empty; pipeline must not care (INV-7)
    # TRIAGE
    urgency: Optional[Literal["emergency", "urgent", "routine"]] = None
    trade: Optional[TradeCategory] = None
    complexity: Optional[Complexity] = None         # BL-4
    # RETRIEVE
    evidence: list[EvidenceChunk] = []
    clarify_rounds: int = 0                         # cap at 3, then escalate to human dispatcher
    pending_question: Optional[str] = None          # set by CLARIFY; graph interrupts here
    # DIAGNOSE / VERIFY
    hypotheses: list[Hypothesis] = []
    verify_pass: Optional[bool] = None              # per-claim grounding rate ≥ threshold
    # SAFETY_GATE
    escalated: bool = False
    escalation_reason: Optional[str] = None
    # RESOLVE / PROCURE
    work_order_id: Optional[str] = None
    sku: Optional[str] = None
```

**Graph wiring rules (`build.py`):**
- Checkpointer: `PostgresSaver` on `DATABASE_URL`. Every node runs under it (INV-6).
- `CLARIFY` uses `interrupt()` — the graph pauses, `pending_question` is surfaced via API,
  human answer resumes the run at RETRIEVE. `clarify_rounds >= 3` → route to human dispatcher, not another loop.
- Conditional edges: `TRIAGE → {fast_path | full_path}` on `complexity` (BL-4);
  `VERIFY → SAFETY_GATE` unconditional (never skippable, INV-1);
  `SAFETY_GATE → {ESCALATE | RESOLVE}`.

---

## 5. Data Model `[IMPL: src/hero/storage/models.py, alembic/versions/0001_initial_schema.py]` — target DDL (implement via Alembic; migrations become source of truth)

```sql
CREATE TABLE ticket (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    building_id     UUID NOT NULL,
    description     TEXT NOT NULL,
    urgency         TEXT,
    trade           TEXT,
    complexity      TEXT,
    status          TEXT NOT NULL DEFAULT 'open',   -- open|clarifying|escalated|resolved|closed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE media (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID NOT NULL REFERENCES ticket(id),
    object_key      TEXT NOT NULL,        -- R2 pointer ONLY (INV-3)
    media_type      TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sensor_reading (             -- OPTIONAL enrichment (INV-7): table may be empty forever
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID NOT NULL REFERENCES ticket(id),
    source          TEXT NOT NULL,
    metric          TEXT NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    unit            TEXT NOT NULL,
    observed_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE diagnosis (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID NOT NULL REFERENCES ticket(id),
    run_id          TEXT NOT NULL,        -- langgraph thread id (audit join)
    fault           TEXT NOT NULL,
    calibrated_confidence DOUBLE PRECISION,   -- from Calibrator only (INV-4)
    verify_pass     BOOLEAN NOT NULL,
    escalated       BOOLEAN NOT NULL DEFAULT FALSE,
    escalation_reason TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE diagnosis_claim (            -- DEC-6 audit trail
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    diagnosis_id    UUID NOT NULL REFERENCES diagnosis(id),
    claim_text      TEXT NOT NULL,
    grounded        BOOLEAN NOT NULL,
    evidence        JSONB NOT NULL        -- [{doc_id, page, region?, score}]
);

CREATE TABLE work_order (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID NOT NULL REFERENCES ticket(id),
    diagnosis_id    UUID REFERENCES diagnosis(id),
    sku             TEXT,
    body            JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- THE FLYWHEEL TABLE (BL-0). A ticket reaching 'resolved' without a row here is a bug (PRD §9).
CREATE TABLE contractor_statement (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID NOT NULL REFERENCES ticket(id),
    diagnosis_id    UUID NOT NULL REFERENCES diagnosis(id),
    verdict         TEXT NOT NULL,        -- confirmed|partially_correct|wrong
    actual_fault    TEXT,                 -- required when verdict != confirmed
    actual_part_sku TEXT,
    contractor_id   UUID,
    free_text       TEXT,
    unlabeled_reason TEXT,                -- explicit reason if label unobtainable
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT verdict_or_reason CHECK (verdict IS NOT NULL OR unlabeled_reason IS NOT NULL)
);
CREATE INDEX ON contractor_statement (created_at);   -- flywheel scans; DuckDB split later (DEC-4)
```

LangGraph checkpoint tables: managed by `langgraph-checkpoint-postgres` — do not hand-edit.

---

## 6. Interfaces `[IMPL: src/hero/interfaces/, src/hero/adapters/stub_*.py]` — `src/hero/interfaces/`

All Protocols. Nodes import Protocols only; `config.EMBEDDER_IMPL` etc. select adapters at startup.

```python
# embedder.py
class Embedder(Protocol):
    model_id: str
    def embed_page(self, image: bytes) -> list[list[float]]: ...      # multi-vector patches
    def embed_query(self, text: str) -> list[list[float]]: ...

# reranker.py
class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[EvidenceChunk],
               top_k: int = 5) -> list[EvidenceChunk]: ...

# calibrator.py  (DEC-5: platt default; isotonic only when label_count >= 1000)
class Calibrator(Protocol):
    def calibrate(self, raw_grounding_score: float, trade: str) -> float: ...
    def fit(self, outcomes: list[tuple[float, bool]]) -> None: ...
    def ece(self) -> float: ...                                        # tracked metric

# vlm.py — the ONLY route to LLM providers (via LiteLLM adapter)
class VLM(Protocol):
    async def diagnose(self, state: TicketState) -> list[Hypothesis]: ...
    async def decompose_claims(self, hypothesis_text: str) -> list[str]: ...
    async def check_entailment(self, claim: str, evidence_text: str) -> bool: ...

# catalog.py  (OPEN-1: schema behind interface because catalog source is undecided)
class CatalogResolver(Protocol):
    async def resolve(self, part_need: str, trade: str) -> Optional[str]: ...  # returns SKU
```

---

## 7. Retrieval Pipeline `[SPEC]` — `src/hero/retrieval/`

```
query → [dense: Qdrant MaxSim multivector, top 25] ┐
                                                    ├→ RRF (k=60) → top 50 → Reranker → top 5
query → [BM25 index, top 25]                        ┘
```

- Qdrant collection: `manuals`, multivector config, HNSW; payload: `{doc_id, page, manufacturer, model_codes[]}`.
- BM25: Qdrant sparse vectors (single store) — do not add Elasticsearch.
- Ingestion (`src/hero/ingestion/`) is an offline CLI job: PDF pages → images → `Embedder.embed_page`
  → Qdrant upsert. Idempotent on `(doc_id, page)`. Never runs in the request path (PRD §4.1).
- Fast path (BL-4, `complexity == "simple"`): skip dense retrieval; BM25-only top 5, no rerank.
  Full path: the diagram above. Both paths emit `retrieval_stage` on every chunk for eval attribution.
- **Corrective loop (BL-9 / DEC-11) `[SPEC]`:** after rerank, a lightweight evidence grader
  (cheap LLM call via `VLM`, or heuristic score threshold) judges whether the top-5 plausibly
  support diagnosis. If not: rewrite query (LLM) and re-retrieve. Hard caps: `max_corrective_rounds=2`
  and a wall-clock timeout (config, default 10s); on cap/timeout, proceed with best-so-far
  (one-shot fallback). Add `corrective_rounds: int = 0` to `TicketState`.
- **Quantization (BL-12 / DEC-9) `[SPEC]`:** Qdrant collection configured with int8 scalar
  quantization + on-disk storage once corpus exceeds ~50K pages. Validate <1% nDCG@5 delta in
  the BL-3 eval before enabling in prod.

## 8. Verification `[SPEC]` — `src/hero/verification/`

Per hypothesis: `VLM.decompose_claims` → for each claim, gather top evidence text →
`VLM.check_entailment(claim, evidence)` → `Claim.grounded`.
`verify_pass = (grounded_claims / total_claims) >= GROUNDING_THRESHOLD` (config, default 1.0
for part numbers / model codes claims; 0.8 for descriptive claims — claim classifier decides).
The **per-claim rate** is what's persisted and evaluated (DEC-6), never an answer-level average alone.
`calibrated_confidence = Calibrator.calibrate(grounding_rate, trade)` — the only confidence
number that ever leaves the system (INV-4).

## 9. Safety Gate `[IMPL: src/hero/safety/gate.py, src/hero/safety/hazards.py]` — `src/hero/safety/`

Pure deterministic functions. **No LLM calls in this module.**

```python
HARD_ESCALATE_TRADES = {"gas", "electrical_high_voltage", "structural", "water_intrusion"}

def safety_gate(state: TicketState) -> SafetyDecision:
    if state.trade in HARD_ESCALATE_TRADES: return escalate("hard_category")   # INV-1
    if not state.verify_pass:               return escalate("verification_failed")
    if any_hazard_keywords(state):          return escalate("hazard_signal")
    return proceed()
```

Hazard keyword/pattern list lives in `safety/hazards.py` as data, reviewed like code.
Confidence is **not** an input to this function — by design (INV-1).

**Conformal prediction (BL-10 / DEC-14) `[SPEC]`:** once a calibration set exists (early
ContractorStatement accumulation), add a `ConformalGate` step producing a prediction set of
candidate faults with coverage ≥ 1−α (config, default α=0.1). Escalate when the set is
non-singleton **or** contains any hazard-category fault. This layers **on top of** the hard
rules above — it can only add escalations, never remove one. Monitor empirical coverage per
trade/building-type; re-calibrate on drift.

**INV-8 note:** structured/constrained decoding of node outputs guarantees schema only.
A schema-valid diagnosis still requires `VERIFY` + `safety_gate` — no shortcut paths.

---

## 10. Testing & Evals

### 10.1 Unit/integration
- `testcontainers` Postgres + Qdrant; no mocking of stores in integration tests.
- Adapters get contract tests against their Protocol (same test suite runs against every impl —
  this is what makes the DEC-2 bake-off cheap).

### 10.2 Eval suite (BL-3) — `evals/`
- `golden_tickets/*.json`: real (anonymized) tickets with contractor-confirmed labels.
- `run_eval.py` replays each through the graph with pinned adapters; reports:
  retrieval hit-rate@5, per-claim grounding rate, diagnosis accuracy vs label, ECE, cost/ticket, latency.
- CI job runs evals on any change under `retrieval/`, `verification/`, `adapters/`, or prompt files.
  Regression > 2% on grounding rate or accuracy blocks merge.

### 10.3 Invariant tests — `tests/invariants/` (these encode the PRD; never delete)
- `test_inv1_safety.py`: gas/HV/structural/water tickets escalate even with grounding rate 1.0.
- `test_inv3_no_blobs.py`: schema scan asserts no bytea/blob columns outside checkpoint tables.
- `test_inv4_no_self_confidence.py`: grep/AST check — no persisted field populated from raw model output named/derived as confidence.
- `test_inv6_checkpoints.py`: kill a run mid-graph, resume, assert state identical.
- `test_inv7_no_sensor.py`: full golden-ticket eval with `sensor_readings=[]` and `sensor_reading`
  table empty — asserts every ticket completes with non-degraded output. **Runs in CI always.**
- `test_flywheel.py`: ticket cannot transition to `resolved` without a `contractor_statement` row
  (verdict or `unlabeled_reason`). PRD §9.

---

## 11. Conventions

- **Commits:** `feat(retrieve): add bge cross-encoder rerank [BL-1]`, `fix(safety): ... [INV-1]`.
- **Errors:** nodes raise typed exceptions; the graph catches, checkpoints, and routes to a
  `FAILED` terminal state with reason — never silent retry loops. External calls (LiteLLM, Qdrant)
  get bounded retries (3, exponential) at the adapter layer only.
- **Tracing:** every node wrapped with the Langfuse decorator in `observability/`; span name =
  node name; run metadata includes `ticket_id`, `EMBEDDER_IMPL`, `RERANKER_IMPL` (bake-off attribution).
- **Prompts:** live in `src/hero/prompts/*.md` as files, versioned in git, loaded at startup —
  never inline f-strings in nodes. Prompt changes trigger the eval CI job.
- **Types:** mypy --strict passes. No `Any` in `graph/`, `interfaces/`, `safety/`.

## 12. Definition of Done — active backlog

| BL | Done means |
|---|---|
| BL-0 | `contractor_statement` table + `POST /outcomes` endpoint + `test_flywheel.py` green + label-velocity metric in Langfuse dashboard |
| BL-1 | `Reranker` Protocol + bge adapter + wired into full path + eval shows hit-rate@5 lift + Cohere adapter behind config flag |
| BL-2 | `platt.py` adapter default; isotonic adapter exists but gated on label_count ≥ 1000; ECE reported per eval run |
| BL-3 | `evals/` runnable locally + CI; ≥20 golden tickets seeded |
| BL-4 | `complexity` classifier in TRIAGE + conditional edge + cost/latency split visible in eval report |
| BL-5 | Both embedder adapters pass contract tests; bake-off report (NDCG on our manuals, $/1k pages, latency) committed to `docs/` |
| BL-9 | Evidence grader + query rewrite + `max_corrective_rounds`/timeout caps + eval shows lift on hard-query subset without >1.5× median latency on simple tickets |
| BL-10 | `ConformalGate` with configurable α + escalation on non-singleton/hazard sets + coverage monitoring in Langfuse + INV-1 hard rules provably unaffected (invariant test) |
| BL-11 | `part_compatibility` table + deterministic filters at SKU lock + tests that an incompatible voltage/phase/refrigerant SKU can never lock |
| BL-12 | Int8 quantization + on-disk index enabled behind config; eval confirms <1% nDCG@5 delta before prod enable |

---

## 13. Out of Scope for This Spec (see PRD)

Anti-goals (PRD §7), competitive rationale (PRD §8), region-level retrieval (BL-7, deferred),
DuckDB analytics split (BL-8, deferred), catalog source selection (OPEN-1 — business decision;
code stays behind `CatalogResolver` until resolved).
