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
| LLM routing | LiteLLM | Tiered: `claude-fable-5` primary (DIAGNOSE), `claude-sonnet-4-6` verify (claims/entailment + TRIAGE, DEC-18 as amended), `gpt-4o` cross-provider fallback. Config: `VLM_MODEL_PRIMARY`, `VLM_MODEL_VERIFY`, `VLM_MODEL_FALLBACK`, `VLM_MODEL_TRIAGE` (empty = verify tier) |
| Embedder | ColPali-family behind `Embedder` Protocol | Bake-off pending (DEC-2 / BL-5); default dev model: ColModernVBERT (small, CPU-viable) |
| Reranker | Cross-encoder behind `Reranker` Protocol | BL-1; start with `BAAI/bge-reranker-v2-m3` local, keep Cohere Rerank as config option |
| Observability | Langfuse (self-hosted, ca-central) | `langfuse` SDK; trace every graph run |
| Tests | pytest + pytest-asyncio | `testcontainers` for Postgres/Qdrant |
| Embedder runtime | `colpali-engine==0.3.17`, `torch==2.11.0`, `transformers==5.13.0`, `Pillow==12.3.0` | ColPali-family multivector embeddings (DEC-2) |
| Reranker runtime | `sentence-transformers==5.6.0` | BGE cross-encoder (BL-1, DEC-8) |
| Ingestion | `pypdfium2==5.11.0` | PDF → page images; no Poppler system dep |
| Calibration | `scikit-learn==1.9.0` | Platt/isotonic scaling (DEC-5) |
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
│   │   ├── repo.py                # typed query layer; nodes never write raw SQL
│   │   ├── ledger.py              # P4-3: pure event derivation + ledger assembly (no DB)
│   │   └── backfill_triage.py     # P4-2 follow-up: stamp trade/urgency onto pre-existing rows
│   ├── ingestion/                 # manual corpus → Qdrant (offline job)
│   ├── observability/             # Langfuse wiring, trace decorators
│   ├── auth/                      # P4-1: argon2id passwords, JWT sessions, seed CLI (python -m hero.auth seed)
│   ├── buildings.py               # P4-4: admin CLI — create buildings, print tenant intake links (python -m hero.buildings)
│   └── api/                       # FastAPI routers: auth, tickets, uploads, outcomes, public (P4-4 tenant intake)
│                                  #   + pipeline.py (shared run+persist), resume.py (single resume path, §4), ratelimit.py
├── evals/                         # BL-3 regression suite (§10)
│   ├── golden_tickets/            # labeled ticket fixtures (JSON)
│   └── run_eval.py
├── web/                           # P4-2 cockpit SPA (Vite + React + TS, dependency-light)
│   └── src/                       # screens/: Login, TicketList, Outcome (contractor), Ledger (operator, P4-3),
│                                  #   Intake + Status (public tenant, P4-4 — hash routes, no auth)
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
VLM_MODEL_PRIMARY / VLM_MODEL_VERIFY / VLM_MODEL_FALLBACK   # DEC-18 tiers (fable-5 / sonnet-4-6 / gpt-4o)
VLM_MODEL_TRIAGE                                            # TRIAGE override; empty = verify tier (DEC-18 as amended)
ANTHROPIC_API_KEY / OPENAI_API_KEY                          # provider keys (LiteLLM)
EMBEDDER_IMPL               # "colmodernvbert" | "colqwen3"  (DEC-2 bake-off switch)
RERANKER_IMPL               # "bge" | "cohere"
CALIBRATOR_IMPL             # "platt" (default; "isotonic" gated behind label count ≥1000, DEC-5)
JWT_SECRET_KEY              # P4-1 auth; empty = authed endpoints 503 (fail loudly, never open)
JWT_EXPIRY_SECONDS          # session TTL (default 43200 = 12h)
AUTH_COOKIE_SECURE          # Secure flag on session cookie (enable behind HTTPS)
CORS_ORIGINS                # comma-separated SPA origins (default http://localhost:5173)
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
    claims: list[Claim]            # checkable against retrieved manual excerpts, cite [doc-id pN]
    reasoning: list[str] = []      # world-knowledge / next steps — VERIFY does NOT gate these (P3-1.5)
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
- **Sufficiency check** `[IMPL: src/hero/graph/nodes/retrieve.py]` (P4-5, INV-5): after evidence
  assembly, BOTH retrieve nodes (full and fast path) make a verify-tier `assess_sufficiency` call
  (`prompts/sufficiency.md`) judging whether evidence + ticket plausibly support a diagnosis;
  insufficient → sets `pending_question` (ONE concrete, tenant-answerable question) and the existing
  RETRIEVE→CLARIFY conditional routes to the interrupt. A triage "simple" verdict cannot skip the
  check — an insufficient ticket never reaches DIAGNOSE unasked; an insufficient fast-path ticket
  CLARIFYs and loops back into the FULL path (CLARIFY always re-enters `retrieve`, BL-4).
  Deterministic guardrails, checked BEFORE the call: never when a question is already pending,
  never after ANY clarify round (at most one check per ticket — the loop-back never re-asks a
  tenant who already answered, and never re-pays the tax), and never on hazards —
  `safety.gate.clarify_allowed` (pure, no LLM) blocks CLARIFY for hard-escalate trades and
  hazard-keyword descriptions, which also skips the per-ticket sufficiency tax. Fails open: parse
  failure or a generic question (`parse_sufficiency` rejects "please provide more details"-style
  output, `SufficiencyParseError`) proceeds to DIAGNOSE — VERIFY + the safety gate still gate the
  output, and a generic question never reaches a tenant.
