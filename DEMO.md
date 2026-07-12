# Hero.AI — Pilot Demo Rehearsal Script

The full loop, end to end: seed an org, file a ticket from a phone with a photo, answer a
CLARIFY question as the tenant, inspect the ledger as the operator, file the outcome as the
contractor. Runnable by anyone with this repo, local Postgres, and R2 credentials.

**Assumptions**
- Postgres running locally (ca-central data residency applies to real deployments — INV-2).
- Cloudflare R2 bucket + credentials in hand (photo uploads presign directly to R2 — INV-3).
- `uv` and `node`/`npm` installed. Qdrant NOT required (retrieval runs in stub mode).
- Model calls are stubbed by default — the demo pipeline is deterministic and free.
  (Real VLM adapters are a code-level choice in `src/hero/api/deps.py:get_graph()`, not an
  env var. Stub mode is the rehearsal default and is what this script assumes.)

---

## 0. One-time setup

```bash
uv sync                # Python deps
(cd web && npm install)  # SPA deps

cp .env.example .env
```

Edit `.env` — the demo needs these filled in:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://hero:hero@localhost:5432/hero` (adjust to your local PG) |
| `JWT_SECRET_KEY` | any random 32+ char string — auth returns 503 if unset |
| `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | your R2 bucket |
| `AUTH_COOKIE_SECURE` | `False` for plain-HTTP local dev |

Everything else (Qdrant, Langfuse, model API keys) is optional for the demo and can stay blank.

Migrate the schema:

```bash
uv run alembic upgrade head
```

## 1. Seed the org, users, and building

There is no signup UI and no building CRUD UI — the CLI is the only way. Run these in order
and **copy the printed IDs**.

```bash
# 1a. First user — omit --org-id to mint a new org (the org UUID is printed)
uv run python -m hero.auth seed --email operator@example.com --role operator --password demopass123
# → [SEED] created operator operator@example.com id=... org_id=<ORG_ID>   ← copy ORG_ID

# 1b. Contractor in the SAME org
uv run python -m hero.auth seed --email contractor@example.com --role contractor \
  --org-id <ORG_ID> --password demopass123

# 1c. Building → prints the tenant intake link (--base-url comes BEFORE the subcommand)
uv run python -m hero.buildings create --org-id <ORG_ID> --name "12 Main St"
# → [BUILDING] tenant intake link: http://localhost:5173/#/intake/<slug>   ← copy this link
```

Notes:
- Omit `--password` to be prompted (keeps it out of shell history) — fine either way for a demo.
- The intake slug is unguessable and **is** the tenant credential. No tenant accounts exist.
- `uv run python -m hero.buildings list --org-id <ORG_ID>` re-prints links if you lose one.
- Demoing from a phone? Use your machine's LAN IP:
  `uv run python -m hero.buildings --base-url http://<LAN-IP>:5173 create --org-id <ORG_ID> --name "12 Main St"`

## 2. Start the services (two terminals)

```bash
# Terminal 1 — API on :8000 (0.0.0.0 so a phone on the LAN can reach it)
uv run uvicorn hero.api.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — SPA on :5173 (Vite proxies /auth /tickets /outcomes /uploads /public → :8000)
cd web && npm run dev
```

Sanity check: `http://localhost:8000/docs` loads Swagger; `http://localhost:5173` shows the
login screen.

## 3. Tenant intake (public — phone or browser, no login)

1. Open the intake link from step 1c: `http://localhost:5173/#/intake/<slug>`.
   The building name ("12 Main St") renders at the top — confirms the slug is valid.
2. **Description** — for the CLARIFY story, use the vague one:
   > Something in our unit is broken and it keeps making a strange rattling sound at night. No idea what it is.
   (For a straight-through run instead: "The radiator in the living room is cold and makes a banging noise.")
3. **Photos** — attach 1–2 images (max 6, 10 MB each). Each photo is presigned and PUT
   directly to R2 by the browser; bytes never touch the API or Postgres.
4. **Contact** — any phone/email string.
5. Submit → confirmation screen with a **status link** (`#/status/<status_slug>`).
   **Save this link** — it is the tenant's only handle on the ticket.

The pipeline runs on submit: INTAKE → TRIAGE → RETRIEVE (sufficiency check) → …