- **Single resume path rule** `[IMPL: src/hero/api/resume.py]` (P4-4 hardening): every resume of a
  CLARIFY-interrupted run MUST go through `hero.api.resume.resume_with_answer` — it snapshots the
  pending question *before* resuming (not recoverable from state history afterwards) and appends the
  `clarify_answered` + resumed-run events to the ledger. The API graph wrapper
  (`deps.get_graph` → `_ResumeGuardedGraph`) raises `ResumeNotAllowedError` on any other
  `Command(resume=…)`, so an out-of-path resume fails loudly instead of leaving the ledger missing
  the question. The offline eval builds its own graph via `build_graph` and is exempt — it writes no
  ledger rows.
- Conditional edges: `TRIAGE → {retrieve_fast | retrieve}` on `complexity` (BL-4) —
  two distinct graph nodes (`retrieve_fast` = `make_retrieve(..., fast_path=True)`), so the
  taken path is visible in checkpoints and eval traces; CLARIFY always loops back to full
  `retrieve` (a ticket that needed clarification is not "simple");
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
    tenant_contact  TEXT,                 -- P4-4 public intake: phone/email for the CLARIFY loop [IMPL: alembic/versions/0006_building_public_intake.py]
    public_slug     TEXT UNIQUE,          -- P4-4: unguessable per-ticket status link; NULL for operator-created tickets
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ON ticket (public_slug);

CREATE TABLE media (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID NOT NULL REFERENCES ticket(id),
    object_key      TEXT NOT NULL,        -- R2 pointer ONLY (INV-3)
    media_type      TEXT NOT NULL,
    sha256          TEXT,                 -- nullable since P4-4: public phone uploads on http LAN have no crypto.subtle; best-effort, never invented
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
    claim_type      TEXT NOT NULL DEFAULT 'descriptive',  -- part_number|descriptive (BL-6/DEC-19)
    grounded        BOOLEAN NOT NULL,
    evidence        JSONB NOT NULL        -- {chunks: [{doc_id, page, region?, score}]}
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
    verdict         TEXT,                 -- confirmed|partially_correct|wrong; NULL when unlabeled
    actual_fault    TEXT,                 -- required when verdict != confirmed
    actual_part_sku TEXT,
    contractor_id   UUID,
    free_text       TEXT,
    unlabeled_reason TEXT,                -- explicit reason if label unobtainable
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT verdict_or_reason CHECK (verdict IS NOT NULL OR unlabeled_reason IS NOT NULL),
    -- P3-2 hardening: closed verdict vocabulary; corrections must carry the actual fault
    CONSTRAINT verdict_allowed CHECK (verdict IS NULL OR verdict IN ('confirmed', 'partially_correct', 'wrong')),
    CONSTRAINT correction_has_fault CHECK (verdict IS NULL OR verdict = 'confirmed' OR actual_fault IS NOT NULL)
);
CREATE INDEX ON contractor_statement (created_at);   -- flywheel scans; DuckDB split later (DEC-4)

CREATE TABLE app_user (                   -- P4-1 auth [IMPL: alembic/versions/0004_app_user.py]
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,        -- scopes every ticket query (repo.get_ticket_for_org)
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,        -- argon2id; never plaintext, never reversible
    role            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT role_allowed CHECK (role IN ('operator', 'contractor', 'admin'))
);
CREATE INDEX ON app_user (org_id);
-- No self-signup: rows seeded via `python -m hero.auth seed`. Sessions are stateless
-- HS256 JWTs (sub/org/role claims) in an httponly cookie; revocation = rotate JWT_SECRET_KEY.

CREATE TABLE ticket_event (                -- P4-3 ledger [IMPL: alembic/versions/0005_ticket_event.py]
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id       UUID NOT NULL REFERENCES ticket(id),
    run_id          TEXT NOT NULL,        -- thread id ("ticket-{id}"); shared by create + resume runs
    seq             INTEGER NOT NULL,     -- per-ticket order; resume runs continue the sequence
    state           TEXT NOT NULL,        -- triage|retrieve|clarify_pending|clarify_answered|diagnose|verify|safety_gate|procure
    payload         JSONB NOT NULL DEFAULT '{}',  -- state substance; NO chunk text, NO claim rows (canonical in diagnosis_claim, DEC-6)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON ticket_event (ticket_id, seq);
-- Append-only, written by the API layer after a graph run (nodes never touch the DB).
-- Ledger assembly (storage/ledger.py) synthesizes intake from the ticket row and outcome
-- from contractor_statement; states that never ran produce no rows (honest gaps).

CREATE TABLE building (                   -- P4-4 tenant intake [IMPL: alembic/versions/0006_building_public_intake.py]
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE, -- unguessable (token_urlsafe(24)); IS the tenant credential — no accounts, no login
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON building (org_id);
-- Rows created only via `python -m hero.buildings create` (prints the intake link).
-- ticket.building_id keeps NO FK to this table: operator tickets predate it and carry
-- caller-supplied building ids; public intake always sets a real building.id.
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
    async def triage(self, description: str) -> TriageResult: ...          # BL-4, verify tier (DEC-18 amended; DEC-21 fail-safes live in the node)
    async def diagnose(self, state: TicketState) -> list[Hypothesis]: ...
    async def decompose_claims(self, hypothesis_text: str) -> list[str]: ...
    async def check_entailment(self, claim: str, evidence_text: str) -> bool: ...
    async def assess_sufficiency(self, state: TicketState) -> SufficiencyResult: ...  # P4-5 (INV-5), verify tier — see §4 sufficiency check

# catalog.py  (OPEN-1: schema behind interface because catalog source is undecided)
class CatalogResolver(Protocol):
    async def resolve(self, part_need: str, trade: str) -> Optional[str]: ...  # returns SKU
```

---

## 7. Retrieval Pipeline `[IMPL: src/hero/retrieval/hybrid.py, src/hero/ingestion/, src/hero/graph/nodes/retrieve.py]` — `src/hero/retrieval/`

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

## 8. Verification `[IMPL: src/hero/graph/nodes/verify.py, src/hero/verification/claims.py, src/hero/adapters/platt.py]` — `src/hero/verification/`

Per hypothesis: for each claim → classify → gather top evidence text
(`EvidenceChunk.text` from the Qdrant payload, top-5 post-rerank) →
`VLM.check_entailment(claim, evidence)` (VERIFY model tier, DEC-18) → `Claim.grounded`.
DIAGNOSE receives the **same evidence excerpts** VERIFY entails against (P3-1.5) — claims
cite them; `Hypothesis.reasoning` (world-knowledge/next steps) is **not** gated by VERIFY.
Entailment calls fan out with `asyncio.gather` under a semaphore bounded at 5 concurrent,
order-preserving. Zero hypotheses ⇒ `verify_pass = False` (never vacuously true).
**Claim classifier (BL-6 ✅ / DEC-6):** deterministic regex in
`verification/claims.py` (data-as-code, no LLM) tags each claim
`part_number` or `descriptive`; per-type thresholds from config:
`GROUNDING_THRESHOLD_STRICT` (default 1.0) for part-number/model-code claims,
`GROUNDING_THRESHOLD` (default 0.8) for descriptive claims.
`verify_pass` = every hypothesis clears the threshold for **each claim type present**.
Per-claim results (text, type, grounded, evidence citations) are persisted to
`diagnosis_claim` by the API layer via `storage/repo.persist_diagnosis_from_state`
(nodes never touch the DB). Calibrators (DEC-5): `PlattCalibrator` default,
`IsotonicCalibrator` self-gated ≥1000 labels, binned ECE reported per eval run (BL-2 ✅).
The **per-claim rate** is what's persisted and evaluated (DEC-6), never an answer-level average alone.
`calibrated_confidence = Calibrator.calibrate(grounding_rate, trade)` — the only confidence
number that ever leaves the system (INV-4).

## 9. Safety Gate `[IMPL: src/hero/safety/gate.py, src/hero/safety/hazards.py]` — `src/hero/safety/`

Pure deterministic functions. **No LLM calls in this module.**

```python
HARD_ESCALATE_TRADES = {"gas", "electrical_high_voltage", "structural", "water_intrusion"}

def safety_gate(state: TicketState) -> SafetyDecision:
    if state.escalation_reason == "diagnosis_unparseable":
        return escalate("diagnosis_unparseable")  # set by DIAGNOSE on parse failure (P3-1.5)
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
- Cost is **measured**, not estimated: the LiteLLM adapter accumulates per-tier
  `{calls, cost_usd, tokens}` (`drain_usage()`), reported per ticket and per run split by tier.
  Per-node latency is timed from the graph's `astream(stream_mode="updates")` chunks.
- `--runs N` repeats each ticket N times and reports mean/min/max grounding and cost —
  primary-tier outputs are non-deterministic (model rejects `temperature`; DEC-20), so a
  single run is a sample, not a measurement.
- Live mode auto-ingests the fixture manuals (plumbing/HVAC/gas) so no trade's grounding
  is structurally 0.00 for lack of corpus.
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
- **Tracing `[IMPL: src/hero/observability/tracing.py]`:** every node wrapped with
  `traced_node` in `build.py`; span name = node name; one trace per ticket (trace id seeded
  from `ticket_id`); metadata includes `ticket_id`, `EMBEDDER_IMPL`, `RERANKER_IMPL` (bake-off
  attribution). No-op passthrough when `LANGFUSE_*` unset; span outputs are scalar summaries
  of the node's state delta, never full evidence text; `flush()` on API shutdown + eval end.
- **Prompts:** live in `src/hero/prompts/*.md` as files, versioned in git, loaded at startup —
  never inline f-strings in nodes. Prompt changes trigger the eval CI job.
- **Index integrity `[IMPL: src/hero/retrieval/integrity.py]`:** every Qdrant point is stamped
  with `tokenizer_version` at ingestion (`ingestion/ingest.py:TOKENIZER_VERSION` — bump on any
  incompatible tokenizer/schema change). Wherever a Qdrant client is wired in (eval harness
  today; API startup once retrieval lands there), run `check_index_integrity` (version-stamp
  sweep) **and** `bm25_canary` (known-present term must return >0 BM25 results) before serving
  queries; the query side additionally rejects any returned point with a stale stamp. Mismatch
  raises `IndexIntegrityError` — never degrade silently. Born from the 2026-07-10 incident:
  builtin `hash()` randomization left the sparse index silently dead and dense+RRF masked it.
- **Types:** mypy --strict passes. No `Any` in `graph/`, `interfaces/`, `safety/`.
- **Lockfiles (asymmetric, deliberate):** `web/package-lock.json` is committed (npm resolution
  is too loose to reproduce without it); `uv.lock` stays gitignored — `pyproject.toml` pins are
  tight enough for a single-service repo and the team predates the lockfile in CI.

## 12. Definition of Done — active backlog

| BL | Done means |
|---|---|
| BL-0 | `contractor_statement` table + `POST /outcomes` endpoint + `test_flywheel.py` green + label-velocity metric (`GET /outcomes/metrics/label-velocity` ✅; Langfuse dashboard pending). P3-2 hardening: `update_ticket_status` raises `FlywheelViolationError` on `resolved` without a statement; `verdict_allowed` + `correction_has_fault` CHECKs (migration 0003) mirrored in API validation |
| BL-1 | `Reranker` Protocol + bge adapter + wired into full path + eval shows hit-rate@5 lift + Cohere adapter behind config flag |
| BL-2 | `platt.py` adapter default; isotonic adapter exists but gated on label_count ≥ 1000; ECE reported per eval run |
| BL-3 | `evals/` runnable locally + CI; ≥20 golden tickets seeded |
| BL-4 | ✅ VLM `triage()` (verify tier per DEC-18 amendment) + `TriageResult` Literal vocabulary gate + DEC-21 keyword fail-safes in `graph/nodes/triage.py`; `retrieve_fast` node behind `TRIAGE` conditional edge; eval prints per-ticket `complexity=`/`path=` and a fast-vs-full "Path split" section (latency, cost, retrieve-node latency); `test_triage_routing.py` covers parse gate, fail-safes, routing |
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