## 4. CLARIFY round (public status page)

1. Open the saved status link. With the vague description above, the state reads
   **"question for you"** and a concrete question appears (e.g. "Which appliance or fixture
   is the problem, and where in the unit is it located?").
2. Type the answer, e.g.:
   > It turned out to be the pipe under the kitchen sink — the curved section drips and rattles whenever water runs.
3. **Send answer** → the graph resumes, loops back through full retrieval, and completes:
   DIAGNOSE → VERIFY → SAFETY_GATE → RESOLVE → PROCURE. Status now shows **"being handled"**.

Plain-language states tenants see: received / question for you / looking into it (escalated) /
being handled / resolved. Pipeline vocabulary never leaks to tenants.

Optional safety beat for the demo: file a second ticket reading "I smell gas near the stove" —
it never asks a question and immediately shows "looking into it" (hard escalation, INV-1).

## 5. Operator ledger (authenticated)

1. Go to `http://localhost:5173`, log in as `operator@example.com` / `demopass123`.
2. Ticket list (`#/tickets`) shows the ticket with trade/urgency/status badges.
3. Click the ticket → **full append-only ledger**: every state that ran with timestamps —
   intake, triage (trade/complexity/path), retrieve citations (doc_id + page + stage),
   `clarify_pending` (the question, "awaiting tenant answer" badge), `clarify_answered`
   (question + the tenant's answer), diagnose hypotheses with calibrated confidence, verify
   grounding marks per claim, safety-gate verdict, procurement work order.
4. If a ticket is stuck in "clarifying" and the tenant is unreachable, the operator can answer
   from this screen (POST `/tickets/{id}/clarify-answer` under the hood).

## 6. Contractor outcome — 3 taps (authenticated)

1. Log out, log in as `contractor@example.com` / `demopass123`.
2. Click the same ticket → contractors get the narrower **outcome screen** (diagnosis +
   suggested part), not the ledger.
3. File the outcome:
   - **Tap 1** — verdict: Confirmed / Partially right / Wrong (or "Can't assess" + reason).
   - **Tap 2** — if not Confirmed: enter the actual fault (required), part SKU (optional).
   - **Tap 3** — submit.
4. The ticket transitions to **resolved** and a `contractor_statement` row is written — the
   flywheel signal (BL-0). A ticket cannot reach `resolved` any other way (PRD §9), and the
   statement is immutable once filed.
5. Re-open the tenant status link: it now reads **resolved**. Full loop closed.

---

## Gotchas (learned the hard way)

- **Rate limits are per-slug per-hour**: 10 intakes / 30 presigns per building link,
  20 answers per status link. Rapid rehearsal loops will hit 429 — mint a fresh building
  link (`hero.buildings create`) or restart the API (limiter is in-memory).
- **Phone on LAN over plain HTTP**: photo SHA-256 hashing (crypto.subtle) is unavailable —
  it's best-effort and nullable, uploads still work. Keep `AUTH_COOKIE_SECURE=False`.
- **CLARIFY asks at most one organic question per ticket** (INV-5) and never re-asks after
  the answer. Hazard tickets (gas, sparking, flooding…) are never asked anything — they
  escalate straight away.
- **Wording matters for the demo script**: "water"/"leak" in the description triages to
  water_intrusion → hard escalation. Use the exact vague description above for the CLARIFY
  story.
- **`--base-url` must precede the subcommand** in `hero.buildings` (it's a top-level flag).
- **`JWT_SECRET_KEY` unset → 503** on all auth endpoints; **no `contractor_statement` → ticket
  can never show resolved** — both are working as designed, not bugs.
- **Cross-org access returns 404, not 403** — no existence leak; don't be surprised in testing.

## Quick reference

| Actor | Entry point | Auth |
|---|---|---|
| Tenant intake | `#/intake/<building-slug>` | link possession only |
| Tenant status + clarify answer | `#/status/<status-slug>` | link possession only |
| Operator (ledger) | `#/tickets` → click ticket | `operator@example.com` / `demopass123` |
| Contractor (outcome) | `#/tickets` → click ticket | `contractor@example.com` / `demopass123` |
| Swagger | `http://localhost:8000/docs` | — |
